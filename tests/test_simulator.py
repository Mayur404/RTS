"""
Unit tests for the Real-Time Systems Simulator engine, tasks, and resources.
"""

import pytest
from ghostguard.config import DEFAULT_TASK_PROFILES, HARDWARE_PROFILES, GhostGuardConfig
from ghostguard.simulator.tasks import TaskInstance, TaskState
from ghostguard.simulator.resources import ResourceManager
from ghostguard.simulator.engine import DiscreteEventSimulator
from ghostguard.schedulers.local_fifo import LocalFIFOScheduler


def test_task_deadline_and_response_time():
    prof = DEFAULT_TASK_PROFILES["Perception"]
    task = TaskInstance.from_profile(
        profile=prof,
        instance_id="t1",
        device_id="Dev1",
        release_time_ms=10.0,
        jitter_ms=0.0
    )

    assert task.deadline_ms == 10.0 + prof.deadline_ms
    assert task.slack_ms(10.0) == prof.deadline_ms - prof.wcet_ms
    assert task.response_time_ms is None

    # Simulate completion
    task.finish_time_ms = 35.0
    assert task.response_time_ms == 25.0
    assert task.lateness_ms == 35.0 - (10.0 + prof.deadline_ms)
    assert task.deadline_met is True


def test_resource_manager_contention_and_thermal():
    hw = HARDWARE_PROFILES["Drone-Standard"]
    rm = ResourceManager(hw, ambient_temp_c=30.0)

    # Initial state
    assert rm.get_thermal_throttling_factor() == 1.0
    nom_speed = rm.calculate_effective_speed(requires_gpu=False)
    assert nom_speed == hw.cpu_speed_multiplier

    # Inject contention
    rm.inject_stress(cpu_load=1.5, gpu_load=1.5)
    slow_speed = rm.calculate_effective_speed(requires_gpu=False)
    assert slow_speed < nom_speed

    # Thermal heating
    for _ in range(50):
        rm.update_thermal_state(delta_time_ms=50.0)
    assert rm.temperature_c > 30.0


def test_deterministic_simulation_repeatability():
    """Confirms that two runs with the exact same seed produce 100% identical outcomes."""
    config = GhostGuardConfig(simulation_duration_ms=200.0)

    sim1 = DiscreteEventSimulator(config=config, seed=42, fleet_size=4)
    sim1.schedule_periodic_tasks(duration_ms=200.0)
    sim1.attach_scheduler(LocalFIFOScheduler())
    m1 = sim1.run(duration_ms=200.0)

    sim2 = DiscreteEventSimulator(config=config, seed=42, fleet_size=4)
    sim2.schedule_periodic_tasks(duration_ms=200.0)
    sim2.attach_scheduler(LocalFIFOScheduler())
    m2 = sim2.run(duration_ms=200.0)

    assert m1["deadline_met_count"] == m2["deadline_met_count"]
    assert m1["deadline_missed_count"] == m2["deadline_missed_count"]
    assert m1["avg_response_time_ms"] == m2["avg_response_time_ms"]
    assert len(sim1.telemetry_log) == len(sim2.telemetry_log)
