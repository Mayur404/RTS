"""Real learning integration and adversarial contract fixtures, never paper data."""
from collections import Counter
from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import pytest
import torch

from rts_predictive.domain.research import default_research_config
from rts_predictive.domain.learning import RECENT_LEARNING_ROUND_LIMIT
from rts_predictive.dashboard.learning_projection import LearningProjection
from rts_predictive.federated.model import load_federated_model
from rts_predictive.gnn.calibration import TemperatureCalibrator
from rts_predictive.predictors import research_adapter
from rts_predictive.predictors.research_adapter import ResearchModels
from rts_predictive.simulator.research_engine import ResearchEngine
from scripts.verify_runtime_end_to_end import replay_models
from test_research_engine import finish, remote_config
from test_research_model_integration import research_bundle_directory


def test_missing_research_weights_cannot_silently_select_legacy_graph_model(tmp_path,monkeypatch):
    research_bundle_directory(tmp_path,monkeypatch)
    (tmp_path/'research_gnn.pt').unlink()
    with pytest.raises(FileNotFoundError,match='research GNN weights'):ResearchModels()


@pytest.mark.parametrize('field,value',[('temperature',True),('temperature',0),('temperature',float('nan')),
    ('temperature',float('inf')),('multiplier',True),('multiplier',-1),('multiplier',float('nan')),
    ('method','unsupported')])
def test_federated_bundle_rejects_invalid_calibration(tmp_path,monkeypatch,field,value):
    research_bundle_directory(tmp_path,monkeypatch)
    path=tmp_path/'federated_remote_estimator.bundle.json';bundle=json.loads(path.read_text())
    if field=='multiplier':bundle['latency_q95_multiplier']=value
    else:bundle['reliability_calibration'][field]=value
    path.write_text(json.dumps(bundle))
    with pytest.raises(ValueError,match='calibration or latency'):load_federated_model(str(tmp_path/'federated_remote_estimator.pt'))


@pytest.mark.parametrize('bundle_name',['research_gnn','federated_remote_estimator'])
def test_bundle_parameter_dtype_must_match_architecture(tmp_path,monkeypatch,bundle_name):
    research_bundle_directory(tmp_path,monkeypatch)
    weights=tmp_path/(bundle_name+'.pt');state=torch.load(weights,weights_only=True)
    key=next(iter(state));state[key]=state[key].double();torch.save(state,weights)
    path=weights.with_suffix('.bundle.json');bundle=json.loads(path.read_text())
    bundle['weights_sha256']=hashlib.sha256(weights.read_bytes()).hexdigest();path.write_text(json.dumps(bundle))
    with pytest.raises(ValueError,match='parameter tensors'):ResearchModels()


@pytest.mark.parametrize('fault',['probability_negative','probability_above_one','risk_shape','time_negative','cause_shape','nan'])
def test_gnn_invalid_head_outputs_fail_visibly(monkeypatch,fault):
    models=ResearchModels();engine=ResearchEngine(remote_config(),models=models,enable_fl=False)
    risk=torch.tensor([[.5]]);ttv=torch.tensor([[.1]]);cause=torch.zeros(1,4)
    if fault=='probability_negative':risk.fill_(-.1)
    elif fault=='probability_above_one':risk.fill_(1.1)
    elif fault=='risk_shape':risk=torch.ones(2,1)
    elif fault=='time_negative':ttv.fill_(-.1)
    elif fault=='cause_shape':cause=torch.zeros(1,5)
    else:cause.fill_(float('nan'))
    monkeypatch.setattr(models.gnn,'forward',lambda *_:(risk,ttv,cause))
    projection=finish(engine)
    assert projection.metrics()['final']
    assert any(e['event_type']=='PREDICTOR_UNAVAILABLE' for e in engine.events)
    assert not any(e['event_type']=='PREDICTION' for e in engine.events)


def test_initial_reliability_uses_bundle_temperature_but_online_model_does_not(monkeypatch):
    models=ResearchModels();engine=ResearchEngine(remote_config(),models=models,enable_fl=False);engine.run_until(0)
    task=next(iter(engine.tasks.values()));device=engine.config.devices[-1];resource=engine.resource(device.device_id)
    monkeypatch.setattr(models.remote,'forward',lambda *_:(torch.tensor([[1.]]),torch.tensor([[.8]])))
    estimate,probability=models.estimate(task,device,resource)
    raw=float(torch.tensor(.8));assert probability==TemperatureCalibrator(models.remote.reliability_temperature).apply(raw)
    assert probability!=raw and estimate>0
    weights={k:v.clone() for k,v in models.remote.state_dict().items()};models.publish([{'samples':4,'weights':weights}])
    monkeypatch.setattr(models.remote,'forward',lambda *_:(torch.tensor([[1.]]),torch.tensor([[1.]])))
    assert models.estimate(task,device,resource)[1]==1.
    assert not models.remote.evaluated and models.remote.reliability_temperature==1.


@pytest.mark.parametrize('fault',['dtype','meta_device','boolean_loss','negative_loss','boolean_bytes','wrong_samples'])
def test_malformed_client_update_is_rejected_before_transport_and_healthy_peers_publish(fault):
    models=ResearchModels();train=models.train
    def corrupt(host,*args):
        update=train(host,*args)
        if host=='Device_1':
            key=next(iter(update['weights']))
            if fault=='dtype':update['weights'][key]=update['weights'][key].double()
            elif fault=='meta_device':update['weights'][key]=torch.empty_like(update['weights'][key],device='meta')
            elif fault=='boolean_loss':update['loss']=True
            elif fault=='negative_loss':update['loss']=-1.
            elif fault=='boolean_bytes':update['bytes']=True
            else:update['samples']+=1
        return update
    models.train=corrupt
    engine=ResearchEngine(default_research_config(family='nominal',release_end_us=350000),models=models)
    projection=finish(engine)
    assert projection.metrics()['model_publications']>0
    assert any(e['event_type']=='FL_TRAIN_FAILED' and e['device_id']=='Device_1' for e in engine.events)
    assert not any(e['event_type']=='TX_START' and e['device_id']=='Device_1' and e['payload']['phase']=='fl_upload' for e in engine.events)


