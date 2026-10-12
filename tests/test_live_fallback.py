"""Falsification tests for live admission, real tensors, and host evidence."""
from dataclasses import replace
from copy import deepcopy
import pytest
from test_research_engine import config,task,finish,remote_config,FixtureModels
from rts_predictive.domain.research import ResearchFault,ResearchDevice,PPM
from rts_predictive.domain.specs import ExitPointSpec
from rts_predictive.simulator.research_engine import ResearchEngine
from rts_predictive.verification.live_fallback import analyze_fallback
from rts_predictive.predictors.partial_output import execute_output,validate_output
from rts_predictive.artifacts.inference_timing import summarize_timings


def setup(gpu=True,**kwargs):
    point=ExitPointSpec('head',(0,4000),20,100,.7)
    engine=ResearchEngine(config((task(work=4000,gpu=gpu,exit_points=(point,)),),**kwargs),
                          models=FixtureModels(),enable_fl=False)
    engine.run_until(0)
    return engine,next(iter(engine.tasks.values())),point


def test_future_fault_is_included_not_current_rate():
    e,t,p=setup(faults=(ResearchFault('Device_1',100,9000,gpu_ppm=PPM),))
    c=analyze_fallback(e,t,p)
    assert c['minimum_rate_ppm']==0 and c['status']=='NOT_SCHEDULABLE'
    assert e._exit(t) is None


def test_certificate_rejects_small_memory_and_wrong_scheduler():
    e,t,p=setup(devices=(ResearchDevice('Device_1','tiny','drone',PPM,PPM,100),))
    assert analyze_fallback(e,t,p)['status']=='NOT_SCHEDULABLE'
    e.policy='fifo'
    assert analyze_fallback(e,t,p)['status']=='UNSUPPORTED'


@pytest.mark.parametrize('gpu',[True,False])
def test_enforced_response_bound_and_matching_commit(gpu):
    e,t,p=setup(gpu=gpu)
    selected=e._exit(t)
    # Remove the ordinary attempt; this is a new admitted recovery attempt.
    e._cancel(e.attempts[t.current_attempt],'test_recovery')
    a=e._new_attempt(t,t.origin,True,selected)
    e._schedule()
    finish(e)
    check=next(x for x in e.events if x['event_type']=='FALLBACK_BOUND_CHECK')
    assert check['payload']['within_bound']
    assert check['payload']['certificate_sha256']==a.fallback_certificate['certificate_sha256']
    assert a.output_record['head']=='prefix' and a.output_record['valid']


def test_normal_gpu_blocking_and_existing_fallback_are_counted():
    point=ExitPointSpec('head',(0,4000),20,100,.7)
    e=ResearchEngine(config((task('A',4000,gpu=True),task('B',4000,gpu=True,exit_points=(point,)),task('Sink')),
                           edges=(('A','Sink'),('B','Sink'))),
                     models=FixtureModels(),enable_fl=False)
    e.run_until(0)
    b=next(t for t in e.tasks.values() if t.spec.task_id=='B')
    certificate=analyze_fallback(e,b,point)
    assert certificate['interference'][0]['work_us']==4000
    assert certificate['interference'][0]['kind']=='nonpreemptive_blocking'


def test_executed_prefix_and_full_are_deterministic_distinct_valid():
    early=execute_output(8,'device/task',True,'head')
    full=execute_output(8,'device/task')
    assert early==execute_output(8,'device/task',True,'head')
    assert early['input_sha256']==full['input_sha256']
    assert early['output_sha256']!=full['output_sha256']
    assert validate_output(early) and validate_output(full)
    for key,value in [('probabilities',[float('nan'),0,0]),('class_id',9),('output_sha256','bad'),('checkpoint_id',None)]:
        wrong=deepcopy(early);wrong[key]=value
        assert not validate_output(wrong)


def test_invalid_actual_output_cannot_commit(monkeypatch):
    import rts_predictive.predictors.partial_output as module
    monkeypatch.setattr(module,'execute_output',lambda *args:{'probabilities':[float('nan')]})
    e=ResearchEngine(config(),'edf');p=finish(e)
    assert p.metrics()['completed_jobs']==0
    assert any(x['event_type']=='OUTPUT_REJECTED' for x in e.events)
    assert not any(x['event_type']=='TASK_COMMIT' for x in e.events)


def test_host_summary_preserves_samples_and_never_proves_wcet():
    records=[{'latency_us':x,'sequence':i} for i,x in enumerate([5,9,3])]
    summary=summarize_timings(records,model_sha256='model',environment={'cpu':'host'},budget_us=6)
    assert summary['observed_max_us']==9 and summary['budget_overruns']==1
    assert summary['records']==records and not summary['hard_wcet_proven']
    with pytest.raises(ValueError):summarize_timings([{'latency_us':0}],model_sha256='m',environment={},budget_us=1)


@pytest.mark.parametrize('corruption',['certificate','output','missing_output','bound'])
def test_raw_audit_rejects_runtime_evidence_corruption(corruption):
    from rts_predictive.simulator.research_audit import audit_research_events,TraceAuditError
    c=remote_config(faults=(ResearchFault('Device_2',300,9000,gpu_ppm=990000),))
    e=ResearchEngine(c,models=FixtureModels(),enable_fl=False);finish(e)
    assert audit_research_events(e.events)['runtime_evidence']['bounded_completions']>0
    wrong=deepcopy(e.events)
    if corruption=='certificate':next(x for x in wrong if x['event_type']=='FALLBACK_ANALYSIS')['payload']['response_bound_us']+=1
    elif corruption=='output':next(x for x in wrong if x['event_type']=='OUTPUT_VALIDATION')['payload']['input_sha256']='0'*64
    elif corruption=='bound':next(x for x in wrong if x['event_type']=='FALLBACK_BOUND_CHECK')['payload']['within_bound']=False
    else:wrong=[x for x in wrong if x['event_type']!='OUTPUT_VALIDATION']
    with pytest.raises(TraceAuditError):audit_research_events(wrong)


def test_overrun_enforcement_discards_neural_recommendation():
    class SlowModels(FixtureModels):
        def predict(self,*args):
            prediction=super().predict(*args);prediction['host_latency_us']=100
            return prediction
    c=replace(remote_config(),host_inference_budget_us=1,enforce_host_inference_budget=True)
    e=ResearchEngine(c,models=SlowModels(),enable_fl=False);projection=finish(e)
    assert any(x['event_type']=='INFERENCE_BUDGET_OVERRUN' and x['payload']['recommendation_discarded'] for x in e.events)
    assert not any(x['event_type'] in {'PREDICTION','OFFLOAD_DISPATCH'} for x in e.events)
    assert projection.metrics()['gnn_inferences']==sum(x['event_type']=='HOST_INFERENCE' for x in e.events)
