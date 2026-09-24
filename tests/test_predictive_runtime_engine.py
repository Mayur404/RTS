"""
Unit and Edge-Case tests for PredictiveRuntime Three-Way Predictive Arbitration Engine.
"""

import pytest
from rts_predictive.config import DEFAULT_TASK_PROFILES, HARDWARE_PROFILES, PredictiveRuntimeConfig
from rts_predictive.simulator.device import DeviceNode
from rts_predictive.simulator.tasks import TaskInstance, TaskState
from rts_predictive.simulator.events import SimulationEvent, EventType
from rts_predictive.simulator.engine import DiscreteEventSimulator
from rts_predictive.schedulers.predictive_runtime import PredictiveRuntimeScheduler


def test_three_way_arbitration_hierarchy():
    hw = HARDWARE_PROFILES["Drone-Standard"]
    dev_a = DeviceNode("Device_A", hw)
    dev_b = DeviceNode("Device_B", hw)
    dev_a.add_neighbor("Device_B", distance_m=10.0, reliability=0.95)

    sim = DiscreteEventSimulator(fleet_size=2, custom_devices=[dev_a, dev_b])
    sched = PredictiveRuntimeScheduler(risk_threshold=0.60, safety_margin_ms=3.0)
    sim.attach_scheduler(sched)

    # 1. Low risk task -> Local execution
    t_normal = TaskInstance.from_profile(DEFAULT_TASK_PROFILES["Sense"], "sense1", "Device_A", 0.0)
    dev_a.admit_task(t_normal)
    sched.schedule_device(dev_a, 0.0)
    assert t_normal in dev_a.running_tasks
    assert t_normal.state == TaskState.RUNNING

    # 2. Critical task under high injected load -> Evaluates candidate and OFFLOADS
    dev_a.resources.inject_stress(cpu_load=0.90, gpu_load=0.95)
    t_crit = TaskInstance.from_profile(DEFAULT_TASK_PROFILES["Perception"], "perc1", "Device_A", 1.0)
    dev_a.admit_task(t_crit)
    sched.schedule_device(dev_a, 1.0)
    assert t_crit.state == TaskState.OFFLOADED
    assert t_crit.offload_target_id == "Device_B"
    decisions = [
        event for event in sim.canonical_events
        if event["event_type"] == "RUNTIME_DECISION"
        and event["task_id"] == t_crit.instance_id
    ]
    assert decisions[-1]["payload"]["action"] == "OFFLOAD"
    assert decisions[-1]["payload"]["target_id"] == "Device_B"
    assert decisions[-1]["payload"]["candidate_evaluations"]


def test_edge_case_no_neighbors():
    """Edge Case: Node has zero reachable neighbors under high risk -> Local Fallback."""
    hw = HARDWARE_PROFILES["Drone-Standard"]
    dev_alone = DeviceNode("Isolated_Dev", hw)
    sim = DiscreteEventSimulator(fleet_size=1, custom_devices=[dev_alone])
    sched = PredictiveRuntimeScheduler(risk_threshold=0.60)
    sim.attach_scheduler(sched)

    dev_alone.resources.inject_stress(gpu_load=0.95)
    task = TaskInstance.from_profile(DEFAULT_TASK_PROFILES["Perception"], "p1", "Isolated_Dev", 0.0)
    dev_alone.admit_task(task)

    sched.schedule_device(dev_alone, 0.0)
    assert task.is_degraded
    assert task.state == TaskState.RUNNING or task.state == TaskState.READY


def test_edge_case_all_neighbors_overloaded():
    """Edge Case: Candidate neighbors are heavily overloaded -> Local Fallback."""
    hw = HARDWARE_PROFILES["Drone-Standard"]
    dev_a = DeviceNode("DevA", hw)
    dev_b = DeviceNode("DevB", hw)
    dev_a.add_neighbor("DevB", distance_m=10.0, reliability=0.95)

    # Overload neighbor B
    dev_b.resources.inject_stress(gpu_load=0.95, cpu_load=0.95)

    sim = DiscreteEventSimulator(fleet_size=2, custom_devices=[dev_a, dev_b])
    sched = PredictiveRuntimeScheduler(risk_threshold=0.60)
    sim.attach_scheduler(sched)

    dev_a.resources.inject_stress(gpu_load=0.95)
    task = TaskInstance.from_profile(DEFAULT_TASK_PROFILES["Perception"], "p1", "DevA", 0.0)
    dev_a.admit_task(task)

    sched.schedule_device(dev_a, 0.0)
    # Should not offload to overloaded neighbor, but degrade locally
    assert task.is_degraded
    assert task.offload_target_id is None


def test_active_monitoring_aborts_degraded_offload():
    """Active monitor detects degraded remote target and triggers fallback."""
    hw = HARDWARE_PROFILES["Drone-Standard"]
    dev_a = DeviceNode("DevA", hw)
    dev_b = DeviceNode("DevB", hw)
    dev_a.add_neighbor("DevB", distance_m=10.0, reliability=0.95)

    sim = DiscreteEventSimulator(fleet_size=2, custom_devices=[dev_a, dev_b])
    sched = PredictiveRuntimeScheduler(risk_threshold=0.60)
    sim.attach_scheduler(sched)

    task = TaskInstance.from_profile(DEFAULT_TASK_PROFILES["Perception"], "p1", "DevA", 0.0)
    dev_a.record_offload_dispatch(task, "DevB", 0.0, 20.0)

    # Simulate neighbor degradation
    dev_b.resources.inject_stress(gpu_load=0.95)

    # Trigger heartbeat progress check
    ev = SimulationEvent(
        timestamp_ms=10.0,
        sequence_id=1,
        event_type=EventType.OFFLOAD_PROGRESS_CHECK,
        device_id="DevA",
        task=task,
        payload={"task_id": "p1", "target_id": "DevB"}
    )
    sched.on_event(sim, ev)

    # Task should be aborted and recovered by local degraded fallback
    assert task.is_degraded
    assert sched.aborted_offloads_recovered_by_fallback == 1
    # The abandoned remote copy must be removed completely; otherwise it could
    # execute again after the origin begins its local fallback.
    assert task not in dev_b.ready_queue
    assert task not in dev_b.running_tasks
    assert task not in dev_b.remotely_hosted_tasks
