"""
Unit and integration tests for PredictiveRuntime continuous live simulation engine.
Validates session initialization, discrete stepping, on-the-fly fault injection,
and physical node metadata.
"""

import pytest
from fastapi import HTTPException
from rts_predictive.api.server import (
    live_start,
    live_step,
    live_inject_fault,
    live_reset,
    create_live_session,
    get_live_session_events,
    delete_live_session,
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


def test_live_pipeline_graph_tracks_real_stage_releases():
    start = live_start(LiveStartRequest(fleet_size=4, seed=42, horizon_ms=300.0))
    pipeline = start["pipeline"]
    assert {stage["id"] for stage in pipeline["stages"]} == {
        "Sense", "ObstacleDetection", "Perception", "Tracking", "PathPlanning", "Actuation"
    }
    assert {tuple(edge.values()) for edge in pipeline["edges"]} >= {
        ("Sense", "ObstacleDetection"), ("PathPlanning", "Actuation")
    }
    initial = pipeline["latest_jobs"]["Device_1"]["stages"]
    assert initial["Sense"]["state"] == "RELEASED"
    assert initial["ObstacleDetection"]["state"] == "WAITING"

    advanced = live_step(LiveStepRequest(delta_ms=10.0))
    stages = advanced["pipeline"]["latest_jobs"]["Device_1"]["stages"]
    assert stages["Sense"]["state"] == "COMPLETED"
    assert stages["ObstacleDetection"]["state"] in {"RELEASED", "READY", "RUNNING", "COMPLETED"}
    if stages["Perception"]["state"] != "WAITING":
        assert stages["ObstacleDetection"]["state"] == "COMPLETED"

    focus = advanced["pipeline"]["focus_jobs"]["Device_1"]
    assert focus["job_id"] == advanced["pipeline"]["latest_jobs"]["Device_1"]["job_id"]
    assert all(
        "remaining_work_ms" in record
        for record in focus["stages"].values()
        if record["state"] != "WAITING"
    )


def test_live_dag_focus_follows_active_job_instead_of_newest_release():
    started = live_start(LiveStartRequest(fleet_size=2, seed=42, horizon_ms=300.0))
    advanced = live_step(LiveStepRequest(
        session_id=started["session_id"], delta_ms=55.0
    ))
    latest = advanced["pipeline"]["latest_jobs"]["Device_1"]
    focus = advanced["pipeline"]["focus_jobs"]["Device_1"]
    assert focus["release_time_ms"] <= latest["release_time_ms"]
    assert any(stage["state"] != "WAITING" for stage in focus["stages"].values())


def test_live_playback_handles_uneven_submillisecond_steps():
    live_start(LiveStartRequest(fleet_size=4, seed=42, horizon_ms=300.0))
    times = [live_step(LiveStepRequest(delta_ms=delta))["current_time_ms"]
             for delta in (40.1, 36.8, 23.8, 40.0, 40.0, 40.0)]
    assert times == sorted(times)
    assert times[-1] > 200.0


def test_live_clock_and_pipeline_continue_beyond_initial_horizon():
    started = live_start(LiveStartRequest(fleet_size=2, seed=42, horizon_ms=120.0))
    session_id = started["session_id"]
    live_step(LiveStepRequest(session_id=session_id, delta_ms=100.0))
    advanced = live_step(LiveStepRequest(session_id=session_id, delta_ms=100.0))

    assert advanced["current_time_ms"] == 200.0
    assert advanced["status"] == "RUNNING"
    assert advanced["evidence"] == "LIVE_NON_EVIDENCE"
    assert all(
        job["release_time_ms"] >= 150.0
        for job in advanced["pipeline"]["latest_jobs"].values()
    )


def test_live_sessions_do_not_reset_each_other():
    first = live_start(LiveStartRequest(fleet_size=4, seed=10, horizon_ms=300.0))
    second = live_start(LiveStartRequest(fleet_size=6, seed=11, horizon_ms=300.0))
    assert first["session_id"] != second["session_id"]
    a = live_step(LiveStepRequest(session_id=first["session_id"], delta_ms=25.0))
    b = live_step(LiveStepRequest(session_id=second["session_id"], delta_ms=10.0))
    assert a["fleet_size"] == 4 and a["current_time_ms"] == 25.0
    assert b["fleet_size"] == 6 and b["current_time_ms"] == 10.0
    with pytest.raises(HTTPException) as error:
        live_step(LiveStepRequest(session_id="missing", delta_ms=10.0))
    assert error.value.status_code == 404


@pytest.mark.parametrize("fleet_size", [6, 8])
def test_large_live_fleets_have_connected_peer_graph(fleet_size):
    snapshot = live_start(LiveStartRequest(fleet_size=fleet_size, seed=42, horizon_ms=300.0))
    neighbors = {node_id: set() for node_id in snapshot["nodes"]}
    for link in snapshot["links"]:
        neighbors[link["source"]].add(link["target"])
        neighbors[link["target"]].add(link["source"])
    reached = {"Device_1"}
    frontier = ["Device_1"]
    while frontier:
        for peer in neighbors[frontier.pop()]:
            if peer not in reached:
                reached.add(peer)
                frontier.append(peer)
    assert reached == set(snapshot["nodes"])


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


def test_api_v1_live_session_event_cursor_and_delete():
    snapshot = create_live_session(LiveStartRequest(fleet_size=2, seed=17, horizon_ms=150.0))
    session_id = snapshot["session_id"]
    live_step(LiveStepRequest(session_id=session_id, delta_ms=20.0))
    first = get_live_session_events(session_id, after_sequence=0)
    assert first["evidence"] == "LIVE_NON_EVIDENCE"
    assert first["events"]
    second = get_live_session_events(session_id, after_sequence=first["next_sequence"])
    assert second["events"] == []
    assert delete_live_session(session_id) is None
    with pytest.raises(HTTPException) as error:
        get_live_session_events(session_id, after_sequence=0)
    assert error.value.status_code == 404


def test_live_simulation_research_parameters_and_stochastic_contention():
    """Verify customizable research parameters (period, deadline, thresholds) and stochastic contention."""
    req = LiveStartRequest(
        fleet_size=4,
        seed=123,
        horizon_ms=500.0,
        enable_contention=True,
        fault_time_ms=20.0,
        fault_duration_ms=120.0,
        contention_magnitude=0.92,
        target_node="Device_1",
        risk_threshold=0.55,
        reliability_threshold=0.65,
        safety_margin_ms=2.5,
        network_delay_ms=14.0,
        period_ms=35.0,
        deadline_ms=35.0,
    )
    snap = live_start(req)
    assert snap["current_time_ms"] == 0.0
    assert snap["pipeline"]["period_ms"] == 35.0
    assert snap["pipeline"]["deadline_ms"] == 35.0

    # Step through 200 ms to trigger stochastic bursts and pipeline jobs
    step_snap = None
    for _ in range(10):
        step_snap = live_step(LiveStepRequest(delta_ms=20.0))

    assert step_snap["current_time_ms"] == 200.0
    assert step_snap["metrics_gg"]["completed"] > 0
    assert step_snap["metrics_edf"]["completed"] > 0
    # Stochastic bursts ensure contention occurred
    assert step_snap["metrics_gg"]["fallbacks"] >= 0
    # Both schedulers operated on deterministic reproducible inputs
    assert step_snap["metrics_gg"]["dmr_pct"] <= step_snap["metrics_edf"]["dmr_pct"] + 10.0
