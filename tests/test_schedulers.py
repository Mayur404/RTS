"""
Unit tests for Real-Time Fleet Baseline Schedulers.
"""

import pytest
from rts_predictive.config import DEFAULT_TASK_PROFILES, HARDWARE_PROFILES
from rts_predictive.simulator.device import DeviceNode
from rts_predictive.simulator.tasks import TaskInstance
from rts_predictive.schedulers.local_fifo import LocalFIFOScheduler
from rts_predictive.schedulers.edf import EDFScheduler
from rts_predictive.schedulers.rm import RMScheduler
from rts_predictive.schedulers.reactive_fallback import ReactiveFallbackScheduler
from rts_predictive.schedulers.always_offload import AlwaysOffloadScheduler
from rts_predictive.simulator.engine import DiscreteEventSimulator


def test_edf_ordering():
    hw = HARDWARE_PROFILES["Drone-Standard"]
    dev = DeviceNode("Dev1", hw)

    # Add task with late deadline
    t_late = TaskInstance.from_profile(DEFAULT_TASK_PROFILES["Tracking"], "t_late", "Dev1", 0.0)
    # Add task with early deadline
    t_early = TaskInstance.from_profile(DEFAULT_TASK_PROFILES["ObstacleDetection"], "t_early", "Dev1", 0.0)

    dev.admit_task(t_late)
    dev.admit_task(t_early)

    sched = EDFScheduler()
    ordered = sched.order_ready_queue(dev, 0.0)
    assert ordered[0].instance_id == "t_early"
    assert ordered[1].instance_id == "t_late"


def test_rm_ordering():
    hw = HARDWARE_PROFILES["Drone-Standard"]
    dev = DeviceNode("Dev1", hw)

    # Sense (period 20ms), Perception (period 33ms), Tracking (period 50ms)
    t_track = TaskInstance.from_profile(DEFAULT_TASK_PROFILES["Tracking"], "track", "Dev1", 0.0)
    t_sense = TaskInstance.from_profile(DEFAULT_TASK_PROFILES["Sense"], "sense", "Dev1", 0.0)

    dev.admit_task(t_track)
    dev.admit_task(t_sense)

    sched = RMScheduler()
    ordered = sched.order_ready_queue(dev, 0.0)
    assert ordered[0].instance_id == "sense"
    assert ordered[1].instance_id == "track"


def test_reactive_fallback_trigger():
    hw = HARDWARE_PROFILES["Drone-Standard"]
    dev = DeviceNode("Dev1", hw)
    t = TaskInstance.from_profile(DEFAULT_TASK_PROFILES["Perception"], "p1", "Dev1", 0.0)
    dev.admit_task(t)

    sched = ReactiveFallbackScheduler(stress_threshold=0.8)

    # Under low stress, does not degrade
    sched.order_ready_queue(dev, 0.0)
    assert not t.is_degraded

    # Under injected stress, degrades task
    dev.resources.inject_stress(cpu_load=0.9)
    sched.order_ready_queue(dev, 5.0)
    assert t.is_degraded
    assert t.remaining_work_ms == t.degraded_wcet_ms


def test_always_offload_does_not_reoffload_a_remote_task():
    sim = DiscreteEventSimulator(seed=5, fleet_size=2)
    scheduler = AlwaysOffloadScheduler()
    sim.attach_scheduler(scheduler)

    remote_host = sim.devices["Device_2"]
    task = TaskInstance.from_profile(
        DEFAULT_TASK_PROFILES["Perception"],
        "remote-p1",
        "Device_1",
        0.0,
    )
    task.is_remote_execution = True
    remote_host.admit_task(task)

    scheduler.schedule_device(remote_host, 5.0)

    assert remote_host.total_offloads == 0
    assert task.offload_target_id is None
