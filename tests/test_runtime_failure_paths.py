"""Regression tests discovered by the start-to-end runtime review."""
from dataclasses import replace

import pytest

from test_research_engine import config,task,finish,FixtureModels,remote_config
from rts_predictive.domain.specs import WcetDistributionSpec
from rts_predictive.simulator.research_engine import ResearchEngine
from rts_predictive.simulator.research_audit import audit_research_events


def test_full_execution_commits_the_configured_task_utility():
    c=config((task(output_utility=.4),))
    e=ResearchEngine(c,'edf');p=finish(e)
    assert p.metrics()['mean_utility']==.4
    assert all(ev['payload']['utility']==.4 for ev in e.events if ev['event_type']=='TASK_COMMIT')


def test_constant_demand_uses_nominal_instead_of_sampling_its_bounds():
    spec=replace(task(),wcet_distribution=WcetDistributionSpec('constant',50,100,200))
    demands=[]
    for seed in (10,11,12):
        engine=ResearchEngine(replace(config((spec,)),seed=seed),'edf');finish(engine)
        demands.append(next(iter(engine.tasks.values())).demand)
    assert demands==[100,100,100]


@pytest.mark.parametrize('failure',['exception','nan','negative','boolean','missing'])
def test_unavailable_prediction_is_recorded_and_uses_local_recovery(failure):
    class BrokenModels(FixtureModels):
        def predict(self,*args):
            if failure=='exception':raise RuntimeError('inference unavailable for controlled test')
            value=super().predict(*args)
            if failure=='missing':value.pop('miss_probability')
            else:value['miss_probability']={'nan':float('nan'),'negative':-.1,'boolean':True}[failure]
            return value
    engine=ResearchEngine(remote_config(),models=BrokenModels(),enable_fl=False)
    projection=finish(engine)
    assert projection.metrics()['final'] and projection.metrics()['pending_jobs']==0
    assert not any(e['event_type']=='OFFLOAD_DISPATCH' for e in engine.events)
    failures=[e for e in engine.events if e['event_type']=='PREDICTOR_UNAVAILABLE']
    assert failures and all(e['payload']['fallback']=='reactive_local_degradation_or_full_local' for e in failures)
    assert not any(e['event_type']=='PREDICTION' for e in engine.events)
    assert projection.metrics()['gnn_inferences']==len(failures)==len(projection.host_latencies)
    assert all(t['predictor_unavailable']['reason'] for t in projection.snapshot()['tasks'] if 'predictor_unavailable' in t)
    assert audit_research_events(engine.events)['runtime_evidence']['status']=='PASS'


def test_failure_at_checkpoint_clears_prior_prediction_in_task_inspection():
    class FailingCheckpointModels(FixtureModels):
        def predict(self,*args):
            t=args[0]
            if t.delivered_work:raise RuntimeError('checkpoint inference failed')
            value=super().predict(*args);value['miss_probability']=0.
            return value
    c=replace(remote_config(),devices=remote_config().devices[:1])
    engine=ResearchEngine(c,models=FailingCheckpointModels(),enable_fl=False)
    p=finish(engine)
    assert any(e['event_type']=='PREDICTION' for e in engine.events)
    assert any(e['event_type']=='PREDICTOR_UNAVAILABLE' for e in engine.events)
    snapshot=p.snapshot()
    failed=next(t for t in snapshot['tasks'] if t.get('predictor_unavailable'))
    assert 'prediction' not in failed['diagnostics']
    assert failed['diagnostics']['decision']['predictor_unavailable']


@pytest.mark.parametrize('failure',['exception','invalid'])
def test_unavailable_remote_estimate_is_rejected_without_stopping_run(failure):
    class FailedEstimator(FixtureModels):
        def estimate(self,*args):
            if failure=='exception':raise RuntimeError('controlled estimator failure')
            return -1,float('nan')
    engine=ResearchEngine(remote_config(),models=FailedEstimator(),enable_fl=False)
    projection=finish(engine)
    assert projection.metrics()['final']
    assert not any(e['event_type']=='OFFLOAD_DISPATCH' for e in engine.events)
    candidates=[c for e in engine.events if e['event_type']=='DECISION' for c in e['payload']['candidates']]
    assert candidates and all(not c['accepted'] and c['reason']=='estimator_unavailable' for c in candidates)


@pytest.mark.parametrize('failure',['exception','nonfinite'])
def test_failing_federated_client_is_excluded_and_healthy_clients_can_publish(failure):
    from rts_predictive.domain.research import default_research_config
    from rts_predictive.predictors.research_adapter import ResearchModels
    import torch
    models=ResearchModels();train=models.train
    def fail_one(host,*args):
        if host=='Device_1':
            if failure=='exception':raise RuntimeError('controlled private training failure')
            update=train(host,*args);next(iter(update['weights'].values())).fill_(float('nan'));return update
        return train(host,*args)
    models.train=fail_one
    engine=ResearchEngine(default_research_config(family='nominal',release_end_us=350000),models=models)
    projection=finish(engine)
    assert projection.metrics()['final'] and projection.metrics()['model_publications']>0
    assert any(e['event_type']=='FL_TRAIN_FAILED' and e['device_id']=='Device_1' for e in engine.events)
    assert all(bool(torch.isfinite(v).all()) for v in models.remote.state_dict().values())
    assert audit_research_events(engine.events)['runtime_evidence']['status']=='PASS'


def test_federated_publication_failure_restores_model_and_version():
    from rts_predictive.domain.research import default_research_config
    from rts_predictive.predictors.research_adapter import ResearchModels
    import torch
    models=ResearchModels();original={k:v.detach().clone() for k,v in models.remote.state_dict().items()}
    def fail_publication(updates):
        with torch.no_grad():next(iter(models.remote.parameters())).fill_(float('nan'))
        models.version+=1
        raise RuntimeError('controlled publication failure')
    models.publish=fail_publication
    engine=ResearchEngine(default_research_config(family='nominal',release_end_us=350000),models=models)
    p=finish(engine)
    assert p.metrics()['model_publications']==0 and models.version==0
    assert any(e['event_type']=='FL_ROUND_SKIPPED' and e['payload']['reason']=='aggregation_failure' for e in engine.events)
    assert all(torch.equal(v,original[k]) for k,v in models.remote.state_dict().items())
