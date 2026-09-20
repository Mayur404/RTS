import json

import pytest

from ghostguard.domain import (
    AttemptKind,
    AttemptState,
    CanonicalEvent,
    Criticality,
    DeviceSpec,
    EventType,
    ExecutionAttempt,
    PipelineJob,
    PipelineSpec,
    PolicySpec,
    PreemptionMode,
    ReleaseModel,
    ResourceDemand,
    ResourceKind,
    TaskSpec,
    WcetDistributionSpec,
)


def make_task(task_id: str, *, deadline_us: int = 10_000) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        resource_demands=(ResourceDemand(ResourceKind.CPU, 0.5, 1024),),
        relative_deadline_us=deadline_us,
        wcet_distribution=WcetDistributionSpec("bounded_uniform", 100, 400, 800),
        criticality=Criticality.HIGH,
        preemption_mode=PreemptionMode.PREEMPTIVE,
        period_us=20_000,
    )


def make_pipeline(edges=(('sense', 'act'),)) -> PipelineSpec:
    return PipelineSpec(
        pipeline_id="control",
        tasks=(make_task("sense"), make_task("act")),
        dependency_edges=edges,
        release_model=ReleaseModel.PERIODIC,
        period_us=20_000,
        end_to_end_deadline_us=15_000,
        sink_task_id="act",
    )


def complete_attempt(task, attempt_id: str, *, completed_at_us: int = 500):
    attempt = ExecutionAttempt(
        attempt_id=attempt_id,
        task_instance_id=task.instance_id,
        kind=AttemptKind.LOCAL,
        target_device_id="edge-1",
    )
    task.add_attempt(attempt)
    attempt.start(100)
    assert attempt.complete(completed_at_us)
    return attempt


def test_integer_microsecond_validation_rejects_floats_and_negative_values():
    with pytest.raises(TypeError, match="integer number of microseconds"):
        make_task("bad", deadline_us=10.5)

    with pytest.raises(ValueError, match="positive"):
        WcetDistributionSpec("constant", 1, 1, 0)

    with pytest.raises(ValueError, match="period_us"):
        PipelineSpec(
            pipeline_id="bad",
            tasks=(make_task("only"),),
            dependency_edges=(),
            release_model=ReleaseModel.PERIODIC,
            end_to_end_deadline_us=10,
            sink_task_id="only",
        )


def test_spec_hashes_are_canonical_stable_and_sensitive_to_data():
    left_parameters = {"risk": 0.6, "nested": {"b": 2, "a": [1, 3]}}
    right_parameters = {"nested": {"a": [1, 3], "b": 2}, "risk": 0.6}
    left = PolicySpec("ghostguard", "1.0", left_parameters)
    right = PolicySpec("ghostguard", "1.0", right_parameters)

    assert left.to_json() == right.to_json()
    assert left.configuration_hash == right.configuration_hash
    assert len(left.configuration_hash) == 64
    assert PolicySpec("ghostguard", "1.0", {"risk": 0.7}).config_hash != left.config_hash

    left_parameters["risk"] = 0.1
    left_parameters["nested"]["a"].append(99)
    assert left.configuration_hash == right.configuration_hash
    with pytest.raises(TypeError):
        left.parameters["risk"] = 0.9


def test_pipeline_accepts_valid_dag_and_rejects_cycles_and_unknown_nodes():
    pipeline = make_pipeline()
    assert pipeline.sink_task_id == "act"
    assert pipeline.task_by_id["sense"].task_id == "sense"

    with pytest.raises(ValueError, match="acyclic"):
        make_pipeline((('sense', 'act'), ('act', 'sense')))

    with pytest.raises(ValueError, match="unknown task"):
        make_pipeline((('sense', 'missing'),))


