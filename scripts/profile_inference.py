"""Profile real GNN calls over every supported graph size; not a WCET proof."""
import argparse
import hashlib
import json
import platform
import uuid
from datetime import datetime,timezone
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import torch
from rts_predictive.domain.research import default_research_config
from rts_predictive.simulator.research_engine import ResearchEngine
from rts_predictive.predictors.research_adapter import ResearchModels
from rts_predictive.artifacts.inference_timing import summarize_timings
from rts_predictive.artifacts.code_provenance import code_provenance


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats',type=int,default=20)
    parser.add_argument('--budget-us',type=int,default=10000)
    parser.add_argument('--output',default='.validation/inference-hardware-profile.json')
    args=parser.parse_args()
    if args.repeats<1 or args.budget_us<1:parser.error('positive repeats and budget required')
    torch.set_num_threads(1)
    models=ResearchModels()
    engine=ResearchEngine(default_research_config(),policy='edf')
    engine.run_until(0)
    tasks=list(engine.tasks.values())
    # Four devices x six stages = 24 task nodes. Inputs are explicitly profile
    # fixtures, not purported scheduling outcomes or prediction-accuracy evidence.
    resource=engine.resource('Device_1')
    records=[]
    for count in range(1,25):
        batch=tasks[:count]
        for _ in range(3):models.predict(batch[0],batch,resource,0)
        for repetition in range(args.repeats):
            prediction=models.predict(batch[0],batch,resource,0)
            records.append({'task_nodes':count,'repetition':repetition,
                            'graph_sha256':prediction['graph_sha256'],
                            'latency_us':prediction['host_latency_us']})
    weights=Path(__file__).resolve().parents[1]/'models/research_gnn.pt'
    summary=summarize_timings(records,model_sha256=hashlib.sha256(weights.read_bytes()).hexdigest(),
        environment={'python':platform.python_version(),'platform':platform.platform(),
                     'processor':platform.processor(),'torch':torch.__version__,'threads':torch.get_num_threads()},
        budget_us=args.budget_us)
    summary['coverage']='1..24 task nodes; configured task-resource graph fixtures; three warmups per size'
    summary['manifest']={'schema_version':'inference-profile-run/1.0','run_id':uuid.uuid4().hex,
                         'created_utc':datetime.now(timezone.utc).isoformat(),
                         'configuration_hash':engine.config.config_hash,
                         'raw_sha256':summary['raw_sha256'],**code_provenance()}
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k!='records'},indent=2))


if __name__=='__main__':main()
