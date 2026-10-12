"""Behavioral invariants for layered work, failed transfers and paired evidence."""
from collections import Counter
from dataclasses import replace
import hashlib
import json
import pytest
import torch
from rts_predictive.domain.research import (ResearchConfig,ResearchDevice,ResearchFault,PPM,default_research_config)
from rts_predictive.domain.specs import (TaskSpec,ResourceDemand,ResourceKind,WcetDistributionSpec,
                                       PipelineSpec,ReleaseModel,ExitPointSpec)
from rts_predictive.domain.lifecycle import AttemptState
from rts_predictive.simulator.research_engine import ResearchEngine
from rts_predictive.dashboard.research_projection import ResearchProjection,paired_comparison
from rts_predictive.artifacts.events import validate_canonical_event,iter_canonical_events


def task(name='A',work=100,deadline=10000,gpu=False,**kwargs):
    return TaskSpec(name,(ResourceDemand(ResourceKind.GPU if gpu else ResourceKind.CPU,1),),deadline,
                    WcetDistributionSpec('constant',work,work,work),period_us=20000,**kwargs)


def config(tasks=None,edges=(),deadline=10000,devices=None,**kwargs):
    tasks=tasks or (task(),)
    pipe=PipelineSpec('test',tasks,edges,ReleaseModel.PERIODIC,deadline,tasks[-1].task_id,period_us=20000)
    return ResearchConfig(devices=devices or (ResearchDevice('Device_1','Test','drone',PPM,PPM),),
                          workflows=(pipe,),release_end_us=1,drain_us=20000,dispatch_cost_us=0,
                          inference_cost_us=0,base_link_us=100,jitter_us=0,loss_ppm=0,margin_us=10,**kwargs)


def finish(engine,step=None):
    if step:
        for at in range(0,engine.config.end_us,step):engine.run_until(at)
    engine.run_until(engine.config.end_us)
    reducer=ResearchProjection()
    for e in engine.events:validate_canonical_event(e);reducer.consume(e)
    return reducer


def test_completion_at_deadline_is_valid_and_integer():
    e=ResearchEngine(config((task(work=100,deadline=100),),deadline=100),'edf')
    p=finish(e)
    assert p.metrics()['completed_jobs']==1 and p.metrics()['missed_jobs']==0
    assert next(v['timestamp_us'] for v in e.events if v['event_type']=='TASK_COMMIT')==100
    assert all(type(v['timestamp_us']) is int for v in e.events)


def test_layer_boundaries_and_service_conservation():
    e=ResearchEngine(config((task(work=400,gpu=True),)),'edf');finish(e,17)
    a=next(iter(e.attempts.values()))
    assert a.work_done==400 and a.remaining==0
    assert [v['payload']['layer'] for v in e.events if v['event_type']=='CHECKPOINT']==[1,2,3]
    assert sum(v['payload']['work_us'] for v in e.events if v['event_type']=='SERVICE')==400


def test_real_fork_join_never_releases_successor_early():
    c=config((task('Source'),task('Left',200,gpu=True),task('Right',300),task('Sink')),
             (('Source','Left'),('Source','Right'),('Left','Sink'),('Right','Sink')))
    e=ResearchEngine(c,'edf');p=finish(e)
    committed={v['task_id']:v['timestamp_us'] for v in e.events if v['event_type']=='TASK_COMMIT'}
    for v in e.events:
        if v['event_type']=='TASK_READY':
            for parent in e.tasks[v['task_id']].parents:assert committed[parent]<=v['timestamp_us']
    assert p.metrics()['completed_jobs']==1


def test_predecessor_miss_drops_descendants_and_counts_one_job():
    c=config((task('A',200,100),task('B')), (('A','B'),))
    e=ResearchEngine(c,'edf');p=finish(e)
    assert p.metrics()['missed_jobs']==1 and p.metrics()['pending_jobs']==0
    assert list(e.tasks.values())[1].status=='SKIPPED'
    assert sum(v['event_type']=='TASK_READY' for v in e.events)==1


def test_partitioned_advancement_preserves_outcomes_and_work():
    c=default_research_config(release_end_us=100000)
    a,b=ResearchEngine(c,'edf'),ResearchEngine(c,'edf')
    pa,pb=finish(a),finish(b,3333)
    assert pa.metrics()==pb.metrics()
    assert {k:(t.status,t.committed_attempt) for k,t in a.tasks.items()}=={k:(t.status,t.committed_attempt) for k,t in b.tasks.items()}
    assert {k:v.work_done for k,v in a.attempts.items()}=={k:v.work_done for k,v in b.attempts.items()}


def test_edf_is_reproducible_and_exogenous_demand_policy_independent():
    c=default_research_config(release_end_us=100000)
    a,b=ResearchEngine(c,'edf'),ResearchEngine(c,'edf');finish(a);finish(b)
    assert a.events==b.events
    assert all(0<=v.remaining<=v.total for v in a.attempts.values())
    with pytest.raises(ValueError):a.push(a.now-.5,'SAMPLE')


class FixtureModels:
    """Deliberately controlled unit-test decisions; never used for experiments."""
    class GNN:decision_threshold=.5
    gnn=GNN();version=0
    def predict(self,*args):return {'miss_probability':1.,'ttv_us':1,'cause':'test','graph_sha256':'test','vertices':1,'edges':1,'model_version':'test','validation_scope':'UNIT_FIXTURE'}
    def estimate(self,*args):return 1,.99
    def observe(self,*args,**kwargs):pass
    def features(self,*args):return torch.tensor([[1.]])


