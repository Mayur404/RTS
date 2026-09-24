"""
Test suite for dashboard timeline tracer, publication plots, and paper artifacts.
Ensures all research outputs exist, are syntactically valid, and maintain strict RTS invariants.
"""

import os
import json
import pytest
from rts_predictive.dashboard.timeline_tracer import run_traced_simulation
from scripts.generate_paper_artifacts import generate_paper_artifacts


def test_timeline_tracer():
    """Verify that the simulation timeline tracer generates valid millisecond frames."""
    res = run_traced_simulation(duration_ms=60.0)
    assert "frames" in res
    assert "metrics_gg" in res
    assert "metrics_edf" in res

    frames = res["frames"]
    assert len(frames) == 61  # 0 to 60 ms inclusive

    # Frames are reduced from canonical events and do not invent resource samples.
    f0 = frames[0]
    assert f0["evidence"] == "SIMULATED"
    assert f0["stage_id"] is None
    assert f0["dev1"]["cpu"] is None
    assert any(frame["active_offload"] is not None for frame in frames)

    # Observed misses remain visible even if a policy performs worse in this run.
    assert res["metrics_gg"]["deadline_missed_count"] >= res["metrics_gg"]["critical_misses"]
    assert (
        res["metrics_gg"]["completed_tasks"]
        + res["metrics_gg"]["deadline_missed_count"]
        == res["metrics_gg"]["eligible_task_count"]
    )


def test_paper_artifacts_generation(tmp_path):
    """Every publication value must agree with its raw run event stream."""
    test_paper_dir = str(tmp_path / "paper")
    test_plots_dir = str(tmp_path / "plots")
    index = generate_paper_artifacts(
        output_dir=test_paper_dir,
        plots_dir=test_plots_dir,
    )
    from hashlib import sha256
    from scripts.generate_paper_artifacts import reduce_event_stream

    assert len(index["runs"]) == 3
    for run in index["runs"]:
        manifest = json.load(open(run["manifest"], encoding="utf-8"))
        event_path = manifest["event_file"]
        assert manifest["schema_version"] == "rts_predictive.run-manifest/1.0"
        assert sha256(open(event_path, "rb").read()).hexdigest() == manifest["event_sha256"]
        assert reduce_event_stream(event_path) == run["metrics"]
    assert all(os.path.getsize(path) > 1000 for path in index["figures"])
    assert r"\begin{table}" in open(index["table"], encoding="utf-8").read()


def test_dashboard_components():
    """Verify that dynamic scenario simulation and visual components render valid outputs."""
    from rts_predictive.dashboard.timeline_tracer import run_dynamic_scenario
    from rts_predictive.dashboard.components import (
        render_mesh_topology_svg,
        render_slack_inspector,
        create_synchronized_gantt_chart
    )

    res = run_dynamic_scenario(
        fault_time_ms=25.0,
        contention_magnitude=0.95,
        channel_jitter_ms=5.0,
        target_node="Node 1 (Jetson Orin Nano)",
        duration_ms=60.0
    )

    assert "frames" in res
    assert "tasks_gg" in res
    assert "tasks_edf" in res
    assert res["evidence"] == "SIMULATED"
    assert res["metrics_gg"]["deadline_missed_count"] >= res["metrics_gg"]["critical_misses"]
    assert len(res["tasks_gg"]) > 0

    frame = res["frames"][30]
    svg = render_mesh_topology_svg(frame, enable_animations=True)
    assert "<svg" in svg
    assert "</svg>" in svg
    assert "Node 1:" in svg
    assert "Node 2:" in svg

    slack_html = render_slack_inspector(frame, 30.0)
    assert "Canonical Event Inspection" in slack_html
    assert "Slack is unavailable" in slack_html

    fig = create_synchronized_gantt_chart(res["tasks_gg"], res["tasks_edf"], 30.0, 60.0)
    assert len(fig.data) > 0
