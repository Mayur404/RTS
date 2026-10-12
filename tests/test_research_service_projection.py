"""Attempt progress must remain exact between samples and after cancellation."""
from collections import Counter

import pytest

from rts_predictive.dashboard.research_projection import ResearchProjection
from rts_predictive.domain.research import ResearchConfig, ResearchDevice, PPM
from rts_predictive.domain.specs import (
    TaskSpec, ResourceDemand, ResourceKind, WcetDistributionSpec, PipelineSpec, ReleaseModel,
)
from rts_predictive.simulator.research_engine import ResearchEngine


def scenario(gpu, deadline):
    spec = TaskSpec('Stage', (ResourceDemand(ResourceKind.GPU if gpu else ResourceKind.CPU, 1),),
                    deadline, WcetDistributionSpec('constant', 12000, 12000, 12000), period_us=20000)
    workflow = PipelineSpec('flow', (spec,), (), ReleaseModel.PERIODIC, deadline, 'Stage', period_us=20000)
    return ResearchConfig(devices=(ResearchDevice('Device_1', 'Test', 'drone', PPM, PPM),),
                          workflows=(workflow,), release_end_us=1, drain_us=20000,
                          dispatch_cost_us=0, inference_cost_us=0)


@pytest.mark.parametrize('gpu', [False, True])
@pytest.mark.parametrize('deadline', [7333, 18000])
def test_attempt_progress_matches_service_after_every_event(gpu, deadline):
    engine = ResearchEngine(scenario(gpu, deadline), 'edf')
    engine.run_until(engine.config.end_us)
    projection = ResearchProjection()
    delivered = Counter()
    for event in engine.events:
        if event['event_type'] == 'SERVICE':
            delivered[event['attempt_id']] += event['payload']['work_us']
        projection.consume(event)
        for aid, work in delivered.items():
            attempt = projection.attempts[aid]
            assert attempt['work_done_us'] == work
            assert attempt['remaining_us'] == attempt['total_work_us'] - work
    for aid, actual in engine.attempts.items():
        shown = projection.attempts[aid]
        assert shown['work_done_us'] == actual.work_done
        assert shown['remaining_us'] == actual.remaining
        assert shown['phase'] == actual.phase


def test_replay_does_not_require_resource_samples_to_reconstruct_progress():
    engine = ResearchEngine(scenario(True, 7333), 'edf')
    engine.run_until(engine.config.end_us)
    projection = ResearchProjection()
    for event in engine.events:
        if event['event_type'] != 'RESOURCE_SAMPLE':
            projection.consume(event)
    actual = next(iter(engine.attempts.values()))
    shown = projection.attempts[actual.lifecycle.attempt_id]
    assert shown['phase'] == 'CANCELLED'
    assert shown['work_done_us'] == actual.work_done == 7333
    assert shown['remaining_us'] == actual.remaining