def remote_config(**kwargs):
    return config((task(work=4000,gpu=True,offloadable=True,request_payload_bytes=100,result_payload_bytes=100,
                        exit_points=(ExitPointSpec('exit',(0,4000),20,100,.7),)),),
                  devices=(ResearchDevice('Device_1','Origin','drone',PPM,PPM),ResearchDevice('Device_2','Peer','server',PPM,2*PPM)),
                  watchdog_period_us=500,**kwargs)


def test_watchdog_recovers_and_commits_at_most_once():
    c=remote_config(faults=(ResearchFault('Device_2',300,9000,gpu_ppm=990000),))
    e=ResearchEngine(c,models=FixtureModels(),enable_fl=False);p=finish(e)
    assert p.metrics()['watchdog_aborts']>=1
    commits=Counter(v['task_id'] for v in e.events if v['event_type']=='TASK_COMMIT')
    assert commits and max(commits.values())==1
    cancelled=[a for a in e.attempts.values() if a.lifecycle.state is AttemptState.CANCELLED]
    assert cancelled
    assert any(v['event_type']=='CANCEL_ACK' for v in e.events)
    assert p.metrics()['overhead_work_us']['watchdog']>0


def test_lost_cancel_waits_for_lease_and_charges_remote_work():
    c=remote_config(faults=(ResearchFault('Device_2',300,9000,gpu_ppm=990000,loss_ppm=PPM),))
    e=ResearchEngine(c,models=FixtureModels(),enable_fl=False);finish(e)
    assert any(v['event_type']=='CANCEL_UNDELIVERED' for v in e.events)
    leases=[v for v in e.events if v['event_type']=='ATTEMPT_LEASE_EXPIRED']
    assert leases and all(v['timestamp_us']==e.tasks[v['task_id']].deadline for v in leases)
    assert any(v['event_type']=='SERVICE' and v['device_id']=='Device_2' and v['timestamp_us']>1000 for v in e.events)


def test_result_in_flight_does_not_cancel_completed_attempt_at_lease():
    e=ResearchEngine(remote_config(),models=FixtureModels(),enable_fl=False,enable_watchdog=False)
    e.run_until(2500)
    a=next(a for a in e.attempts.values() if a.host=='Device_2')
    a.lifecycle.state=AttemptState.COMPLETED;a.phase='RESULT_TX'
    e._handle('LEASE',a.lifecycle.attempt_id)
    assert a.lifecycle.state is AttemptState.COMPLETED


def test_zero_baseline_and_regression_are_not_hidden():
    assert paired_comparison({'job_dmr_pct':0,'final':True},{'job_dmr_pct':5,'final':True})['relative_reduction_pct'] is None
    assert paired_comparison({'job_dmr_pct':10,'final':True},{'job_dmr_pct':20,'final':True})['change_pp']==-10


@pytest.mark.parametrize('field,value',[('loss_ppm',PPM+1),('dispatch_cost_us',-1),('release_end_us',2.5),('seed',True)])
def test_invalid_configuration_is_rejected(field,value):
    with pytest.raises(ValueError):replace(default_research_config(),**{field:value})


def test_actual_neural_execution_and_raw_manifest_reduction(tmp_path):
    from rts_predictive.api.research import PairedResearchSession
    from scripts.audit_research_trace import audit_manifest
    session=PairedResearchSession(default_research_config(release_end_us=350000),tmp_path)
    initial=session.snapshot()
    threshold=session.model_identity['threshold']
    initial['models']['threshold']=None
    initial['verification']['reference']['applies_to_live_scheduler']=True
    assert session.model_identity['threshold']==threshold
    assert session.reference['applies_to_live_scheduler'] is False
    x=session.step(session.config.end_us)
    assert x['after']['metrics']['gnn_inferences']>0
    assert x['models']['validation_scope']=='simulated_heldout_firm_task_failure'
    assert x['after']['metrics']['model_publications']>0
    assert x['host_latency']['count']==x['after']['metrics']['gnn_inferences']
    assert len(session.projections['protected'].host_latencies)==x['host_latency']['count']
    assert all(v>0 for v in session.projections['protected'].host_latencies)
    for policy in ['edf','protected']:
        root=session.root/policy;m=json.loads((root/'manifest.json').read_text())
        assert hashlib.sha256((root/'events.jsonl').read_bytes()).hexdigest()==m['event_sha256']
        reducer=ResearchProjection()
        for event in iter_canonical_events(root/'events.jsonl'):reducer.consume(event)
        assert reducer.metrics()==json.loads((root/'metrics.json').read_text())
        assert reducer.metrics()['pending_jobs']==0
        assert audit_manifest(root/'manifest.json')['status']=='PASS'
    counts=Counter(v['task_id'] for v in session.engines['protected'].events if v['event_type']=='TASK_COMMIT')
    assert max(counts.values())==1
    assert {k:t.demand for k,t in session.engines['edf'].tasks.items()}=={k:t.demand for k,t in session.engines['protected'].tasks.items()}
    configuration=json.loads((session.root/'config.json').read_text())
    configuration['devices'][0]['cpu_speed_ppm']+=1
    (session.root/'config.json').write_text(json.dumps(configuration),encoding='utf-8')
    with pytest.raises(ValueError,match='configuration checksum'):
        audit_manifest(session.root/'protected/manifest.json')


