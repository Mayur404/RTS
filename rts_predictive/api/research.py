"""Finite paired research sessions with raw event and model provenance."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib
import json
import threading
import uuid
import zipfile
import platform
from dataclasses import replace
from copy import deepcopy
from importlib.metadata import version
import torch
from fastapi import APIRouter,HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field
from typing import Literal
from rts_predictive.api.scenario_designer import ScenarioInput, template
from rts_predictive.domain.research import default_research_config
from rts_predictive.simulator.research_engine import ResearchEngine
from rts_predictive.predictors.research_adapter import ResearchModels
from rts_predictive.dashboard.research_projection import ResearchProjection,paired_comparison
from rts_predictive.artifacts.events import CanonicalEventWriter
from rts_predictive.artifacts.code_provenance import code_provenance

router=APIRouter(prefix="/api/research",tags=["Layered research simulation"])
ROOT=Path(__file__).resolve().parents[2]
SESSIONS={}
STORE_LOCK=threading.RLock()


class ResearchStart(BaseModel):
    seed:int=Field(default=1000,ge=0)
    family:Literal["nominal","bursty","thermal","unreliable"]="bursty"
    release_end_us:int=Field(default=1_200_000,ge=100_000,le=5_000_000)
    host_inference_budget_us:int=Field(default=10_000,ge=1)
    enforce_host_inference_budget:bool=False
    scenario:ScenarioInput | None=None
    baseline:Literal["edf","fifo","rm","always_offload","reactive","predictive_no_fallback"]="edf"


class ResearchStep(BaseModel):
    delta_us:int=Field(default=6000,ge=1,le=100_000)


class ResearchSessionClosedError(RuntimeError):
    """A request retained a session reference after its deletion."""


class PairedResearchSession:
    def __init__(self,config,output_root=None,baseline="edf",custom_scenario=False,**features):
        torch.set_num_threads(1)
        self.id=uuid.uuid4().hex
        if baseline not in {"edf","fifo","rm","always_offload","reactive","predictive_no_fallback"}:raise ValueError("unsupported baseline")
        self.baseline=baseline
        self.config=config;self.lock=threading.RLock();self.finalized=False;self.closed=False
        self.root=Path(output_root or ROOT/".validation"/"research-sessions")/self.id
        self.root.mkdir(parents=True,exist_ok=False)
        self.source=code_provenance()
        self.environment={"python":platform.python_version(),"platform":platform.platform(),
                          "torch":torch.__version__,"torch_geometric":version("torch-geometric"),
                          "numpy":version("numpy")}
        # Preserve the actual dirty source and starting bundles, not just HEAD.
        archive=self.root/"source.zip"
        with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as z:
            paths=list((ROOT/"rts_predictive").rglob("*.py"))+list((ROOT/"scripts").glob("*.py"))
            paths+=list((ROOT/"models").glob("*.pt"))+list((ROOT/"models").glob("*.json"))
            paths += [p for p in (ROOT/"frontend").rglob("*") if p.is_file() and p.suffix in {".html",".css",".js",".svg"}]
            paths += [ROOT/"UI Design.md",ROOT/"Implementation Plan.md",ROOT/"README.md"]
            paths += list((ROOT/"docs/adr").glob("*.md"))
            for path in sorted(paths):z.write(path,path.relative_to(ROOT).as_posix())
        self.source["source_archive_sha256"]=hashlib.sha256(archive.read_bytes()).hexdigest()
        self.models=ResearchModels()
        if custom_scenario:
            self.models.validation_scope="custom_scenario_unvalidated"
        from rts_predictive.verification.research_reference import control_partition_reference
        self.reference=control_partition_reference(config,self.source)
        (self.root/"analytical-reference.json").write_text(json.dumps(self.reference,indent=2),encoding="utf-8")
        self.projections={};self.engines={};self.writers={};self.manifests={}
        gnn_path=ROOT/"models"/("research_gnn.pt" if self.models.validation_scope!="transfer_unvalidated" else "gnn_predictive_runtime.pt")
        self.model_identity={"gnn_bundle":self.models.gnn.bundle_version,"gnn_sha256":hashlib.sha256(gnn_path.read_bytes()).hexdigest(),
                             "remote_sha256":hashlib.sha256((ROOT/"models/federated_remote_estimator.pt").read_bytes()).hexdigest(),
                             "validation_scope":self.models.validation_scope,"threshold":self.models.gnn.decision_threshold}
        (self.root/"config.json").write_text(config.to_json(),encoding="utf-8")
        for policy in [baseline,"protected"]:
            directory=self.root/policy;directory.mkdir()
            policy_models=self.models if policy=="protected" else ResearchModels() if policy=="predictive_no_fallback" else None
            if custom_scenario and policy_models is not None:
                policy_models.validation_scope="custom_scenario_unvalidated"
            engine=ResearchEngine(config,policy,policy_models,
                                  run_id=f"{self.id}-{policy}",**features)
            projection=ResearchProjection();writer=CanonicalEventWriter(directory/"events.jsonl",engine.run_id)
            for event in engine.events:writer.write(event);projection.consume(event)
            def record(event,w=writer,p=projection):
                w.write(event);p.consume(event)
            engine.subscribe(record)
            self.engines[policy]=engine;self.projections[policy]=projection;self.writers[policy]=writer
            self.manifests[policy]={"schema_version":"rts_predictive.research-run/1.0","run_id":engine.run_id,
                "pair_id":self.id,"policy":policy,"seed":config.seed,"family":config.family,
                "configuration_hash":config.config_hash,"configuration_file":str((self.root/"config.json").resolve()),
                "models":self.model_identity if engine.neural else {},"features":features,
                "created_utc":datetime.now(timezone.utc).isoformat(),"status":"RUNNING",**self.source,
                "environment":self.environment,
                "event_file":str((directory/"events.jsonl").resolve()),
                "assumptions":["integer microsecond work/time; PPM rates","one CPU slot; one layer GPU slot",
                               "declared GPU CPU reservation and memory","configured inference/FL work, separate observed host latency",
                               "firm workflow drop after predecessor failure","payload-byte link serialization; shared sender radio",
                               "thermal and output utility models are scenario assumptions, not hardware measurements",
                               "shared current-state telemetry available to simulated controllers; no telemetry transport delay modeled",
                               "delivery reliability formula assumes independent retries and stationary configured packet loss",
                               "remote neural head estimates execution service/reliability, not end-to-end network time"]}
            self._write_manifest(policy)
        self.engines[baseline].run_until(0);self.engines["protected"].run_until(0)

    def _write_manifest(self,policy):
        w=self.writers[policy];m=self.manifests[policy]
        m.update(event_sha256=w.sha256,event_count=w.count)
        (self.root/policy/"manifest.json").write_text(json.dumps(m,indent=2),encoding="utf-8")

    def step(self,delta):
        with self.lock:
            if self.closed:
                raise ResearchSessionClosedError("Research session is closed")
            at=min(self.engines[self.baseline].now+delta,self.config.end_us)
            for engine in self.engines.values():engine.run_until(at)
            if at==self.config.end_us:self.finalize()
            return self.snapshot()

    def finalize(self):
        if self.finalized:return
        for policy,writer in self.writers.items():
            writer.close();self.manifests[policy]["status"]="COMPLETE"
            metrics=self.projections[policy].metrics()
            if metrics["pending_jobs"]:raise AssertionError("drain left undecided released workflows")
            (self.root/policy/"metrics.json").write_text(json.dumps(metrics,indent=2),encoding="utf-8")
            self.manifests[policy]["metrics_sha256"]=hashlib.sha256((self.root/policy/"metrics.json").read_bytes()).hexdigest()
            self._write_manifest(policy)
        (self.root/"protected"/"host.json").write_text(json.dumps({"evidence":"MEASURED_ON_HOST",
                "observations":self.models.host_observations},indent=2),encoding="utf-8")
        from rts_predictive.artifacts.inference_timing import summarize_timings
        records=[{'sequence':e['sequence'],'task_id':e['task_id'],'timestamp_us':e['timestamp_us'],**e['payload']}
                 for e in self.engines['protected'].events if e['event_type']=='HOST_INFERENCE']
        profile=summarize_timings(records,model_sha256=self.model_identity['gnn_sha256'],
                                 environment=self.environment,budget_us=self.config.host_inference_budget_us)
        (self.root/'protected'/'inference-timing.json').write_text(json.dumps(profile,indent=2),encoding='utf-8')
        torch.save(self.models.remote.state_dict(),self.root/"protected"/"final_remote_model.pt")
        for filename in ["host.json","final_remote_model.pt","inference-timing.json"]:
            self.manifests["protected"][filename+"_sha256"]=hashlib.sha256((self.root/"protected"/filename).read_bytes()).hexdigest()
        self._write_manifest("protected")
        comparison=paired_comparison(self.projections[self.baseline].metrics(),self.projections["protected"].metrics())
        (self.root/"comparison.json").write_text(json.dumps({"schema_version":"research-pair/1.0",
                "pair_id":self.id,"configuration_hash":self.config.config_hash,"comparison":comparison,
                "source_manifests":[str((self.root/p/"manifest.json").resolve()) for p in self.engines]},indent=2),encoding="utf-8")
        self.finalized=True

    def snapshot(self):
        before=self.projections[self.baseline].snapshot();after=self.projections["protected"].snapshot()
        metrics=paired_comparison(before["metrics"],after["metrics"])
        inference=self.projections["protected"].host_latencies
        return {"schema_version":"research-snapshot/1.0","session_id":self.id,"evidence":"SIMULATED",
                "baseline":self.baseline,"time_us":self.engines[self.baseline].now,"end_us":self.config.end_us,"release_end_us":self.config.release_end_us,
                "phase":"COMPLETE" if self.finalized else "DRAIN" if self.engines[self.baseline].now>=self.config.release_end_us else "RELEASE",
                "devices":[d.to_dict() for d in self.config.devices],
                "workflows":[w.to_dict() for w in self.config.workflows],"config_hash":self.config.config_hash,
                "seed":self.config.seed,"family":self.config.family,"comparison":metrics,
                "budgets":{"inference_work_us":self.config.inference_cost_us,
                           "dispatch_work_us":self.config.dispatch_cost_us,
                           "deadline_margin_us":self.config.margin_us,
                           "watchdog_period_us":self.config.watchdog_period_us,
                           "training_work_us_per_sample":self.config.training_work_us_per_sample},
                "runtime_features":{name:getattr(self.engines['protected'],'enable_'+name)
                                    for name in ('watchdog','fl','offload','fallback')},
                "before":before,"after":after,"models":deepcopy(self.model_identity),
                "verification":{"evidence":"ANALYTICAL","status":"UNSUPPORTED_FOR_DYNAMIC_EDF_GPU_OFFLOAD",
                    "live_fallback":{"analysis":"reserved-lane-finite-job-rta",
                        "admitted":self.projections['protected'].counts['FALLBACK_ADMITTED'],
                        "bounded_completions":self.projections['protected'].counts['FALLBACK_BOUND_CHECK'],
                        "scope":"matching admission certificate and enforced queue order; stage only"},
                    "reference":deepcopy(self.reference),
                    "note":"Exact fixed-priority RTA applies only to its hypothetical independent CPU partition; current-rate admission bounds are predictions."},
                "host_latency":{"evidence":"MEASURED_ON_HOST","count":len(inference),
                                "observed_max_us":max(inference) if inference else None,
                                "budget_us":self.config.host_inference_budget_us,
                                "budget_overruns":sum(v>self.config.host_inference_budget_us for v in inference),
                                "hard_wcet_proven":False,
                                "p95_us":sorted(inference)[int(.95*(len(inference)-1))] if inference else None},
                "artifact_urls":{p:{f:f"/api/research/sessions/{self.id}/artifacts/{p}/{f}"
                                     for f in ["manifest.json","events.jsonl","metrics.json"]+(['inference-timing.json'] if p=='protected' else [])}
                                 for p in self.engines} if self.finalized else {}}

    def close(self):
        with self.lock:
            if self.closed:return
            if not self.finalized:
                for policy,writer in self.writers.items():
                    writer.close();self.manifests[policy]["status"]="INTERRUPTED";self._write_manifest(policy)
            self.closed=True


def lookup(uid):
    with STORE_LOCK:
        if uid not in SESSIONS:raise HTTPException(404,"Unknown research session")
        return SESSIONS[uid]


@router.get("/scenarios/templates/{family}")
def scenario_template(family:Literal["nominal","bursty","thermal","unreliable"]):
    return template(family)


@router.post("/scenarios/validate")
def validate_scenario(req:ScenarioInput):
    try:
        config,counts=req.compile()
    except (ValueError,TypeError) as exc:
        raise HTTPException(422,detail={"code":"INVALID_SCENARIO","message":str(exc),"field":"scenario"}) from exc
    return {"valid":True,"configuration_hash":config.config_hash,"evidence":"CONFIGURED",
            "counts":counts,"scenario":req.model_dump(),
            "assumptions":["periodic workflows on every device; firm job drops",
                "one preemptive CPU slot and one four-layer GPU slot per device",
                "task memory is modeled as 32 MiB CPU / 128 MiB GPU",
                "fully connected directed routes with shared sender radios",
                "custom scenarios are outside the pretrained model calibration claim",
                "synthetic prefix outputs and configured utility; no physical robot commands"]}


@router.post("/sessions",status_code=201)
def start(req:ResearchStart):
    if req.scenario is not None:
        try:config,_=req.scenario.compile()
        except (ValueError,TypeError) as exc:
            raise HTTPException(422,detail={"code":"INVALID_SCENARIO","message":str(exc),"field":"scenario"}) from exc
    else:
        config=replace(default_research_config(req.seed,req.family,req.release_end_us),
                     host_inference_budget_us=req.host_inference_budget_us,
                     enforce_host_inference_budget=req.enforce_host_inference_budget)
    with STORE_LOCK:
        if len(SESSIONS)>=32:
            completed=next((uid for uid,s in SESSIONS.items() if s.finalized),None)
            if completed:SESSIONS.pop(completed)
            else:raise HTTPException(429,"Research session capacity reached")
        try:session=PairedResearchSession(config,baseline=req.baseline,custom_scenario=req.scenario is not None)
        except (ValueError,FileNotFoundError,RuntimeError) as exc:raise HTTPException(503,str(exc)) from exc
        SESSIONS[session.id]=session
    return session.snapshot()


@router.post("/sessions/{uid}/step")
def step(uid:str,req:ResearchStep):
    try:
        return lookup(uid).step(req.delta_us)
    except ResearchSessionClosedError as exc:
        raise HTTPException(404,"Unknown research session") from exc


@router.get("/sessions/{uid}")
def snapshot(uid:str):
    session=lookup(uid)
    with session.lock:return session.snapshot()


@router.get("/sessions/{uid}/artifacts/{policy}/{filename}")
def artifact(uid:str,policy:Literal["edf","fifo","rm","always_offload","reactive","predictive_no_fallback","protected"],filename:Literal["manifest.json","events.jsonl","metrics.json","host.json","inference-timing.json"]):
    if len(uid)!=32 or any(c not in "0123456789abcdef" for c in uid):raise HTTPException(404,"Unknown run")
    root=ROOT/".validation"/"research-sessions"/uid
    if not (root/"comparison.json").is_file():raise HTTPException(409,"Run is not complete")
    path=root/policy/filename
    if not path.is_file():raise HTTPException(404,"Artifact unavailable")
    return FileResponse(path,filename=f"{uid}-{policy}-{filename}")


@router.get("/sessions/{uid}/evidence/{filename}")
def evidence(uid:str,filename:Literal["source.zip","config.json","comparison.json","analytical-reference.json"]):
    if len(uid)!=32 or any(c not in "0123456789abcdef" for c in uid):raise HTTPException(404,"Unknown run")
    root=ROOT/".validation"/"research-sessions"/uid
    if not (root/"comparison.json").is_file():raise HTTPException(409,"Run is not complete")
    return FileResponse(root/filename,filename=f"{uid}-{filename}")


@router.delete("/sessions/{uid}",status_code=204)
def delete(uid:str):
    session=lookup(uid)
    with session.lock:session.close()
    with STORE_LOCK:SESSIONS.pop(uid,None)
