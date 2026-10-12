"""Actual PyTorch inference and decentralized model updates for research runs."""
import copy
import hashlib
import time
import json
import math
from pathlib import Path
import torch
from rts_predictive.gnn.model import PredictiveRuntimeGNN
from rts_predictive.gnn.calibration import TemperatureCalibrator
from rts_predictive.domain.learning import REMOTE_ESTIMATE_SCHEMA_VERSION
from rts_predictive.federated.model import load_federated_model

MODEL_DIRECTORY = Path(__file__).resolve().parents[2]/"models"


class ResearchModels:
    def __init__(self):
        self.validation_scope="transfer_unvalidated"
        path=MODEL_DIRECTORY/"research_gnn.pt"
        if path.is_file():
            bundle=json.loads(path.with_suffix(".bundle.json").read_text(encoding="utf-8"))
            if (not isinstance(bundle,dict) or bundle.get("bundle_version")!="research-gnn/1.0" or
                    bundle.get("feature_schema")!="research-task-resource/9-v3" or
                    hashlib.sha256(path.read_bytes()).hexdigest()!=bundle.get("weights_sha256")):
                raise ValueError("research GNN bundle integrity/schema mismatch")
            calibration=bundle.get("calibration")
            if not isinstance(calibration,dict):raise ValueError("invalid research GNN calibration or threshold")
            temperature=calibration.get("temperature")
            threshold=bundle.get("decision_threshold")
            if (calibration.get("method")!="temperature_scaling" or
                isinstance(temperature,bool) or not isinstance(temperature,(int,float)) or
                not math.isfinite(temperature) or temperature<=0 or
                isinstance(threshold,bool) or not isinstance(threshold,(int,float)) or
                not math.isfinite(threshold) or not 0<=threshold<=1):
                raise ValueError("invalid research GNN calibration or threshold")
            self.gnn = PredictiveRuntimeGNN()
            state=torch.load(path,map_location="cpu",weights_only=True)
            expected=self.gnn.state_dict()
            if (set(state)!=set(expected) or any(not isinstance(v,torch.Tensor) or
                    v.shape!=expected[k].shape or v.dtype!=expected[k].dtype or
                    not bool(torch.isfinite(v).all()) for k,v in state.items())):
                raise ValueError("research GNN parameter tensors must match the architecture and be finite")
            self.gnn.load_state_dict(state)
            self.gnn.calibration_temperature=temperature
            self.gnn.decision_threshold=threshold
            self.gnn.bundle_version=bundle["bundle_version"]
            self.gnn.calibrated=True
            self.gnn.eval()
            self.validation_scope="simulated_heldout_firm_task_failure"
        else:
            raise FileNotFoundError("research GNN weights and bundle are required; legacy graph models are incompatible")
        self.remote = load_federated_model(str(MODEL_DIRECTORY/"federated_remote_estimator.pt"))
        if any(not bool(torch.isfinite(v).all()) for v in self.remote.state_dict().values()):
            raise ValueError("federated estimator weights must be finite")
        self.version = 0
        self.parameter_sha256 = self.parameter_digest(self.remote.state_dict())
        self.last_estimate_evidence = None
        self.private = {}
        self.host_observations = []

    @staticmethod
    def parameter_digest(weights):
        return hashlib.sha256(b"".join(v.detach().cpu().numpy().tobytes()
                                      for _, v in sorted(weights.items()))).hexdigest()

    @staticmethod
    def validate_update(update, expected, expected_samples=None):
        if (not isinstance(update, dict) or type(update.get("samples")) is not int or
                update["samples"] <= 0 or
                (expected_samples is not None and update["samples"] != expected_samples)):
            raise ValueError("federated sample counts must match positive observed counts")
        weights = update.get("weights")
        if (not isinstance(weights, dict) or set(weights) != set(expected) or any(
                not isinstance(v, torch.Tensor) or v.shape != expected[k].shape or
                v.dtype != expected[k].dtype or v.device != expected[k].device or
                not bool(torch.isfinite(v).all()) for k, v in weights.items())):
            raise ValueError("invalid federated parameter tensors")
        if expected_samples is not None:
            loss = update.get("loss")
            if (isinstance(loss, bool) or not isinstance(loss, (int, float)) or
                    not math.isfinite(loss) or loss < 0 or type(update.get("bytes")) is not int or
                    update["bytes"] != sum(v.numel()*v.element_size() for v in weights.values())):
                raise ValueError("invalid federated training loss or payload byte count")

    @staticmethod
    def graph(task, tasks, resource, now):
        # Always retain the queried task, even if a node has a long queue.
        active = sorted(tasks, key=lambda t: (t.uid != task.uid, t.deadline, t.uid))[:24]
        features = [[1,0,0,resource["cpu_ppm"]/1e6,min(1,len(active)/10),resource["thermal_ppm"]/1e6,0,0,0],
                    [0,1,0,resource["gpu_ppm"]/1e6,min(1,sum(t.gpu for t in active)/5),resource["thermal_ppm"]/1e6,0,0,0],
                    [0,0,1,resource["memory_mb"]/max(1,resource["memory_capacity_mb"]),resource["memory_mb"]/2048,0,0,0,0],
                    [0,0,0,min(1,resource["bandwidth_mbps"]/100),resource["link_extra_us"]/20000,resource["loss_ppm"]/1e6,0,0,0]]
        mapping = {t.uid: 4+i for i,t in enumerate(active)}
        edges = []
        for t in active:
            remain = t.remaining
            features.append([int(t.critical),int(t.spec.offloadable),int(t.gpu),
                             t.spec.wcet_distribution.wcet_us/50000,remain/50000,
                             max(-2,min(2,(t.deadline-now-remain)/50000)),
                             t.spec.priority/10,int(t.degraded),int(t.uid==task.uid)])
            idx = mapping[t.uid]
            for r in [0,2] + ([1] if t.gpu else []):
                edges.extend([(idx,r),(r,idx)])
            for parent in t.parents:
                if parent in mapping:
                    edges.append((mapping[parent],idx))
        for i,t in enumerate(active):
            for u in active[i+1:]:
                if t.gpu and u.gpu:
                    edges.extend([(mapping[t.uid],mapping[u.uid]),(mapping[u.uid],mapping[t.uid])])
        edges.extend((i,i) for i in range(len(features)))
        x = torch.tensor(features,dtype=torch.float32)
        e = torch.tensor(edges,dtype=torch.long).T.contiguous()
        digest = hashlib.sha256(x.numpy().tobytes()+e.numpy().tobytes()).hexdigest()
        return x,e,digest

    def predict(self, task, tasks, resource, now):
        started = time.perf_counter_ns()
        x,e,digest = self.graph(task,tasks,resource,now)
        with torch.no_grad():
            risk,ttv,cause = self.gnn(x,e)
            if (risk.shape != (1,1) or ttv.shape != (1,1) or cause.shape != (1,4) or
                    not all(bool(torch.isfinite(value).all()) for value in (risk,ttv,cause)) or
                    not 0 <= float(risk[0,0]) <= 1 or float(ttv[0,0]) < 0):
                raise ValueError("GNN returned invalid output dimensions, probability or time")
            probability = self.gnn._calibrate_probability(float(risk[0,0]))
        latency = max(1,(time.perf_counter_ns()-started)//1000)
        self.host_observations.append({"kind":"gnn", "task":task.uid,"at_us":now,"latency_us":latency})
        active = sorted(tasks, key=lambda t: (t.uid != task.uid, t.deadline, t.uid))[:24]
        identities = ['CPU','GPU','MEMORY','LINK']+[t.uid for t in active]
        graph = {"feature_schema":"research-task-resource/9-v3", "node_ids":identities,
                 "node_kinds":['resource']*4+['task']*len(active),
                 "query_index":identities.index(task.uid), "features":x.tolist(),
                 "edge_index":e.tolist()}
        return {"miss_probability":probability,"ttv_us":max(0,int(float(ttv[0,0])*1_000_000)),
                "cause":self.gnn.CAUSE_NAMES[int(torch.argmax(cause[0]))],
                "graph_sha256":digest,"vertices":len(x),"edges":e.shape[1],"graph":graph,
                "host_latency_us":latency,
                "model_version":self.gnn.bundle_version,"validation_scope":self.validation_scope}

    @staticmethod
    def features(task, device, resource):
        return torch.tensor([[task.spec.wcet_distribution.wcet_us/50000, int(task.gpu),
                              device.cpu_speed_ppm/1e6,device.gpu_speed_ppm/1e6,
                              resource["cpu_ppm"]/1e6,resource["gpu_ppm"]/1e6]],dtype=torch.float32)

    def estimate(self, task, device, resource):
        evidence = self.estimate_evidence(task, device, resource)
        self.last_estimate_evidence = (task.uid, device.device_id, evidence)
        return evidence["execution_bound_us"], evidence["execution_reliability"]

    def estimate_evidence(self, task, device, resource):
        features = self.features(task,device,resource)
        with torch.no_grad():
            execution, reliability = self.remote(features)
        # Online publications do not inherit old quantile coverage guarantees.
        q = self.remote.q95_multiplier
        if (execution.shape!=(1,1) or reliability.shape!=(1,1) or
            not bool(torch.isfinite(execution).all()) or not bool(torch.isfinite(reliability).all()) or
            float(execution[0,0])<=0 or not 0<=float(reliability[0,0])<=1 or
            isinstance(q,bool) or not isinstance(q,(int,float)) or not math.isfinite(q) or q<=0):
            raise ValueError("remote estimator returned invalid execution, reliability or multiplier")
        latency=float(execution[0,0])*1000*q
        if not math.isfinite(latency):
            raise ValueError("remote estimator latency overflow")
        raw_probability = float(reliability[0,0])
        temperature = self.remote.reliability_temperature if self.version == 0 else 1.0
        probability = TemperatureCalibrator(temperature).apply(raw_probability) if self.version == 0 else raw_probability
        return {"schema_version": REMOTE_ESTIMATE_SCHEMA_VERSION,
                "features":features[0].tolist(),"feature_schema":"remote-execution/6-v1",
                "execution_mean_ms":float(execution[0,0]),"execution_bound_us":max(1,int(latency)),
                "latency_multiplier":q,"raw_execution_reliability":raw_probability,
                "execution_reliability":probability,"reliability_temperature":temperature,
                "model_version":self.version,"weights_sha256":self.parameter_sha256,
                "evidence":"PREDICTED",
                "scope":"pretrained calibration; current-workload coverage unvalidated" if self.version == 0 else
                        "online publication uncalibrated; latency multiplier is an unvalidated heuristic"}

    def observe(self, task, device, resource, elapsed_us, success,latency_observed=True):
        records = self.private.setdefault(device.device_id,[])
        records.append((self.features(task,device,resource),elapsed_us/1000,float(success),float(latency_observed)))
        del records[:-32]

    def train(self, device_id, now, records=None):
        records = list(self.private.get(device_id,[]) if records is None else records)
        if len(records)<4:
            return None
        model = copy.deepcopy(self.remote)
        model.train()
        x = torch.cat([r[0] for r in records])
        y = torch.tensor([[r[1]] for r in records])
        rel = torch.tensor([[r[2]] for r in records])
        observed = torch.tensor([[r[3]] for r in records])
        optimizer = torch.optim.SGD(model.parameters(),lr=.001)
        started = time.perf_counter_ns()
        optimizer.zero_grad()
        pred,p = model(x)
        latency_loss=(torch.nn.functional.huber_loss(pred,y,reduction='none')*observed).sum()/observed.sum().clamp(min=1)
        loss = .1*latency_loss+torch.nn.functional.binary_cross_entropy(p,rel)
        loss.backward(); optimizer.step()
        self.host_observations.append({"kind":"fl_train","device":device_id,"at_us":now,
                                       "latency_us":max(1,(time.perf_counter_ns()-started)//1000)})
        return {"weights":{k:v.detach().clone() for k,v in model.state_dict().items()},
                "samples":len(records),"loss":float(loss.detach()),
                "bytes":sum(v.numel()*v.element_size() for v in model.state_dict().values())}

    def publish(self, updates):
        updates=list(updates)
        expected=self.remote.state_dict()
        for update in updates:
            self.validate_update(update,expected)
        total = sum(u["samples"] for u in updates)
        if not total:
            raise ValueError("cannot publish a model without observed samples")
        weights = {key:sum((u["weights"][key]*(u["samples"]/total) for u in updates),
                           torch.zeros_like(updates[0]["weights"][key]))
                   for key in updates[0]["weights"]}
        if any(not bool(torch.isfinite(v).all()) for v in weights.values()):
            raise ValueError("federated aggregate must be finite")
        staged=copy.deepcopy(self.remote)
        staged.load_state_dict(weights); staged.eval()
        staged.evaluated=False
        staged.reliability_temperature=1.0
        digest = self.parameter_digest(weights)
        self.remote=staged
        self.parameter_sha256=digest
        self.version += 1
        return self.version,digest
