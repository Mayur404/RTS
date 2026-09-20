"""
Deterministic Experiment and Demonstration Scenario Generators.
Configures multi-device fleets, task release timelines, and injected contention events.
"""

from typing import Tuple, Dict, Any
from ghostguard.config import GhostGuardConfig
from ghostguard.simulator.engine import DiscreteEventSimulator
from ghostguard.simulator.events import EventType


def create_nominal_scenario(seed: int = 42, fleet_size: int = 6, duration_ms: float = 600.0) -> DiscreteEventSimulator:
    """Nominal scenario with baseline tasks and zero injected faults."""
    config = GhostGuardConfig(simulation_duration_ms=duration_ms)
    sim = DiscreteEventSimulator(config=config, seed=seed, fleet_size=fleet_size)
    sim.schedule_periodic_tasks(duration_ms=duration_ms)
    return sim


def create_bursty_scenario(seed: int = 42, fleet_size: int = 6, duration_ms: float = 600.0) -> DiscreteEventSimulator:
    """Scenario with injected bursty CPU and GPU contention spikes."""
    sim = create_nominal_scenario(seed=seed, fleet_size=fleet_size, duration_ms=duration_ms)
    # Inject contention on Device_1 at 100ms
    sim.schedule_contention_burst(
        target_device_id="Device_1",
        start_time_ms=80.0,
        duration_ms=180.0,
        cpu_load=0.85,
        gpu_load=0.95
    )
    # Inject contention on Device_3 at 250ms
    sim.schedule_contention_burst(
        target_device_id="Device_3",
        start_time_ms=250.0,
        duration_ms=150.0,
        cpu_load=0.90,
        gpu_load=0.80
    )
    return sim


def create_thermal_scenario(seed: int = 42, fleet_size: int = 6, duration_ms: float = 800.0) -> DiscreteEventSimulator:
    """Scenario with prolonged contention driving temperatures above throttling threshold."""
    sim = create_nominal_scenario(seed=seed, fleet_size=fleet_size, duration_ms=duration_ms)
    sim.schedule_contention_burst(
        target_device_id="Device_2",
        start_time_ms=50.0,
        duration_ms=450.0,
        cpu_load=0.95,
        gpu_load=0.95
    )
    return sim


def create_unreliable_neighbor_scenario(seed: int = 42, fleet_size: int = 6, duration_ms: float = 600.0) -> DiscreteEventSimulator:
    """Scenario where a key neighbor drops packets and degrades communication link."""
    sim = create_bursty_scenario(seed=seed, fleet_size=fleet_size, duration_ms=duration_ms)
    # Degrade Device_2 at 120ms
    sim.events.push(
        timestamp_ms=120.0,
        event_type=EventType.NEIGHBOR_DEGRADE,
        device_id="Device_1",
        payload={"target_id": "Device_2"}
    )
    return sim


def create_deterministic_failure_demo_scenario(seed: int = 42) -> DiscreteEventSimulator:
    """
    CRITICAL DEMO SCENARIO (Section 12 of specification):
    1. Device A (Device_1) becomes overloaded at t = 30ms.
    2. GhostGuard predicts deadline risk on critical Perception task.
    3. Device B (Device_2) is selected as a candidate neighbor.
    4. Task is dispatched to Device B.
    5. At t = 45ms, Device B is hit with sudden massive contention burst.
    6. GhostGuard active monitor at t = 50ms detects that Device B is degraded.
    7. GhostGuard abandons remote execution and immediately activates local verified fallback.
    8. Critical deadline (t = 63ms) is met!
    """
    duration_ms = 250.0
    config = GhostGuardConfig(simulation_duration_ms=duration_ms)
    sim = DiscreteEventSimulator(config=config, seed=seed, fleet_size=2)
    sim.schedule_periodic_tasks(duration_ms=duration_ms)

    # 1. Device 1 gets hit with heavy overload at 25ms
    sim.schedule_contention_burst(
        target_device_id="Device_1",
        start_time_ms=25.0,
        duration_ms=100.0,
        cpu_load=0.90,
        gpu_load=0.95,
        network_delay_ms=0.0
    )

    # 2. Device 2 (the neighbor) suddenly gets hit with contention burst at 45ms
    sim.schedule_contention_burst(
        target_device_id="Device_2",
        start_time_ms=45.0,
        duration_ms=90.0,
        cpu_load=0.98,
        gpu_load=0.99,
        network_delay_ms=25.0
    )

    return sim