def test_fedavg_is_sample_weighted_not_equal_device_weight():
    from rts_predictive.predictors.research_adapter import ResearchModels
    model=ResearchModels()
    a={k:torch.ones_like(v) for k,v in model.remote.state_dict().items()}
    b={k:3*torch.ones_like(v) for k,v in model.remote.state_dict().items()}
    version,digest=model.publish([{'weights':a,'samples':1},{'weights':b,'samples':3}])
    assert version==1 and len(digest)==64
    assert all(torch.allclose(v,torch.full_like(v,2.5)) for v in model.remote.state_dict().values())


def test_lost_federated_uploads_never_publish():
    from rts_predictive.predictors.research_adapter import ResearchModels
    c=default_research_config(release_end_us=350000)
    c=replace(c,loss_ppm=PPM)
    e=ResearchEngine(c,models=ResearchModels(),enable_offload=False);p=finish(e)
    assert any(v['event_type']=='FL_TRAIN_END' for v in e.events)
    assert any(v['event_type']=='TRANSFER_FAILED' and v['payload']['phase']=='fl_upload' for v in e.events)
    assert p.metrics()['model_publications']==0
    assert e.models.version==0


def test_memory_exhaustion_fails_admission_without_overallocation():
    c=remote_config()
    c=replace(c,devices=tuple(replace(d,memory_mb=64) for d in c.devices))
    e=ResearchEngine(c,models=FixtureModels(),enable_fl=False);p=finish(e)
    assert p.metrics()['offloads']==0
    assert all(v['payload']['memory_mb']<=64 for v in e.events if v['event_type']=='RESOURCE_SAMPLE')
    assert p.metrics()['missed_jobs']==2 and p.metrics()['committed_tasks']==0


@pytest.mark.parametrize('policy',['fifo','rm','always_offload','reactive'])
def test_non_neural_baselines_use_same_kernel_and_no_fake_inferences(policy):
    e=ResearchEngine(default_research_config(release_end_us=100000),policy);p=finish(e)
    assert p.metrics()['gnn_inferences']==0
    assert p.metrics()['pending_jobs']==0
    assert p.metrics()['released_jobs']==32
    assert all(isinstance(v['timestamp_us'],int) for v in e.events)
    if policy=='always_offload':assert p.metrics()['offloads']>0


def test_fifo_does_not_preempt_cpu_but_edf_does():
    base=config((task('Long',work=10000,deadline=15000),),deadline=15000)
    fast=PipelineSpec('urgent',(task('Short',work=100,deadline=1000),),(),ReleaseModel.PERIODIC,1000,'Short',period_us=20000)
    c=replace(base,workflows=base.workflows+(fast,),release_end_us=3000)
    edf,fifo=ResearchEngine(c,'edf'),ResearchEngine(c,'fifo')
    a,b=finish(edf),finish(fifo)
    assert any(v['event_type']=='PREEMPT' for v in edf.events)
    assert not any(v['event_type']=='PREEMPT' for v in fifo.events)
    assert a.metrics()['completed_jobs']==2 and b.metrics()['missed_jobs']==1


def test_analytical_reference_preserves_non_applicability_and_failures():
    from rts_predictive.verification.research_reference import control_partition_reference
    c=default_research_config()
    x=control_partition_reference(c,{'source_sha256':'a'*64})
    assert x['applies_to_live_scheduler'] is False
    assert len(x['certificates'])==4
    assert any(v['certificate']['status']=='NOT_SCHEDULABLE' for v in x['certificates'])
    for v in x['certificates']:
        assert v['certificate']['binding']['scenario_hash']==c.config_hash
        assert v['certificate']['assumptions']['additional']


def test_full_capacity_fault_delivers_no_phantom_service():
    c=config(faults=(ResearchFault('Device_1',0,1000,cpu_ppm=PPM),))
    e=ResearchEngine(c,'edf');finish(e)
    services=[v for v in e.events if v['event_type']=='SERVICE']
    assert services and min(v['timestamp_us'] for v in services)>=1100
    assert sum(v['payload']['work_us'] for v in services)==100


def test_federated_training_freezes_observation_set_and_work_charge():
    from rts_predictive.predictors.research_adapter import ResearchModels
    models=ResearchModels();e=ResearchEngine(default_research_config(release_end_us=350000),models=models)
    e.run_until(300000)
    training=[op for op in e.operations.values() if op.kind=='fl_train']
    assert training
    for op in training:
        assert op.payload['samples']==len(op.payload['records'])
        assert op.remaining<=op.payload['samples']*e.config.training_work_us_per_sample
    starts={v['device_id']:v['payload']['samples'] for v in e.events if v['event_type']=='FL_TRAIN_START'}
    finish(e)
    ends={v['device_id']:v['payload']['samples'] for v in e.events if v['event_type']=='FL_TRAIN_END'}
    assert ends==starts


def test_checkpoint_updates_are_ordered_by_observation_time():
    reducer=ResearchProjection()
    for index,tid in enumerate(['A','B','A'],1):
        reducer.consume({'sequence':index,'timestamp_us':index,'event_type':'DECISION',
                         'task_id':tid,'device_id':'Device_1','payload':{'action':'LOCAL'}})
    assert [d['task'] for d in reducer.snapshot()['decisions']]==['B','A']

