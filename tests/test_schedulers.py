"""
Unit tests for Real-Time Fleet Baseline Schedulers.
"""

import pytest
from ghostguard.config import DEFAULT_TASK_PROFILES, HARDWARE_PROFILES
from ghostguard.simulator.device import DeviceNode
from ghostguard.simulator.tasks import TaskInstance
from ghostguard.schedulers.local_fifo import LocalFIFOScheduler
from ghostguard.schedulers.edf import EDFScheduler
from ghostguard.schedulers.rm import RMScheduler
from ghostguard.schedulers.reactive_fallback import ReactiveFallbackScheduler


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
