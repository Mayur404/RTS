"""Actual model wiring and rejection of unusable published parameters."""
import hashlib
import json
import shutil

import pytest
import torch

from rts_predictive.predictors import research_adapter
from rts_predictive.predictors.research_adapter import ResearchModels
from rts_predictive.domain.research import default_research_config
from rts_predictive.simulator.research_engine import ResearchEngine
from scripts.verify_runtime_end_to_end import replay_models
from test_research_engine import finish, remote_config


def test_research_models_load_from_an_unrelated_launch_directory(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    models=ResearchModels()
    assert models.validation_scope=='simulated_heldout_firm_task_failure'
    assert not models.gnn.training and not models.remote.training


def research_bundle_directory(tmp_path,monkeypatch):
    for name in ('research_gnn.pt','research_gnn.bundle.json',
                 'federated_remote_estimator.pt','federated_remote_estimator.bundle.json'):
        shutil.copyfile(research_adapter.MODEL_DIRECTORY/name,tmp_path/name)
    monkeypatch.setattr(research_adapter,'MODEL_DIRECTORY',tmp_path)
    return tmp_path/'research_gnn.bundle.json'


def test_research_bundle_does_not_require_legacy_initialization(tmp_path,monkeypatch):
    research_bundle_directory(tmp_path,monkeypatch)
    models=ResearchModels()
    assert models.gnn.bundle_version=='research-gnn/1.0'
    assert models.gnn.calibrated


@pytest.mark.parametrize('field,value',[('temperature',0),('temperature',float('nan')),
                                       ('temperature',True),('threshold',1.1),('threshold',True)])
def test_invalid_research_calibration_is_rejected(tmp_path,monkeypatch,field,value):
    path=research_bundle_directory(tmp_path,monkeypatch)
    bundle=json.loads(path.read_bytes())
    if field=='temperature':bundle['calibration']['temperature']=value
    else:bundle['decision_threshold']=value
    path.write_text(json.dumps(bundle),encoding='utf-8')
    with pytest.raises(ValueError,match='calibration or threshold'):ResearchModels()


@pytest.mark.parametrize('fault',['samples','boolean_samples','negative_samples','keys','shape','dtype','nan'])
def test_bad_federated_update_preserves_active_weights_and_version(fault):
    models=ResearchModels()
    original={k:v.detach().clone() for k,v in models.remote.state_dict().items()}
    update={'samples':4,'weights':{k:v.clone() for k,v in original.items()}}
    key=next(iter(original))
    if fault=='samples':update['samples']=0
    elif fault=='boolean_samples':update['samples']=True
    elif fault=='negative_samples':update['samples']=-4
    elif fault=='keys':update['weights'].pop(key)
    elif fault=='shape':update['weights'][key]=torch.zeros(1)
    elif fault=='dtype':update['weights'][key]=update['weights'][key].double()
    else:update['weights'][key].fill_(float('nan'))
    active=models.remote
    with pytest.raises(ValueError):models.publish([update])
    assert models.remote is active and models.version==0
    assert all(torch.equal(v,original[k]) for k,v in models.remote.state_dict().items())


@pytest.mark.parametrize('execution,reliability',[(float('nan'),.8),(-1.,.8),(1.,float('nan')),(1.,1.2)])
def test_invalid_neural_remote_outputs_reject_candidates(monkeypatch,execution,reliability):
    models=ResearchModels()
    monkeypatch.setattr(models.remote,'forward',lambda x:(torch.tensor([[execution]]),torch.tensor([[reliability]])))
    engine=ResearchEngine(remote_config(),models=models,enable_fl=False)
    engine.run_until(0)
    candidates=engine._candidates(next(iter(engine.tasks.values())))
    assert candidates and all(c['reason']=='estimator_unavailable' and not c['accepted'] for c in candidates)


def test_published_estimator_is_used_by_runtime_candidates():
    models=ResearchModels()
    engine=ResearchEngine(remote_config(),models=models,enable_fl=False)
    engine.run_until(0)
    task=next(iter(engine.tasks.values()))
    before=engine._candidates(task)[0]
    weights={k:torch.zeros_like(v) for k,v in models.remote.state_dict().items()}
    weights['time_head.2.bias'].fill_(100.)
    weights['rel_head.2.bias'].fill_(10.)
    version,digest=models.publish([{'samples':4,'weights':weights}])
    after=engine._candidates(task)[0]
    assert before['estimator_version']==0 and after['estimator_version']==version==1
    assert after['bound_us']>before['bound_us'] and not after['accepted']
    assert digest==hashlib.sha256(b''.join(v.numpy().tobytes() for _,v in sorted(models.remote.state_dict().items()))).hexdigest()


def test_actual_gnn_federated_training_and_publication_replay():
    torch.set_num_threads(1)
    engine=ResearchEngine(default_research_config(family='bursty',release_end_us=650000))
    projection=finish(engine)
    replay=replay_models(engine)
    assert replay['neural_forwards']>0 and replay['federated_publications']>0
    assert projection.metrics()['overhead_work_us']['decision']>0
    assert projection.metrics()['overhead_work_us']['fl_train']>0
    assert any(e['event_type']=='TX_START' and e['payload']['phase']=='fl_upload' for e in engine.events)
    publications=[e for e in engine.events if e['event_type']=='MODEL_PUBLISH']
    assert any(c['estimator_version']>0 for e in engine.events if e['event_type']=='DECISION'
               for c in e['payload']['candidates'])
    assert engine.models.version==publications[-1]['payload']['version']