def test_handoff_history_recovery_is_canonical_and_survives_live_log():
    c=remote_config(faults=(ResearchFault('Device_2',300,9000,gpu_ppm=990000),))
    e=ResearchEngine(c,models=FixtureModels(),enable_fl=False);p=finish(e)
    histories=p.snapshot()['handoffs']
    recovered=[h for h in histories if h['state']=='RECOVERED']
    assert recovered
    raw={v['sequence']:v for v in e.events}
    for h in histories:
        assert all(v==raw[v['sequence']] for v in h['events'])
        assert [v['sequence'] for v in h['events']]==sorted(v['sequence'] for v in h['events'])
        assert all(v['task_id']==h['task'] for v in h['events'])
    h=recovered[0]
    commits=[v for v in h['events'] if v['event_type']=='TASK_COMMIT']
    assert len(commits)==1 and commits[0]['attempt_id']!=h['id']
    assert {'WATCHDOG_CHECK','WATCHDOG_ABORT','CANCEL_REQUEST','CANCEL_ACK','EARLY_EXIT'} <= {v['event_type'] for v in h['events']}
    check=next(v for v in reversed(h['events']) if v['event_type']=='WATCHDOG_CHECK')
    assert p.watchdogs[h['task']]['recovery_bound_us']==check['payload']['recovery_bound_us']
    assert h['origin']!=h['target']


def test_handoff_return_and_packet_loss_are_not_conflated():
    e=ResearchEngine(remote_config(),models=FixtureModels(),enable_fl=False,enable_watchdog=False);p=finish(e)
    returned=[h for h in p.snapshot()['handoffs'] if h['state']=='RETURNED']
    assert returned
    for h in returned:
        commit=next(v for v in h['events'] if v['event_type']=='TASK_COMMIT')
        assert commit['attempt_id']==h['id']
    c=remote_config(faults=(ResearchFault('Device_2',300,9000,gpu_ppm=990000,loss_ppm=PPM),))
    e=ResearchEngine(c,models=FixtureModels(),enable_fl=False);p=finish(e)
    h=next(h for h in p.snapshot()['handoffs'] if any(v['event_type']=='PACKET_LOSS' for v in h['events']))
    assert any(v['event_type']=='ATTEMPT_LEASE_EXPIRED' for v in h['events'])
    assert any(v['event_type']=='CANCEL_UNDELIVERED' for v in h['events'])
    assert h['state']!='RETURNED'

def test_remote_host_and_offload_denominator_survive_cancellation():
    c=remote_config(faults=(ResearchFault('Device_2',300,9000,gpu_ppm=990000),))
    e=ResearchEngine(c,models=FixtureModels(),enable_fl=False)
    p=ResearchProjection();seen=[]
    def project(event):
        p.consume(event)
        if event['event_type']=='CANCEL_REQUEST':
            a=p.attempts[event['attempt_id']]
            assert a['host']==event['payload']['target']
            assert a['phase']=='CANCEL_PENDING'
            assert p.metrics()['offloads']==len(p.offload_attempts)
            seen.append(event['sequence'])
    for event in e.events:project(event)
    e.subscribe(project);e.run_until(c.end_us)
    assert seen
    assert all(p.attempts[aid]['host']==e.attempts[aid].host for aid in p.offload_attempts)
    for t in p.tasks.values():
        if t['state']=='COMMITTED':
            assert t['committed_attempt']==e.tasks[t['id']].committed_attempt
            assert p.attempts[t['committed_attempt']]['phase']=='COMMITTED'


def test_task_queue_and_preemption_are_visible_before_next_execution():
    base=config((task('Long',work=10000,deadline=15000),),deadline=15000)
    urgent=PipelineSpec('urgent',(task('Short',work=100,deadline=1000),),(),ReleaseModel.PERIODIC,1000,'Short',period_us=20000)
    e=ResearchEngine(replace(base,workflows=base.workflows+(urgent,),release_end_us=3000),'edf')
    p=ResearchProjection();seen=[]
    for event in e.events:p.consume(event)
    def project(event):
        p.consume(event)
        if event['event_type'] in {'ATTEMPT_CREATED','PREEMPT'}:
            assert p.tasks[event['task_id']]['state']=='QUEUED'
            assert p.attempts[event['attempt_id']]['phase']=='QUEUED'
            seen.append(event['event_type'])
    e.subscribe(project);e.run_until(e.config.end_us)
    assert {'PREEMPT','ATTEMPT_CREATED'}<=set(seen)


@pytest.mark.parametrize('field,value',[('cpu_speed_ppm',1.5),('gpu_speed_ppm',True),('memory_mb',0),('bandwidth_mbps',float('nan'))])
def test_hardware_values_preserve_integer_runtime(field,value):
    with pytest.raises(ValueError):replace(ResearchDevice('Device_1','Test','drone',PPM,PPM),**{field:value})


def test_boolean_clock_requests_are_rejected():
    e=ResearchEngine(config(),'edf')
    with pytest.raises(ValueError):e.run_until(True)
    with pytest.raises(ValueError):e.push(False,'SAMPLE')


@pytest.mark.parametrize('family',['nominal','bursty','thermal','unreliable'])
def test_trace_audit_checks_real_models_in_each_scenario(family):
    from rts_predictive.simulator.research_audit import audit_research_events
    from rts_predictive.predictors.research_adapter import ResearchModels
    torch.set_num_threads(1)
    c=default_research_config(seed=1001,family=family,release_end_us=350000)
    e=ResearchEngine(c,models=ResearchModels());p=finish(e,1733)
    result=audit_research_events(e.events)
    assert result['status']=='PASS'
    assert result['committed_tasks']==p.metrics()['committed_tasks']
    assert result['remote_commits']==p.metrics()['offload_committed_results']
    assert all(a.work_done+a.remaining==a.total for a in e.attempts.values())