def test_events_sort_by_queue_coordinates_and_round_trip_canonical_json():
    later_sequence = CanonicalEvent(
        timestamp_us=100,
        priority=1,
        sequence=2,
        event_type=EventType.TASK_READY,
        event_id="event-2",
        run_id="run-1",
        task_id="task-1",
        payload={"slack_us": 900, "cause": {"load": 0.7}},
    )
    earlier_sequence = CanonicalEvent(
        timestamp_us=100,
        priority=1,
        sequence=1,
        event_type=EventType.TASK_READY,
        event_id="event-1",
        run_id="run-1",
        task_id="task-1",
        payload={"cause": {"load": 0.7}, "slack_us": 900},
    )
    earlier_priority = CanonicalEvent(
        timestamp_us=100,
        priority=0,
        sequence=99,
        event_type=EventType.DEADLINE,
        event_id="event-0",
        run_id="run-1",
    )

    assert sorted((later_sequence, earlier_sequence, earlier_priority)) == [
        earlier_priority,
        earlier_sequence,
        later_sequence,
    ]
    restored = CanonicalEvent.from_json(earlier_sequence.to_json())
    assert restored == earlier_sequence
    assert earlier_sequence != later_sequence
    assert json.loads(restored.to_json())["timestamp_us"] == 100

    with pytest.raises(ValueError, match="reserved event fields"):
        CanonicalEvent(
            1,
            1,
            1,
            EventType.TASK_READY,
            "event-bad",
            "run-1",
            payload={"task_id": "smuggled-identity"},
        )


def test_job_releases_sources_after_creation_and_successors_only_after_commit():
    job = PipelineJob.from_spec("job-1", make_pipeline(), 0)
    assert job.tasks["sense"].state.value == "READY"
    assert job.tasks["act"].state.value == "BLOCKED"

    complete_attempt(job.tasks["sense"], "sense-local")
    assert job.commit_attempt("sense", "sense-local", 500) == ("act",)
    assert job.tasks["act"].state.value == "READY"


def test_single_commit_is_idempotent_and_discards_competing_result():
    job = PipelineJob.from_spec("job-1", make_pipeline(), 0)
    task = job.tasks["sense"]
    selected = complete_attempt(task, "local", completed_at_us=400)
    rival = complete_attempt(task, "remote", completed_at_us=450)

    assert task.commit_attempt("local", 401)
    assert not task.commit_attempt("local", 402)
    assert not task.commit_attempt("remote", 451)
    assert task.committed_attempt_id == "local"
    assert selected.state is AttemptState.COMMITTED
    assert rival.state is AttemptState.LATE_RESULT_DISCARDED


def test_cancelled_attempt_cannot_commit_and_late_completion_is_discarded():
    job = PipelineJob.from_spec("job-1", make_pipeline(), 0)
    task = job.tasks["sense"]
    attempt = ExecutionAttempt("remote", task.instance_id, AttemptKind.REMOTE, "edge-2")
    task.add_attempt(attempt)
    attempt.start(100)
    attempt.charge(service_us=250, network_bytes=4096)
    attempt.request_cancel()
    attempt.acknowledge_cancel(300)

    assert not attempt.complete(350)
    assert attempt.state is AttemptState.LATE_RESULT_DISCARDED
    assert attempt.service_received_us == 250
    assert attempt.network_bytes == 4096
    assert not task.commit_attempt("remote", 351)
    assert task.committed_attempt_id is None


def test_task_lifecycle_helpers_preserve_attempt_and_logical_task_identity():
    task = PipelineJob.from_spec("job-1", make_pipeline(), 0).tasks["sense"]
    attempt = task.create_attempt("local", AttemptKind.LOCAL, "edge-1", 10)
    task.dispatch_attempt("local")
    task.start_attempt("local", 20)
    assert task.complete_attempt("local", 200)
    assert task.state.value == "COMPLETED"
    assert task.commit_attempt("local", 201)
    assert task.state.value == "COMMITTED"
    assert attempt.state is AttemptState.COMMITTED


def test_device_rejects_non_integer_thermal_time():
    with pytest.raises(TypeError, match="integer number of microseconds"):
        DeviceSpec(
            device_id="edge",
            cpu_capacity=1.0,
            gpu_capacity=1.0,
            cpu_concurrency=1,
            gpu_concurrency=1,
            memory_bytes=1024,
            thermal_time_constant_us=1.5,
        )
