"""Auditable host timing observations, deliberately not a hard-WCET proof."""
import hashlib
import json
from rts_predictive.domain.runtime_evidence import HARDWARE_INFERENCE_PROFILE_SCHEMA_VERSION


def summarize_timings(records, *, model_sha256, environment, budget_us):
    records=list(records)
    values=sorted(r['latency_us'] for r in records)
    if any(type(v) is not int or v<1 for v in values):raise ValueError('invalid measured latency')
    raw=json.dumps(records,sort_keys=True,separators=(',',':')).encode()
    return {'schema_version':HARDWARE_INFERENCE_PROFILE_SCHEMA_VERSION,'evidence':'MEASURED_ON_HOST',
            'model_sha256':model_sha256,'environment':environment,'budget_us':budget_us,
            'sample_count':len(values),'observed_max_us':max(values) if values else None,
            'p99_us':values[max(0,(99*len(values)+99)//100-1)] if values else None,
            'budget_overruns':sum(v>budget_us for v in values),'raw_sha256':hashlib.sha256(raw).hexdigest(),
            'hard_wcet_proven':False,
            'assumptions':['finite host timing samples do not bound unseen interference or prove WCET',
                           'budget enforcement detects after return; no PyTorch-call preemption'],
            'records':records}