def test_trace_audit_detects_broken_causality_delivery_and_service():
    from copy import deepcopy
    from rts_predictive.simulator.research_audit import audit_research_events,TraceAuditError
    e=ResearchEngine(remote_config(),models=FixtureModels(),enable_fl=False,enable_watchdog=False);finish(e)
    assert audit_research_events(e.events)['remote_commits']>0
    wrong=deepcopy(e.events)
    next(v for v in wrong if v['event_type']=='SERVICE')['payload']['work_us']+=1
    with pytest.raises(TraceAuditError,match='conserv|progress'):audit_research_events(wrong)
    wrong=[v for v in e.events if not(v['event_type']=='TX_END' and v['payload']['phase']=='result')]
    with pytest.raises(TraceAuditError,match='result delivery'):audit_research_events(wrong)
    wrong=deepcopy(e.events)
    next(v for v in wrong if v['event_type']=='TASK_READY')['payload']['deadline_us']=0
    with pytest.raises(TraceAuditError,match='deadline'):audit_research_events(wrong)
    wrong=e.events[:-5]
    with pytest.raises(TraceAuditError,match='incomplete'):audit_research_events(wrong)

@pytest.mark.parametrize('family',['bursty','unreliable'])
def test_neural_fl_outcomes_do_not_depend_on_playback_step(family):
    from rts_predictive.predictors.research_adapter import ResearchModels
    from rts_predictive.simulator.research_audit import audit_research_events
    torch.set_num_threads(1)
    c=default_research_config(seed=1000,family=family,release_end_us=350000)
    a=ResearchEngine(c,models=ResearchModels());b=ResearchEngine(c,models=ResearchModels())
    pa,pb=finish(a),finish(b,1337)
    assert pa.metrics()==pb.metrics()
    assert {k:(t.status,t.committed_attempt) for k,t in a.tasks.items()}=={k:(t.status,t.committed_attempt) for k,t in b.tasks.items()}
    assert {k:(v.work_done,v.remaining) for k,v in a.attempts.items()}=={k:(v.work_done,v.remaining) for k,v in b.attempts.items()}
    assert a.models.version==b.models.version
    assert all(torch.equal(v,b.models.remote.state_dict()[k]) for k,v in a.models.remote.state_dict().items())
    assert [v['payload']['graph_sha256'] for v in a.events if v['event_type']=='PREDICTION']==[v['payload']['graph_sha256'] for v in b.events if v['event_type']=='PREDICTION']
    assert audit_research_events(a.events)['status']=='PASS'
    assert audit_research_events(b.events)['status']=='PASS'

def test_late_remote_admission_cannot_replace_running_fallback():
    c=remote_config(faults=(ResearchFault('Device_2',300,9000,gpu_ppm=990000),))
    spec=replace(c.workflows[0].tasks[0],exit_points=(ExitPointSpec('exit',(0,4000),20,4000,.7),))
    c=replace(c,base_link_us=3000,workflows=(replace(c.workflows[0],tasks=(spec,)),))
    e=ResearchEngine(c,models=FixtureModels(),enable_fl=False);p=ResearchProjection();observed=[]
    for event in e.events:p.consume(event)
    def project(event):
        p.consume(event)
        if event['event_type']=='REMOTE_ADMIT':
            t=e.tasks[event['task_id']]
            if t.current_attempt!=event['attempt_id'] and t.status=='RUNNING':
                projected=p.tasks[t.uid]
                assert projected['attempt']==t.current_attempt
                assert projected['host']==t.origin
                assert projected['state']=='RUNNING'
                observed.append(event['sequence'])
    e.subscribe(project);e.run_until(c.end_us)
    assert observed


def test_trace_audit_rejects_a_missing_predecessor_result():
    from rts_predictive.simulator.research_audit import audit_research_events,TraceAuditError
    c=config((task('A'),task('B')), (('A','B'),))
    e=ResearchEngine(c,'edf');finish(e)
    wrong=[v for v in e.events if not(v['event_type']=='TASK_COMMIT' and v['task_id'].endswith('/A'))]
    with pytest.raises(TraceAuditError,match='uncommitted predecessor'):audit_research_events(wrong)

def test_trace_audit_rejects_result_on_wrong_route():
    from copy import deepcopy
    from rts_predictive.simulator.research_audit import audit_research_events,TraceAuditError
    e=ResearchEngine(remote_config(),models=FixtureModels(),enable_fl=False,enable_watchdog=False);finish(e)
    wrong=deepcopy(e.events)
    transfer=next(v for v in wrong if v['event_type']=='TX_START' and v['payload']['phase']=='result')
    transfer['payload']['target']=transfer['device_id']
    with pytest.raises(TraceAuditError,match='wrong route'):audit_research_events(wrong)

@pytest.mark.parametrize('stage_period',[None,100000])
def test_rm_uses_workflow_period_for_precedence_triggered_stages(stage_period):
    long=replace(task('Long',work=10000,deadline=15000),period_us=100)
    c=config((long,),deadline=15000)
    short=replace(task('Short',work=100,deadline=1000),period_us=stage_period,minimum_interarrival_us=100000)
    urgent=PipelineSpec('urgent',(short,),(),ReleaseModel.PERIODIC,1000,'Short',period_us=10000)
    c=replace(c,workflows=c.workflows+(urgent,),release_end_us=3000)
    e=ResearchEngine(c,'rm');p=finish(e)
    assert any(v['event_type']=='PREEMPT' and v['task_id'].endswith('/Long') for v in e.events)
    assert p.metrics()['completed_jobs']==2


