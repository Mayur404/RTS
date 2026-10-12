"""Train/calibrate a research GNN from observed future no-intervention outcomes."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import argparse
import hashlib
import json
import zipfile
import torch
from rts_predictive.domain.research import default_research_config
from rts_predictive.simulator.research_engine import ResearchEngine
from rts_predictive.predictors.research_adapter import ResearchModels
from rts_predictive.gnn.model import load_pretrained_gnn
from rts_predictive.gnn.dataset import RolloutSample
from rts_predictive.gnn.trainer import GNNTrainer
from rts_predictive.gnn.calibration import TemperatureCalibrator,select_f1_threshold
from rts_predictive.artifacts.events import CanonicalEventWriter
from rts_predictive.artifacts.code_provenance import code_provenance


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--epochs",type=int,default=10)
    parser.add_argument("--output",default="models/research_gnn.pt")
    parser.add_argument("--data",default=".validation/research-training")
    args=parser.parse_args();torch.set_num_threads(1);torch.manual_seed(53)
    output=Path(args.output);root=Path(args.data);root.mkdir(parents=True,exist_ok=True)
    split_seeds={"train":list(range(4100,4106)),"validation":[4200,4201],"test":[4300,4301]}
    datasets={k:[] for k in split_seeds};records=[];raw_samples=[]
    source=code_provenance()
    archive=root/'source.zip'
    workspace=Path(__file__).resolve().parents[1]
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for path in sorted((workspace/'rts_predictive').rglob('*.py')):
            z.write(path,path.relative_to(workspace).as_posix())
        z.write(Path(__file__),'scripts/train_research_gnn.py')
        for path in sorted((workspace/'models').glob('*')):
            if path.suffix in {'.pt','.json'}:z.write(path,path.relative_to(workspace).as_posix())
    source['source_archive_sha256']=hashlib.sha256(archive.read_bytes()).hexdigest()
    for split,seeds in split_seeds.items():
        families=["bursty","thermal"] if split!="test" else ["bursty","thermal","unreliable"]
        for seed in seeds:
            for family in families:
                config=default_research_config(seed,family,650000)
                run_id=f"research-dataset-{split}-{family}-{seed}"
                sim=ResearchEngine(config,"edf",run_id=run_id)
                pending=[]
                def observe(event):
                    if event["event_type"]!="TASK_READY":return
                    task=sim.tasks[event["task_id"]]
                    if not (task.spec.offloadable or task.spec.exit_points):return
                    active=[t for t in sim.tasks.values() if t.origin==task.origin and t.status not in {"COMMITTED","MISSED","SKIPPED"}]
                    resource=sim.resource(task.origin)
                    x,edge,digest=ResearchModels.graph(task,active,resource,sim.now)
                    cause=1 if resource["background_gpu_ppm"]>=resource["background_cpu_ppm"] else 0
                    pending.append((task.uid,sim.now,x,edge,digest,cause))
                sim.subscribe(observe);sim.run_until(config.end_us)
                failures={e["task_id"]:e["timestamp_us"] for e in sim.events if e["event_type"]=="TASK_DEADLINE"}
                event_path=root/f"{run_id}.jsonl"
                with CanonicalEventWriter(event_path,run_id) as writer:
                    for event in sim.events:writer.write(event)
                    digest=writer.sha256
                manifest={"schema_version":"rts_predictive.research-training-run/1.0","run_id":run_id,
                          "split":split,"seed":seed,"family":family,"config":config.to_dict(),
                          "event_file":str(event_path.resolve()),"event_sha256":digest,**source}
                manifest_path=root/f"{run_id}.manifest.json"
                manifest_path.write_text(json.dumps(manifest,indent=2),encoding="utf-8")
                records.append(str(manifest_path.resolve()))
                for uid,at,x,edge,digest,cause in pending:
                    failed=uid in failures
                    delay=(failures[uid]-at)/1e6 if failed else 0
                    sample=RolloutSample(x,edge,float(failed),delay,cause,sim.tasks[uid].origin,at/1000,failed)
                    datasets[split].append(sample)
                    raw_samples.append({"run_id":run_id,"task":uid,"timestamp_us":at,"split":split,
                                        "graph_sha256":digest,"x":x.tolist(),"edge_index":edge.tolist(),
                                        "failure":int(failed),"failure_delay_s":delay,"resource_cause_proxy":cause})
        print(f'{split}: {len(datasets[split])} observed graphs',flush=True)
    data_path=root/"graphs.json"
    data_path.write_text(json.dumps({"schema_version":"research-gnn-dataset/1.0","runs":records,"samples":raw_samples}),encoding="utf-8")
    for split,samples in datasets.items():
        labels={int(s.y_risk.item()) for s in samples}
        if labels!={0,1}:raise RuntimeError(f"{split} does not contain both observed classes")
    model=load_pretrained_gnn();trainer=GNNTrainer(model=model)
    history=[];best_loss=float("inf");best_weights=None
    for epoch in range(args.epochs):
        # Shuffle only training graphs with a recorded torch seed.
        order=torch.randperm(len(datasets["train"])).tolist()
        stats=trainer.train_epoch([datasets["train"][i] for i in order])
        model.eval();probabilities=[];outcomes=[]
        with torch.no_grad():
            for s in datasets["validation"]:
                r,_,_=model(s.x,s.edge_index);probabilities.append(float(r.item()));outcomes.append(int(s.y_risk.item()))
        loss=sum(-(y*__import__('math').log(max(p,1e-7))+(1-y)*__import__('math').log(max(1-p,1e-7))) for p,y in zip(probabilities,outcomes))/len(outcomes)
        if loss<best_loss:
            best_loss=loss;best_weights={k:v.detach().clone() for k,v in model.state_dict().items()}
        history.append({"epoch":epoch+1,"training_loss":stats["loss"],"validation_log_loss":loss})
        print(f'epoch {epoch+1}: validation log loss {loss:.4f}',flush=True)
    model.load_state_dict(best_weights);model.eval();probabilities=[];outcomes=[]
    with torch.no_grad():
        for s in datasets["validation"]:
            r,_,_=model(s.x,s.edge_index);probabilities.append(float(r.item()));outcomes.append(int(s.y_risk.item()))
    calibrator=TemperatureCalibrator.fit(probabilities,outcomes)
    threshold=select_f1_threshold([calibrator.apply(p) for p in probabilities],outcomes)
    test_metrics=trainer.evaluate(datasets["test"],calibrator,threshold)
    output.parent.mkdir(parents=True,exist_ok=True);torch.save(model.state_dict(),output)
    bundle={"bundle_version":"research-gnn/1.0","feature_schema":"research-task-resource/9-v3",
            "weights_sha256":hashlib.sha256(output.read_bytes()).hexdigest(),
            "calibration":{"method":"temperature_scaling","temperature":calibrator.temperature},
            "decision_threshold":threshold,"test_metrics":test_metrics,
            "dataset_file":str(data_path.resolve()),"dataset_sha256":hashlib.sha256(data_path.read_bytes()).hexdigest(),
            "split_seeds":split_seeds,"training_families":["bursty","thermal"],
            "test_families":["bursty","thermal","unreliable"],
            "labels":"observed future firm-task failure (deadline or workflow drop) in EDF no-intervention rollout",
            "calibration_scope":"EDF TASK_READY graphs; protected checkpoints and shifted policies require separate calibration validation",
            "cause_scope":"resource-state proxy, not experimentally established causal attribution",
            "training":{"epochs":args.epochs,"torch_seed":53,"history":history},**source}
    output.with_suffix(".bundle.json").write_text(json.dumps(bundle,indent=2),encoding="utf-8")
    print(json.dumps(test_metrics),flush=True)


if __name__=="__main__":main()
