"""Known exhausted delivery must not be represented as a zero remote bound."""
from copy import deepcopy
from dataclasses import replace

import pytest
from test_research_engine import FixtureModels,remote_config,finish
from rts_predictive.domain.research import ResearchFault,PPM
from rts_predictive.simulator.research_engine import ResearchEngine
from rts_predictive.simulator.research_audit import audit_research_events,TraceAuditError
from scripts.check_watchdog_observations import audit_watchdog_observations


def failed_result_engine(**features):
    # Request arrives before the actual configured loss window; result delivery
    # is then lost with no retry. These controlled models are unit fixtures.
    c=replace(remote_config(faults=(ResearchFault('Device_2',1500,15000,loss_ppm=PPM),)),retry_limit=0)
    return ResearchEngine(c,models=FixtureModels(),enable_fl=False,**features)


def test_exhausted_result_delivery_recovers_at_next_watchdog_check():
    e=failed_result_engine();p=finish(e)
    failed=next(v for v in e.events if v['event_type']=='TRANSFER_FAILED' and v['payload']['phase']=='result')
    check=next(v for v in e.events if v['event_type']=='WATCHDOG_CHECK' and v['attempt_id']==failed['attempt_id'] and v['sequence']>failed['sequence'])
    assert check['payload']['action']=='ABORT' and check['payload']['reason']=='remote_transfer_failed'
    assert check['payload']['remote_bound_us'] is None
    assert check['payload']['remote_transfer_failed']=='result'
    charged=[v for v in e.events if v['event_type']=='CPU_OVERHEAD' and v['device_id']==e.tasks[failed['task_id']].origin and v['payload']['category']=='watchdog' and failed['timestamp_us']<v['timestamp_us']<=check['timestamp_us']]
    assert charged and check['timestamp_us']<check['payload']['latest_abort_us']
    commits=[v for v in e.events if v['event_type']=='TASK_COMMIT' and v['task_id']==failed['task_id']]
    assert len(commits)==1
    assert commits[0]['device_id']==e.tasks[failed['task_id']].origin and commits[0]['payload']['degraded']
    assert audit_research_events(e.events)['status']=='PASS'
    assert audit_watchdog_observations(e.events)['matched_recovery_admissions']>0


@pytest.mark.parametrize('disabled',['watchdog','fallback'])
def test_delivery_failure_respects_disabled_recovery_components(disabled):
    e=failed_result_engine(**{'enable_'+disabled:False});p=finish(e)
    assert p.metrics()['watchdog_aborts']==0 and p.metrics()['committed_tasks']==0
    assert p.metrics()['missed_jobs']==p.metrics()['released_jobs']
    if disabled=='fallback':
        failed=[v for v in e.events if v['event_type']=='WATCHDOG_CHECK' and v['payload'].get('remote_transfer_failed')]
        assert failed and all(v['payload']['reason']=='no_admissible_fallback' for v in failed)
    assert audit_research_events(e.events)['status']=='PASS'


def test_recovery_handoff_retains_matching_certificate_and_output_events():
    e=failed_result_engine();p=finish(e)
    h=next(h for h in p.snapshot()['handoffs'] if h['state']=='RECOVERED')
    required={'FALLBACK_ADMITTED','FALLBACK_BOUND_CHECK','OUTPUT_VALIDATION'}
    assert required<={v['event_type'] for v in h['events']}
    raw={v['sequence']:v for v in e.events}
    assert all(v==raw[v['sequence']] for v in h['events'])
    admission=next(v for v in h['events'] if v['event_type']=='FALLBACK_ADMITTED')
    check=next(v for v in h['events'] if v['event_type']=='FALLBACK_BOUND_CHECK')
    assert admission['payload']['certificate_sha256']==check['payload']['certificate_sha256']


@pytest.mark.parametrize('field,value',[('remote_bound_us',0),('reason','remote_within_window'),('action','CONTINUE'),('remote_transfer_failed',None)])
def test_independent_audit_rejects_invented_watchdog_explanations(field,value):
    e=failed_result_engine();finish(e);events=deepcopy(e.events)
    check=next(v for v in events if v['event_type']=='WATCHDOG_CHECK' and v['payload'].get('remote_transfer_failed'))
    check['payload'][field]=value
    with pytest.raises(TraceAuditError,match='watchdog'):
        audit_research_events(events)


def test_watchdog_bound_must_match_actual_analysis_even_if_its_window_is_consistent():
    e=failed_result_engine();finish(e);events=deepcopy(e.events)
    check=next(v for v in events if v['event_type']=='WATCHDOG_CHECK' and v['payload'].get('remote_transfer_failed'))
    check['payload']['recovery_bound_us']+=1;check['payload']['latest_abort_us']-=1
    # Gate arithmetic alone is consistent; independently bind it to its analysis.
    assert audit_research_events(events)['status']=='PASS'
    with pytest.raises(ValueError,match='conditional certificate'):
        audit_watchdog_observations(events)