def test_edf_memory_guard_accounts_for_replaced_cpu_holder():
    c=config((task('Long',work=10000,deadline=15000),),deadline=15000,
             devices=(ResearchDevice('Device_1','Small RAM','drone',PPM,PPM,memory_mb=32),))
    urgent=PipelineSpec('urgent',(task('Short',work=100,deadline=1000),),(),ReleaseModel.PERIODIC,1000,'Short',period_us=20000)
    c=replace(c,workflows=c.workflows+(urgent,),release_end_us=3000)
    e=ResearchEngine(c,'edf');p=finish(e)
    assert p.metrics()['completed_jobs']==2 and p.metrics()['missed_jobs']==0
    assert any(v['event_type']=='PREEMPT' for v in e.events)
    assert all(v['payload']['memory_mb']<=32 for v in e.events if v['event_type']=='RESOURCE_SAMPLE')


@pytest.mark.parametrize('background',[0,800000,950000,1000000])
def test_sampled_service_rates_match_kernel_and_cpu_reservation(background):
    c=config((task('GPU',work=10000,gpu=True),),
             faults=(ResearchFault('Device_1',0,9000,cpu_ppm=background,gpu_ppm=400000),))
    e=ResearchEngine(c,'edf');e.run_until(0)
    r=e.resource('Device_1')
    assert e.gpu['Device_1']
    assert r['gpu_cpu_reservation_ppm']==min(150000,PPM-background)
    assert r['cpu_rate_ppm']==PPM*max(0,PPM-background-150000)//PPM*r['thermal_ppm']//PPM
    assert r['gpu_rate_ppm']==PPM*(PPM-400000)//PPM*r['thermal_ppm']//PPM
    assert e.rate('Device_1')==r['cpu_rate_ppm'] and e.rate('Device_1',True)==r['gpu_rate_ppm']


def test_fedavg_coordinator_uses_capacity_and_supports_renamed_nodes():
    from rts_predictive.predictors.research_adapter import ResearchModels
    from rts_predictive.simulator.research_audit import audit_research_events
    torch.set_num_threads(1)
    c=default_research_config(family='nominal',release_end_us=350000)
    renamed=tuple(replace(d,device_id='Host_'+str(i)) for i,d in enumerate(c.devices))
    c=replace(c,devices=renamed)
    e=ResearchEngine(c,models=ResearchModels());p=finish(e)
    assert e.fl_coordinator=='Host_1'
    rounds=[v for v in e.events if v['event_type']=='FL_ROUND_START']
    assert rounds and all(v['payload']['coordinator']=='Host_1' for v in rounds)
    assert p.metrics()['model_publications']>0
    transfers=[v for v in e.events if v['event_type']=='TX_START' and v['payload']['phase'].startswith('fl_')]
    assert transfers and all('Host_1' in (v['device_id'],v['payload']['target']) for v in transfers)
    assert audit_research_events(e.events)['status']=='PASS'


def test_deadline_projection_uses_recorded_readiness_start_and_terminal_times():
    c=config((task('Source'),task('Sink')), (('Source','Sink'),))
    e=ResearchEngine(c,'edf');p=finish(e)
    for t in p.tasks.values():
        starts=[v['timestamp_us'] for v in e.events if v['event_type']=='EXECUTION_START' and v['task_id']==t['id']]
        commits=[v['timestamp_us'] for v in e.events if v['event_type']=='TASK_COMMIT' and v['task_id']==t['id']]
        assert t['first_start_us']==min(starts)
        assert t['terminal_us']==commits[0]==t['commit_us']
        assert t['ready_us']<=t['first_start_us']<=t['terminal_us']<=t['deadline_us']


@pytest.mark.parametrize('field',['cpu_rate_ppm','gpu_rate_ppm','gpu_cpu_reservation_ppm','thermal_ppm','cpu_ppm'])
def test_trace_audit_rejects_capacity_rates_that_disagree_with_hardware(field):
    from copy import deepcopy
    from rts_predictive.simulator.research_audit import audit_research_events,TraceAuditError
    c=config((task('GPU',work=10000,gpu=True),),
             devices=(ResearchDevice('Device_1','Faster node','drone',2*PPM,3*PPM),),
             faults=(ResearchFault('Device_1',0,9000,cpu_ppm=200000,gpu_ppm=300000),))
    e=ResearchEngine(c,'edf');finish(e)
    assert audit_research_events(e.events,devices=c.to_dict()['devices'])['status']=='PASS'
    wrong=deepcopy(e.events)
    next(v for v in wrong if v['event_type']=='RESOURCE_SAMPLE')['payload'][field]+=(-1 if field=='thermal_ppm' else 1)
    with pytest.raises(TraceAuditError,match='rate|reservation|occupancy'):
        audit_research_events(wrong,devices=c.to_dict()['devices'])


def test_firm_drop_projection_records_early_sibling_terminal_and_skipped_stage():
    c=config((task('First',work=100,deadline=1000),task('Fails',work=1000,deadline=200),
              task('Sibling',work=10000,deadline=10000,gpu=True),task('Join',work=100)),
             (('First','Fails'),('First','Sibling'),('Fails','Join'),('Sibling','Join')))
    e=ResearchEngine(c,'edf');p=finish(e)
    by_name={t['name']:t for t in p.tasks.values()}
    fail,sibling,join=(by_name[n] for n in ('Fails','Sibling','Join'))
    assert fail['terminal_us']==fail['deadline_us']
    assert sibling['terminal_us']==fail['terminal_us']<sibling['deadline_us']
    assert sibling['reason']=='job_dropped' and sibling['state']=='MISSED'
    assert join['state']=='SKIPPED' and join['terminal_us']==fail['terminal_us']
    assert 'ready_us' not in join and 'first_start_us' not in join
    job=next(iter(p.jobs.values()))
    assert job['failure_task']==fail['id'] and job['failure_us']==fail['terminal_us']
    assert job['terminal_us']==fail['terminal_us'] and job['failure_reason']=='stage_deadline'


