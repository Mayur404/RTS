"""Executed synthetic prefix classifier; structural validity is not accuracy."""
import hashlib
import torch
from rts_predictive.domain.runtime_evidence import EXECUTED_OUTPUT_SCHEMA_VERSION
from rts_predictive.simulator.rng import derive_stream_seed

MODEL_ID = 'synthetic-prefix-classifier/1.0'
WEIGHTS = torch.tensor([[1.,-1.,.5,-.5],[-1.,1.,-.5,.5],[.25,.25,-.25,-.25]])
MODEL_SHA256 = hashlib.sha256(MODEL_ID.encode()+WEIGHTS.numpy().tobytes()).hexdigest()


def execute_output(seed, task_id, early=False, checkpoint_id=None):
    generator = torch.Generator().manual_seed(derive_stream_seed(seed,'partial-input/'+task_id) % (2**63-1))
    features = torch.rand(4,generator=generator)*2-1
    # Early head executes only the first feature stage. Full head adds stage two.
    with torch.no_grad():
        logits = WEIGHTS[:,:2]@features[:2]
        if not early: logits = logits+WEIGHTS[:,2:]@features[2:]
        probabilities = torch.softmax(logits,dim=0)
    record = {'output_schema_version':EXECUTED_OUTPUT_SCHEMA_VERSION,'workload':'SYNTHETIC_PREFIX_CLASSIFIER',
        'model_id':MODEL_ID,'model_sha256':MODEL_SHA256,
        'input_sha256':hashlib.sha256(features.numpy().tobytes()).hexdigest(),
        'head':'prefix' if early else 'full','stages_executed':1 if early else 2,
        'checkpoint_id':checkpoint_id,'probabilities':probabilities.tolist(),
        'class_id':int(probabilities.argmax()),
        'output_sha256':hashlib.sha256(probabilities.numpy().tobytes()).hexdigest(),
        'validity_scope':'finite normalized classification tensor; no semantic accuracy guarantee'}
    record['valid'] = validate_output(record)
    return record


def validate_output(record):
    try:
        p = torch.tensor(record['probabilities'],dtype=torch.float32)
        return bool(record['output_schema_version']==EXECUTED_OUTPUT_SCHEMA_VERSION and
                    record['model_id']==MODEL_ID and record['workload']=='SYNTHETIC_PREFIX_CLASSIFIER' and
                    record['model_sha256']==MODEL_SHA256 and p.shape==(3,) and
                    torch.isfinite(p).all() and (p>=0).all() and (p<=1).all() and
                    abs(float(p.sum())-1)<1e-6 and record['class_id']==int(p.argmax()) and
                    record['output_sha256']==hashlib.sha256(p.numpy().tobytes()).hexdigest() and
                    (record['head'],record['stages_executed']) in {('prefix',1),('full',2)} and
                    (record['head']!='prefix' or bool(record['checkpoint_id'])))
    except (KeyError,TypeError,ValueError,RuntimeError):
        return False