def test_learning_view_and_estimates_reconcile_with_real_records_and_sgd():
    torch.set_num_threads(1)
    engine=ResearchEngine(default_research_config(family='bursty',release_end_us=650000))
    projection=finish(engine);learning=projection.snapshot()['learning'];raw=engine.events
    replay=replay_models(engine)
    assert replay['remote_estimates']>0 and replay['federated_publications']>0
    assert learning['gnn']['attempts']==projection.metrics()['gnn_inferences']
    assert learning['round_counts']['published']==projection.metrics()['model_publications']
    observations=Counter(e['device_id'] for e in raw if e['event_type']=='PRIVATE_OBSERVATION')
    assert {c['device']:c['observations'] for c in learning['clients']}==dict(observations)
    bytes_=Counter()
    for e in raw:
        if e['event_type']=='TX_START' and e['payload']['phase'].startswith('fl_'):bytes_[e['payload']['phase']]+=e['payload']['bytes']
    assert learning['charged_transfer_bytes']==dict(bytes_)
    publication=next(e for e in reversed(raw) if e['event_type']=='MODEL_PUBLISH')
    assert learning['latest_publication']['weights_sha256']==publication['payload']['weights_sha256']
    assert learning['latest_publication']['at_us']==publication['timestamp_us']
    by_sequence={e['sequence']:e for e in raw}
    for round_ in learning['rounds']:
        for record in round_['events']:
            e=by_sequence[record['sequence']]
            assert record['at_us']==e['timestamp_us'] and record['event_type']==e['event_type']
    learning['rounds'][0]['clients'].clear()
    assert projection.snapshot()['learning']['rounds'][0]['clients']
    # Corruption of an estimator record is caught independently of the runtime adapter.
    original=deepcopy(engine.events)
    candidate=next(c for e in engine.events if e['event_type']=='DECISION' for c in e['payload']['candidates'] if c.get('estimator_evidence'))
    candidate['estimator_evidence']['weights_sha256']='0'*64
    with pytest.raises(AssertionError):replay_models(engine)
    engine.events=original


def test_learning_history_is_bounded_without_losing_publication_totals():
    reducer=LearningProjection();sequence=0
    for index in range(1,RECENT_LEARNING_ROUND_LIMIT+6):
        for kind,payload in [('FL_ROUND_START',{'round':index,'participants':['A','B'],'coordinator':'A'}),
                             ('MODEL_PUBLISH',{'round':index,'version':index,'weights_sha256':str(index),'samples':8,'participants':2})]:
            sequence+=1;reducer.consume({'sequence':sequence,'timestamp_us':sequence,'event_type':kind,'device_id':None,'payload':payload})
    snapshot=reducer.snapshot()
    assert len(snapshot['rounds'])==RECENT_LEARNING_ROUND_LIMIT
    assert snapshot['round_counts']['published']==RECENT_LEARNING_ROUND_LIMIT+5
    assert snapshot['latest_publication']['version']==RECENT_LEARNING_ROUND_LIMIT+5


@pytest.mark.parametrize('flag',['enable_watchdog','enable_fl','enable_offload','enable_fallback'])
@pytest.mark.parametrize('value',['false',1,None])
def test_ablation_flags_cannot_silently_coerce_nonbooleans(flag,value):
    with pytest.raises(ValueError,match='flags must be booleans'):
        ResearchEngine(default_research_config(),**{flag:value})


def test_failed_publication_restores_calibration_metadata_and_parameter_identity():
    models=ResearchModels();initial_digest=models.parameter_sha256
    initial_temperature=models.remote.reliability_temperature
    def fail(_):
        models.remote.reliability_temperature=999.
        models.remote.evaluated=False;models.parameter_sha256='corrupted';models.version+=1
        raise RuntimeError('Controlled publication fault')
    models.publish=fail
    engine=ResearchEngine(default_research_config(family='nominal',release_end_us=350000),models=models)
    projection=finish(engine)
    assert projection.metrics()['model_publications']==0 and models.version==0
    assert models.remote.reliability_temperature==initial_temperature and models.remote.evaluated
    assert models.parameter_sha256==initial_digest
    assert projection.snapshot()['learning']['latest_publication'] is None


def test_single_client_round_is_skipped_without_fabricating_publication():
    config=default_research_config(family='nominal',release_end_us=650000)
    engine=ResearchEngine(replace(config,devices=config.devices[:1]))
    projection=finish(engine);learning=projection.snapshot()['learning']
    assert learning['latest_publication'] is None and engine.models.version==0
    assert learning['round_counts']['skipped']>0
    assert all(r['phase']=='SKIPPED' and r['reason']=='insufficient_private_samples' for r in learning['rounds'])
    assert not any(e['event_type']=='FL_TRAIN_START' for e in engine.events)


def test_declared_estimate_override_does_not_reuse_stale_evidence(monkeypatch):
    models=ResearchModels();engine=ResearchEngine(remote_config(),models=models,enable_fl=False);engine.run_until(0)
    task=next(iter(engine.tasks.values()));assert engine._candidates(task)[0].get('estimator_evidence')
    monkeypatch.setattr(models,'estimate',lambda *_:(1000,.99))
    candidate=engine._candidates(task)[0]
    assert candidate['predicted_execution_reliability']==.99 and 'estimator_evidence' not in candidate
