"""
Unit and integration tests for GhostGuard continuous live simulation engine.
Validates session initialization, discrete stepping, on-the-fly fault injection,
and physical node metadata.
"""

import pytest
from ghostguard.api.server import (
    live_start,
    live_step,
    live_inject_fault,
    live_reset,
    LiveStartRequest,
    LiveStepRequest,
    LiveFaultRequest,
)


def test_live_simulation_start():
    """Verify live continuous simulation session initialization."""
    req = LiveStartRequest(
        fleet_size=4,
        seed=42,
        horizon_ms=2000.0,
        enable_contention=True,
        fault_time_ms=25.0,
        contention_magnitude=0.90,
        target_node="Device_1",
    )
    snapshot = live_start(req)
    assert snapshot["current_time_ms"] == 0.0
    assert snapshot["fleet_size"] == 4
    assert "nodes" in snapshot
    assert len(snapshot["nodes"]) == 4

    # Verify physical node metadata
    dev1 = snapshot["nodes"]["Device_1"]
    assert dev1["node_type"] == "drone"
    assert "Drone" in dev1["name"]

    dev2 = snapshot["nodes"]["Device_2"]
    assert dev2["node_type"] == "server"
    assert "Server" in dev2["name"]

    dev3 = snapshot["nodes"]["Device_3"]
    assert dev3["node_type"] == "rover"
    assert "Rover" in dev3["name"]

    dev4 = snapshot["nodes"]["Device_4"]
    assert dev4["node_type"] == "arm"
    assert "Arm" in dev4["name"]

    # Verify metrics structures
    assert "metrics_gg" in snapshot
    assert "metrics_edf" in snapshot
    assert snapshot["metrics_gg"]["missed"] == 0


def test_live_simulation_step():
    """Verify monotonic time progression and metric updates during stepping."""
    live_start(LiveStartRequest(fleet_size=4, seed=42))

    step1 = live_step(LiveStepRequest(delta_ms=20.0))
    assert step1["current_time_ms"] == 20.0
    assert "nodes" in step1
    assert "metrics_gg" in step1
    assert "metrics_edf" in step1

    step2 = live_step(LiveStepRequest(delta_ms=30.0))
    assert step2["current_time_ms"] == 50.0
    assert step2["current_time_ms"] > step1["current_time_ms"]


def test_live_simulation_fault_injection():
    """Verify dynamic on-the-fly fault injection at current live simulation clock."""
    live_start(LiveStartRequest(fleet_size=4, seed=42))
    live_step(LiveStepRequest(delta_ms=10.0))

    fault_res = live_inject_fault(LiveFaultRequest(
        target_node="Device_3",
        cpu_load=0.95,
        gpu_load=0.95,
        duration_ms=150.0,
        network_delay_ms=20.0,
    ))
    assert fault_res["status"] == "injected"
    assert fault_res["target_node"] == "Device_3"
    assert fault_res["cpu_load"] == 0.95

    # Step through the injected burst
    step_after = live_step(LiveStepRequest(delta_ms=20.0))
    dev3 = step_after["nodes"]["Device_3"]
    assert dev3["cpu"] > 80.0 or dev3["gpu"] > 80.0


def test_live_simulation_reset():
    """Verify simulation resets back to t=0.0 ms."""
    live_start(LiveStartRequest(fleet_size=4, seed=42))
    live_step(LiveStepRequest(delta_ms=40.0))

    reset_snap = live_reset(LiveStartRequest(fleet_size=4, seed=42))
    assert reset_snap["current_time_ms"] == 0.0
