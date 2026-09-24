"""Behavioral checks for remote result causality and metric denominators."""

from rts_predictive.config import PredictiveRuntimeConfig, DEFAULT_TASK_PROFILES
from rts_predictive.simulator.engine import DiscreteEventSimulator
from rts_predictive.simulator.events import EventType
from rts_predictive.simulator.tasks import TaskInstance, TaskState
from rts_predictive.schedulers.local_fifo import LocalFIFOScheduler
from rts_predictive.schedulers.predictive_runtime import PredictiveRuntimeScheduler
from rts_predictive.schedulers.always_offload import AlwaysOffloadScheduler
from rts_predictive.schedulers.predictive_no_fallback import PredictiveNoFallbackScheduler
from rts_predictive.experiments.scenarios import create_bursty_scenario
from rts_predictive.artifacts import CanonicalEventWriter
from scripts.generate_paper_artifacts import reduce_event_stream
import pytest


def test_remote_result_commits_only_after_actual_execution_and_return_packet():
    sim = DiscreteEventSimulator(PredictiveRuntimeConfig(), seed=1, fleet_size=2)
    sim.attach_scheduler(LocalFIFOScheduler())
    task = TaskInstance.from_profile(
        DEFAULT_TASK_PROFILES["Perception"], "remote-1", "Device_1", 0.0
    )
    task.deadline_ms = 200.0
    sim.all_tasks.append(task)
    sim.devices["Device_1"].record_offload_dispatch(task, "Device_2", 0.0, 1.0)
    sim.schedule_offload_request(task, "Device_2")
    sim.events.push(task.deadline_ms, EventType.DEADLINE_EXPIRED, "Device_1", task)

    sim.run(duration_ms=10.0)
    assert task.finish_time_ms is None
    assert task.state != TaskState.COMPLETED

    sim.run(duration_ms=190.0)
    trace = [e for e in sim.telemetry_log if e.get("task_id") == task.instance_id]
    names = [e["event"] for e in trace]
    assert names.index("REMOTE_EXECUTION_COMPLETE") < names.index("RESULT_TX_START")
    assert names.index("RESULT_TX_START") < names.index("OFFLOAD_RETURNED")
    assert task.state == TaskState.COMPLETED
    assert task.finish_time_ms >= next(
        e["timestamp_ms"] for e in trace if e["event"] == "REMOTE_EXECUTION_COMPLETE"
    )


def test_miss_ratio_uses_all_released_jobs_and_jitter_is_per_task():
    sim = DiscreteEventSimulator(PredictiveRuntimeConfig(), seed=1, fleet_size=1)
    first = TaskInstance.from_profile(
        DEFAULT_TASK_PROFILES["Perception"], "first", "Device_1", 0.0
    )
    second = TaskInstance.from_profile(
        DEFAULT_TASK_PROFILES["Perception"], "second", "Device_1", 0.0
    )
    third = TaskInstance.from_profile(
        DEFAULT_TASK_PROFILES["Perception"], "third", "Device_1", 0.0
    )
    first.finish_time_ms = first.deadline_ms
    first.state = TaskState.COMPLETED
    second.deadline_ms = 100.0
    third.finish_time_ms = first.deadline_ms
    third.state = TaskState.DEADLINE_MISSED
    sim.all_tasks.extend((first, second, third))
    sim.current_time_ms = first.deadline_ms
    metrics = sim.compute_metrics()
    assert metrics["total_released_tasks"] == 3
    assert metrics["censored_task_count"] == 1
    assert metrics["deadline_miss_ratio"] == 0.3333
    assert metrics["jitter_ms"] == 0.0


def test_dropped_request_triggers_watchdog_local_fallback():
    sim = DiscreteEventSimulator(PredictiveRuntimeConfig(), seed=7, fleet_size=2)
    scheduler = PredictiveRuntimeScheduler(enable_gnn=False, enable_federated=False)
    sim.attach_scheduler(scheduler)
    task = TaskInstance.from_profile(
        DEFAULT_TASK_PROFILES["Perception"], "drop-1", "Device_1", 0.0
    )
    task.deadline_ms = 100.0
    sim.all_tasks.append(task)
    origin = sim.devices["Device_1"]
    origin.resources.injected_network_drop_prob = 1.0
    origin.record_offload_dispatch(task, "Device_2", 0.0, 20.0)
    sim.schedule_offload_request(task, "Device_2")
    check_at = origin.offloaded_tasks[task.instance_id]["request_arrival_ms"] + 1.0
    sim.events.push(check_at, EventType.OFFLOAD_PROGRESS_CHECK, "Device_1", task,
                    {"task_id": task.instance_id, "target_id": "Device_2"})
    sim.run(duration_ms=check_at + 1.0)

    assert origin.offloaded_tasks[task.instance_id]["status"] == "ABORTED"
    assert task.is_degraded
    assert scheduler.fallbacks_invoked == 1
    assert any(event["event_type"] == "PACKET_DROP" for event in sim.canonical_events)


@pytest.mark.parametrize("scheduler", [
    AlwaysOffloadScheduler(), PredictiveNoFallbackScheduler(risk_threshold=0.0)
])
def test_baseline_offload_does_not_schedule_predicted_result(scheduler):
    sim = DiscreteEventSimulator(PredictiveRuntimeConfig(), seed=2, fleet_size=2)
    sim.attach_scheduler(scheduler)
    task = TaskInstance.from_profile(
        DEFAULT_TASK_PROFILES["Perception"], "baseline-remote", "Device_1", 0.0
    )
    sim.devices["Device_1"].admit_task(task)
    scheduler.schedule_device(sim.devices["Device_1"], 0.0)
    assert task.offload_target_id == "Device_2"
    assert all(event.event_type != EventType.OFFLOAD_RETURN for event in sim.events._heap)


def test_deadline_events_match_terminal_task_state_and_artifact_metrics(tmp_path):
    sim = create_bursty_scenario(seed=42, fleet_size=3, duration_ms=300)
    sim.run_id = "deadline-reconciliation"
    sim.attach_scheduler(PredictiveRuntimeScheduler())
    metrics = sim.run(300)
    missed_ids = {event["task_id"] for event in sim.canonical_events
                  if event["event_type"] == "DEADLINE"}
    state_missed = {task.instance_id for task in sim.all_tasks
                    if task.state == TaskState.DEADLINE_MISSED}
    assert missed_ids == state_missed
    for device in sim.devices.values():
        assert not any(task.instance_id in missed_ids for task in
                       device.ready_queue + device.running_tasks + device.remotely_hosted_tasks)

    event_path = tmp_path / "events.jsonl"
    with CanonicalEventWriter(event_path, sim.run_id) as writer:
        for event in sim.canonical_events:
            writer.write(event)
    reduced = reduce_event_stream(event_path)
    assert reduced["released"] == metrics["total_released_tasks"]
    assert reduced["missed"] == metrics["deadline_missed_count"]

