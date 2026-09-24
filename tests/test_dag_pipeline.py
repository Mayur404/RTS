"""
Integration tests for DAG Pipeline Job Releases, Precedence Progression,
and Single-Commit Invariants.
"""

import pytest
from rts_predictive.config import PredictiveRuntimeConfig, HARDWARE_PROFILES, DEFAULT_TASK_PROFILES
from rts_predictive.domain.specs import create_autonomous_ai_pipeline_spec
from rts_predictive.simulator.engine import DiscreteEventSimulator
from rts_predictive.simulator.device import DeviceNode
from rts_predictive.simulator.tasks import TaskInstance, TaskState
from rts_predictive.simulator.events import EventType
from rts_predictive.schedulers.edf import EDFScheduler
from rts_predictive.schedulers.local_fifo import LocalFIFOScheduler


def test_dag_pipeline_spec_creation():
    spec = create_autonomous_ai_pipeline_spec()
    assert spec.pipeline_id == "autonomous_pipeline"
    assert spec.sink_task_id == "Actuation"
    assert len(spec.tasks) == 6
    assert spec.end_to_end_deadline_us == 50_000


def test_dag_pipeline_job_precedence_progression():
    """Verify that downstream tasks are only released when predecessors complete."""
    config = PredictiveRuntimeConfig(simulation_duration_ms=100.0)
    sim = DiscreteEventSimulator(config=config, seed=42, fleet_size=2)
    sim.attach_scheduler(LocalFIFOScheduler())

    job_id = sim.schedule_pipeline_job(
        pipeline_spec=create_autonomous_ai_pipeline_spec(),
        release_time_ms=0.0,
        device_id="Device_1",
    )

    # Initial state before run: source task Sense is scheduled
    queued_task_names = [ev.task.task_name for ev in sim.events._heap if ev.task is not None]
    assert "Sense" in queued_task_names
    assert "ObstacleDetection" not in queued_task_names

    # Run simulation forward
    metrics = sim.run(duration_ms=60.0)

    # All 6 stages should have completed in DAG sequence
    job = sim.pipeline_jobs[job_id]
    assert job["completed"] is True
    assert job["domain_job"].completed_at_us is not None

    # Check canonical events for PIPELINE_COMPLETE
    pipeline_events = [
        e for e in sim.canonical_events
        if e.get("event_type") == "PIPELINE_COMPLETE"
    ]
    assert len(pipeline_events) == 1
    assert pipeline_events[0]["job_id"] == job_id
    task_events = [
        event for event in sim.canonical_events
        if event["event_type"] in {"TASK_READY", "TASK_COMMIT"}
    ]
    assert task_events
    assert all(event["job_id"] == job_id for event in task_events)
    assert all(event["attempt_id"] for event in task_events)


def test_dag_pipeline_output_utility_accounting():
    """Verify that utility is recorded in metrics."""
    config = PredictiveRuntimeConfig(simulation_duration_ms=80.0)
    sim = DiscreteEventSimulator(config=config, seed=123, fleet_size=2)
    sim.attach_scheduler(EDFScheduler())

    sim.schedule_pipeline_job(
        pipeline_spec=create_autonomous_ai_pipeline_spec(),
        release_time_ms=0.0,
        device_id="Device_1",
    )

    metrics = sim.run(duration_ms=80.0)
    assert "avg_utility" in metrics
    assert 0.0 <= metrics["avg_utility"] <= 1.0


def test_single_commit_late_result_discarded():
    """Verify that a late result from an abandoned offload attempt is discarded."""
    config = PredictiveRuntimeConfig(simulation_duration_ms=100.0)
    sim = DiscreteEventSimulator(config=config, seed=99, fleet_size=2)

    task = TaskInstance.from_profile(
        DEFAULT_TASK_PROFILES["Perception"],
        "perc_test_late",
        "Device_1",
        release_time_ms=0.0,
    )
    task.attempt_id = "attempt_remote_1"
    dev1 = sim.devices["Device_1"]
    dev1.offloaded_tasks[task.instance_id] = {
        "target_id": "Device_2",
        "status": "ABORTED",
        "attempt_id": "attempt_remote_1",
        "task": task,
    }

    # An event arrives from Device_2 attempting to commit the remote result
    sim.events.push(
        timestamp_ms=50.0,
        event_type=EventType.OFFLOAD_RETURN,
        device_id="Device_1",
        task=task,
        payload={"task_id": task.instance_id, "attempt_id": "attempt_remote_1"},
    )
    sim.run(duration_ms=60.0)

    # Must log LATE_RESULT_DISCARDED and not commit
    discarded = [
        e for e in sim.canonical_events
        if e.get("event_type") == "LATE_RESULT_DISCARDED"
    ]
    assert len(discarded) == 1
    assert discarded[0]["task_id"] == "perc_test_late"


def test_future_pipeline_release_is_causal():
    sim = DiscreteEventSimulator(seed=3, fleet_size=1)
    job_id = sim.schedule_pipeline_job(create_autonomous_ai_pipeline_spec(), 10.0)
    assert not sim.canonical_events
    sim.run(9.0)
    assert not any(e["event_type"] == "PIPELINE_RELEASE" for e in sim.canonical_events)
    sim.run(10.0)
    releases = [e for e in sim.canonical_events if e["event_type"] == "PIPELINE_RELEASE"]
    assert len(releases) == 1
    assert releases[0]["job_id"] == job_id
    assert releases[0]["timestamp_us"] == 10_000


def test_remote_pipeline_stage_releases_successor_only_after_result_arrival():
    sim = DiscreteEventSimulator(seed=4, fleet_size=2)
    job_id = sim.schedule_pipeline_job(create_autonomous_ai_pipeline_spec(), 0.0)
    sim.run(0.0)
    source = sim.pipeline_jobs[job_id]["tasks"]["Sense"]
    origin = sim.devices["Device_1"]
    origin.record_offload_dispatch(source, "Device_2", 0.0, 1.0)
    sim.attach_scheduler(LocalFIFOScheduler())
    sim.schedule_offload_request(source, "Device_2")
    sim.run(40.0)
    returned = next(e["timestamp_us"] for e in sim.canonical_events
                    if e["event_type"] == "RESULT_TX_END" and e["task_id"] == source.instance_id)
    successor = sim.pipeline_jobs[job_id]["tasks"].get("ObstacleDetection")
    assert successor is not None
    ready = next(e["timestamp_us"] for e in sim.canonical_events
                 if e["event_type"] == "TASK_READY" and e["task_id"] == successor.instance_id)
    assert ready >= returned
