from rts_predictive.dashboard.live_projection import live_statistics, resource_dependency_graph
from rts_predictive.api.server import LiveSimulationSession


def event(kind, task, **payload):
    return {"event_type": kind, "task_id": task, "payload": payload}


def test_live_outcomes_exclude_pending_and_deduplicate_late_commits():
    events = [event("TASK_READY", "pending"), event("TASK_READY", "late", is_critical=True),
              event("DEADLINE", "late"), event("TASK_COMMIT", "late", deadline_met=False,
              response_time_ms=12), event("TASK_COMMIT", "ok", deadline_met=True,
              response_time_ms=4, output_utility=.8)]
    result = live_statistics(events)
    assert result["evaluated"] == 2
    assert result["missed"] == result["critical_misses"] == 1
    assert result["completed"] == result["pending"] == 1
    assert result["dmr_pct"] == 50
    assert result["wcrt_ms"] == 12
    assert result["avg_utility"] == .8


def test_undefined_live_values_are_unavailable():
    result = live_statistics([event("TASK_READY", "pending")])
    assert result["dmr_pct"] is None
    assert result["avg_utility"] is None
    assert result["wcrt_ms"] is None


def test_window_can_identify_critical_miss_without_retained_release():
    result = live_statistics([event("DEADLINE", "task", task_name="Sense")], {"Sense"})
    assert result["critical_misses"] == 1


def test_resource_edges_match_admitted_work_and_effective_setting():
    session = LiveSimulationSession(fleet_size=2, horizon_ms=120, risk_threshold=.42)
    snapshot = session.step(10)
    assert snapshot["model_status"]["predictor"] == "gnn"
    assert snapshot["model_status"]["risk_threshold"] == .42
    assert snapshot["model_status"]["inferences"] > 0
    graph = resource_dependency_graph(session.sim_gg)
    tasks = {task["id"]: task for task in graph["tasks"]}
    resources = {resource["id"] for resource in graph["resources"]}
    assert len(resources) == 4
    assert set(tasks) == {task.instance_id for device in session.sim_gg.devices.values()
                          for task in device.running_tasks + device.ready_queue}
    assert graph["edges"]
    for edge in graph["edges"]:
        assert edge["source"] in tasks and edge["target"] in resources
        assert edge["kind"] == ("allocation" if tasks[edge["source"]]["state"] == "RUNNING" else "demand")
        assert 0 < edge["demand_fraction"] <= 1
    assert snapshot["pipeline"]["stages"][0]["nominal_work_ms"] == 3


def test_pruning_drops_failed_jobs_and_baseline_logs():
    session = LiveSimulationSession(fleet_size=2, horizon_ms=120)
    session.step(100)
    session.retention_window_ms = 5
    session._prune_history()
    assert not session.sim_edf.telemetry_log
    for job in session.sim_gg.pipeline_jobs.values():
        assert job["release_time_ms"] >= 95 or any(task.state.value in {
            "RELEASED", "READY", "RUNNING", "OFFLOADED", "FALLBACK_ACTIVE"
        } for task in job["tasks"].values())


def test_snapshot_streams_canonical_events_once_across_pruning():
    session = LiveSimulationSession(fleet_size=2, horizon_ms=120)
    first = session.step(10)["step_canonical_events"]
    assert first and all("schema_version" in e and "timestamp_us" in e for e in first)
    assert session.get_snapshot()["step_canonical_events"] == []
    session.retention_window_ms = 5
    session._prune_history()
    second = session.step(10)["step_canonical_events"]
    assert second
    assert min(e["sequence"] for e in second) > max(e["sequence"] for e in first)
