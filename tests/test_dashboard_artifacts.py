"""
Test suite for dashboard timeline tracer, publication plots, and paper artifacts.
Ensures all research outputs exist, are syntactically valid, and maintain strict RTS invariants.
"""

import os
import json
import pytest
from ghostguard.dashboard.timeline_tracer import run_traced_simulation
from scripts.generate_paper_artifacts import generate_paper_artifacts


def test_timeline_tracer():
    """Verify that the simulation timeline tracer generates valid millisecond frames."""
    res = run_traced_simulation(duration_ms=60.0)
    assert "frames" in res
    assert "metrics_gg" in res
    assert "metrics_edf" in res

    frames = res["frames"]
    assert len(frames) == 61  # 0 to 60 ms inclusive

    # Verify stage progression
    f0 = frames[0]
    assert f0["stage_id"] == 1
    assert f0["dev1"]["cpu"] < 50.0

    f26 = frames[26]
    assert f26["stage_id"] == 2
    assert f26["dev1"]["cpu"] > 80.0

    f35 = frames[35]
    assert f35["stage_id"] == 3
    assert f35["active_offload"] is not None

    f46 = frames[46]
    assert f46["stage_id"] == 4
    assert f46["dev2"]["cpu"] > 90.0

    f50 = frames[50]
    assert f50["stage_id"] == 5

    f55 = frames[55]
    assert f55["stage_id"] == 6

    # The scripted trace currently preserves its critical task, but non-critical
    # misses must remain visible instead of being relabelled as completions.
    assert res["metrics_gg"]["critical_misses"] == 0
    assert res["metrics_gg"]["deadline_missed_count"] >= res["metrics_gg"]["critical_misses"]
    assert (
        res["metrics_gg"]["completed_tasks"]
        + res["metrics_gg"]["deadline_missed_count"]
        == res["metrics_gg"]["eligible_task_count"]
    )


def test_paper_artifacts_generation(tmp_path):
    """Verify that the legacy demonstration generator writes isolated outputs."""
    test_paper_dir = str(tmp_path / "paper")
    test_plots_dir = str(tmp_path / "plots")
    generate_paper_artifacts(
        output_dir=test_paper_dir,
        plots_dir=test_plots_dir,
    )

    # 1. Check Plots
    for fig_name in ["fig1_timeline_trace", "fig2_dmr_comparison", "fig3_latency_cdf", "fig4_gnn_overhead"]:
        png_f = os.path.join(test_plots_dir, f"{fig_name}.png")
        pdf_f = os.path.join(test_plots_dir, f"{fig_name}.pdf")
        assert os.path.exists(png_f), f"Missing plot {png_f}"
        assert os.path.exists(pdf_f), f"Missing vector plot {pdf_f}"
        assert os.path.getsize(png_f) > 1000

    # 2. Check JSON
    json_path = os.path.join(test_paper_dir, "PAPER_DATA.json")
    assert os.path.exists(json_path)
    with open(json_path, "r") as f:
        data = json.load(f)
    assert "benchmarks" in data
    assert data["benchmarks"]["GhostGuard (Proposed)"]["critical_misses"] == 0
    assert data["benchmarks"]["EDF-Local (Baseline)"]["critical_misses"] == 8

    # 3. Check LaTeX tables
    t1_path = os.path.join(test_paper_dir, "table1_benchmark_summary.tex")
    t2_path = os.path.join(test_paper_dir, "table2_rta_verification.tex")
    assert os.path.exists(t1_path)
    assert os.path.exists(t2_path)

    with open(t1_path, "r") as f:
        t1_content = f.read()
    assert r"\begin{table}" in t1_content
    assert r"\end{table}" in t1_content
    assert "GhostGuard (Proposed)" in t1_content

    with open(t2_path, "r") as f:
        t2_content = f.read()
    assert r"\begin{table}" in t2_content
    assert r"\end{table}" in t2_content
    assert "Perception" in t2_content


def test_dashboard_components():
    """Verify that dynamic scenario simulation and visual components render valid outputs."""
    from ghostguard.dashboard.timeline_tracer import run_dynamic_scenario
    from ghostguard.dashboard.components import (
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
    assert res["metrics_gg"]["critical_misses"] == 0
    assert len(res["tasks_gg"]) > 0

    frame = res["frames"][30]
    svg = render_mesh_topology_svg(frame, enable_animations=True)
    assert "<svg" in svg
    assert "</svg>" in svg
    assert "Node 1: Jetson Orin Nano" in svg
    assert "Node 2: Jetson AGX Orin" in svg

    slack_html = render_slack_inspector(frame, 30.0)
    assert "Real-Time Mathematical Slack Gauge" in slack_html
    assert "PROPOSED: GHOSTGUARD" in slack_html
    assert "BASELINE: LOCAL EDF" in slack_html

    fig = create_synchronized_gantt_chart(res["tasks_gg"], res["tasks_edf"], 30.0, 60.0)
    assert len(fig.data) > 0