def test_research_snapshots_are_isolated_from_future_events_and_caller_mutation():
    from copy import deepcopy
    e=ResearchEngine(config((task(work=1000),)),'edf')
    p=ResearchProjection()
    for event in e.events:p.consume(event)
    e.subscribe(p.consume);e.run_until(100)
    original=p.snapshot();frozen=deepcopy(original)
    e.run_until(e.config.end_us)
    assert original==frozen
    latest=p.snapshot();untouched=deepcopy(latest)
    latest['tasks'][0]['state']='BROKEN'
    latest['resources']['Device_1']['operations'].append({'kind':'invented'})
    latest['events'][0]['payload']['fake']=True
    assert p.snapshot()==untouched


def test_old_task_diagnostics_survive_recent_record_limits_and_are_isolated():
    from copy import deepcopy
    e=ResearchEngine(remote_config(),models=FixtureModels(),enable_fl=False);p=finish(e)
    tid=next(t for t in p.predictions)
    for index in range(24):
        other='unrelated-'+str(index)
        p.predictions[other]={'task':other,'device':'Device_1','at_us':e.now+index,'miss_probability':.2}
    snapshot=p.snapshot()
    assert not any(v['task']==tid for v in snapshot['predictions'])
    t=next(t for t in snapshot['tasks'] if t['id']==tid)
    diagnostics=t['diagnostics']
    assert diagnostics['prediction']==p.predictions[tid]
    assert diagnostics['decision']==p.decisions[tid]
    original=deepcopy(p.predictions[tid])
    diagnostics['prediction']['miss_probability']=999
    assert p.predictions[tid]==original


def test_trace_audit_rejects_double_service_on_one_lane_but_allows_parallel_lanes():
    from copy import deepcopy
    from rts_predictive.simulator.research_audit import audit_research_events,TraceAuditError
    e=ResearchEngine(config((task('CPU',work=1000),task('GPU',work=2000,gpu=True),task('Join')),
                            (('CPU','Join'),('GPU','Join'))),'edf')
    finish(e)
    assert audit_research_events(e.events)['status']=='PASS'
    service_times={lane:{v['timestamp_us'] for v in e.events if v['event_type']=='SERVICE' and v['payload']['lane']==lane} for lane in ('cpu','gpu')}
    assert service_times['cpu'] & service_times['gpu']
    wrong=deepcopy(e.events)
    service=next(v for v in wrong if v['event_type']=='SERVICE')
    position=wrong.index(service)
    wrong.insert(position+1,deepcopy(service))
    for sequence,event in enumerate(wrong,1):event['sequence']=sequence
    with pytest.raises(TraceAuditError,match='overlapping exclusive'):
        audit_research_events(wrong)


def test_trace_audit_rejects_commitment_after_a_firm_job_drop():
    from copy import deepcopy
    from rts_predictive.simulator.research_audit import audit_research_events,TraceAuditError
    e=ResearchEngine(config(),'edf');finish(e)
    wrong=deepcopy(e.events)
    commit=next(v for v in wrong if v['event_type']=='TASK_COMMIT')
    missed={**commit,'event_type':'JOB_MISS','task_id':None,'attempt_id':None,'payload':{'reason':'injected_drop'}}
    wrong.insert(wrong.index(commit),missed)
    for sequence,event in enumerate(wrong,1):event['sequence']=sequence
    with pytest.raises(TraceAuditError,match='commitment in terminal'):
        audit_research_events(wrong)


@pytest.mark.parametrize('base_link,faults',[(2000,()),(200,(ResearchFault('Device_2',400,9000,extra_link_us=3000),))])
def test_delayed_remote_request_after_firm_drop_cannot_resurrect_task(base_link,faults):
    from rts_predictive.simulator.research_audit import audit_research_events
    c=config((task('Fails',work=2000,deadline=500,gpu=True),
              task('Remote',work=8000,deadline=15000,gpu=True,offloadable=True,request_payload_bytes=100,result_payload_bytes=100),task('Join')),
             (('Fails','Join'),('Remote','Join')),deadline=16000,devices=remote_config().devices)
    c=replace(c,base_link_us=base_link,faults=faults)
    e=ResearchEngine(c,models=FixtureModels(),enable_fl=False,enable_watchdog=False)
    e.run_until(2300)
    remote=[t for t in e.tasks.values() if t.spec.task_id=='Remote']
    assert remote and all(t.status=='MISSED' and e.jobs[t.job_id].status=='MISSED' for t in remote)
    assert any(v['event_type']=='REMOTE_ADMIT' for v in e.events)
    assert any(v['event_type']=='EXECUTION_START' and v['task_id'].endswith('/Remote') and v['timestamp_us']>500 for v in e.events)
    assert any(v['event_type']=='SERVICE' and v['task_id'].endswith('/Remote') and v['timestamp_us']>500 for v in e.events)
    while e.now<c.end_us:e.run_until(min(c.end_us,e.now+173))
    p=finish(e)
    deadlines=Counter(v['task_id'] for v in e.events if v['event_type']=='TASK_DEADLINE')
    assert max(deadlines.values())==1
    assert all(t.status=='MISSED' for t in remote)
    assert p.metrics()['missed_jobs']==2 and not p.metrics()['completed_jobs']
    assert audit_research_events(e.events)['status']=='PASS'


@pytest.mark.parametrize('work',[0,-1,True,1.5])
def test_trace_audit_rejects_invalid_controller_work(work):
    from copy import deepcopy
    from rts_predictive.simulator.research_audit import audit_research_events,TraceAuditError
    e=ResearchEngine(replace(config(),dispatch_cost_us=40),'edf');finish(e)
    wrong=deepcopy(e.events)
    next(v for v in wrong if v['event_type']=='CPU_OVERHEAD')['payload']['work_us']=work
    with pytest.raises(TraceAuditError,match='invalid delivered work'):
        audit_research_events(wrong)


def test_task_offload_identity_is_retained_when_detailed_history_is_bounded():
    c=replace(remote_config(),release_end_us=600000)
    e=ResearchEngine(c,models=FixtureModels(),enable_fl=False);p=finish(e)
    snapshot=p.snapshot()
    assert snapshot['handoff_history_total']>snapshot['handoff_history_limit']
    assert len(snapshot['handoffs'])==snapshot['handoff_history_limit']
    recent={h['id'] for h in snapshot['handoffs']}
    assert any(t.get('handoff_ids') and not any(a in recent for a in t['handoff_ids']) for t in snapshot['tasks'])
    for t in p.snapshot()['tasks']:
        actual=[v['attempt_id'] for v in e.events if v['task_id']==t['id'] and v['event_type']=='OFFLOAD_DISPATCH']
        assert t.get('handoff_ids',[])==actual
    assert p.snapshot()['handoff_history_total']==len(p.handoffs)
    assert p.snapshot()['handoff_history_limit']==48


@pytest.mark.parametrize('corruption',['overlap','early_arrival'])
def test_radio_audit_checks_serialization_but_allows_overlapping_propagation(corruption):
    from copy import deepcopy
    from rts_predictive.simulator.research_audit import audit_research_events,TraceAuditError
    c=remote_config()
    e=ResearchEngine(c,'edf',enable_fl=False)
    e._send('Device_1','Device_2',100000,'fl_upload',payload={'round':1})
    e._send('Device_1','Device_2',100000,'fl_upload',payload={'round':1})
    finish(e)
    assert audit_research_events(e.events,devices=c.to_dict()['devices'])['status']=='PASS'
    packets=[v for v in e.events if v['event_type']=='TX_START' and v['payload']['phase']=='fl_upload']
    assert packets[1]['payload']['start_us']<packets[0]['payload']['end_us']
    wrong=deepcopy(e.events)
    changed=next(v for v in wrong if v['event_type']=='TX_START' and v['payload']['transfer']==packets[1]['payload']['transfer'])
    if corruption=='overlap':changed['payload']['start_us']=packets[0]['payload']['start_us']
    else:changed['payload']['end_us']=changed['payload']['start_us']+1
    with pytest.raises(TraceAuditError,match='radio serialization|before serialization'):
        audit_research_events(wrong,devices=c.to_dict()['devices'])


def test_recorded_neural_graph_reproduces_the_actual_forward_pass():
    from rts_predictive.predictors.research_adapter import ResearchModels
    from rts_predictive.simulator.research_audit import audit_research_events
    models=ResearchModels();e=ResearchEngine(config((task(work=4000,gpu=True,offloadable=True),)),models=models,enable_fl=False)
    finish(e)
    prediction=next(v for v in e.events if v['event_type']=='PREDICTION')
    p=prediction['payload'];g=p['graph']
    x=torch.tensor(g['features'],dtype=torch.float32);edges=torch.tensor(g['edge_index'],dtype=torch.long)
    assert hashlib.sha256(x.numpy().tobytes()+edges.numpy().tobytes()).hexdigest()==p['graph_sha256']
    with torch.no_grad():risk,ttv,cause=models.gnn(x,edges)
    assert models.gnn._calibrate_probability(float(risk[0,0]))==p['miss_probability']
    assert g['node_ids'][g['query_index']]==prediction['task_id']
    assert p['vertices']==x.shape[0] and p['edges']==edges.shape[1]
    assert audit_research_events(e.events)['status']=='PASS'


@pytest.mark.parametrize('corruption',['feature','endpoint','shape','query','duplicate','risk_gate','local_guard','combined_gate','nan','threshold','probability','gate_type'])
def test_auditor_rejects_corrupted_neural_inputs_and_decision_explanations(corruption):
    from copy import deepcopy
    from rts_predictive.predictors.research_adapter import ResearchModels
    from rts_predictive.simulator.research_audit import audit_research_events,TraceAuditError
    e=ResearchEngine(config((task(work=4000,gpu=True,offloadable=True),)),models=ResearchModels(),enable_fl=False);finish(e)
    wrong=deepcopy(e.events);p=next(v['payload'] for v in wrong if v['event_type']=='PREDICTION');g=p['graph']
    if corruption=='nan':g['features'][4][3]=float('nan')
    elif corruption=='probability':p['miss_probability']=1.1
    elif corruption=='feature':g['features'][4][3]+=.1
    elif corruption=='endpoint':g['edge_index'][0][0]=len(g['node_ids'])
    elif corruption=='shape':g['features'][0].pop()
    elif corruption=='query':g['query_index']=0
    elif corruption=='duplicate':g['node_ids'][-1]=g['node_ids'][0]
    else:
        d=next(v['payload'] for v in wrong if v['event_type']=='DECISION')
        if corruption=='threshold':d['threshold']=float('nan')
        elif corruption=='gate_type':d['risk_gate']=int(d['risk_gate'])
        else:
            field={'risk_gate':'risk_gate','local_guard':'local_deadline_guard','combined_gate':'high_risk'}[corruption]
            d[field]=not d[field]
    with pytest.raises(TraceAuditError,match='neural|gate|guard'):
        audit_research_events(wrong)
