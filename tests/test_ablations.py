"""
Unit and integration tests for GhostGuard ablation study runner
and component graph assertions.
"""

import pytest
from ghostguard.experiments.ablations import (
    ABLATION_REGISTRY,
    AblationConfig,
    instantiate_ablation_scheduler,
    assert_ablation_component_graph,
    AblationRunner,
)


def test_all_ablation_configurations_assert_correctly():
    """Verify that every named ablation alters the intended component graph."""
    assert len(ABLATION_REGISTRY) == 7
    for name, config in ABLATION_REGISTRY.items():
        sched = instantiate_ablation_scheduler(config)
        assert_ablation_component_graph(sched, name)


def test_ablation_scheduler_component_substitutions():
    """Verify specific ablation flags create exact component substitutions."""
    # 1. w/o GNN replaces GNN with analytical heuristic
    sched_no_gnn = instantiate_ablation_scheduler(ABLATION_REGISTRY["w/o GNN"])
    assert sched_no_gnn.gnn_predictor is None
    assert sched_no_gnn.predictor_type == "heuristic"

    # 2. w/o Federated Learning replaces FL estimator with static spec
    sched_no_fl = instantiate_ablation_scheduler(ABLATION_REGISTRY["w/o Federated Learning"])
    assert sched_no_fl.federated_model is None
    assert sched_no_fl.estimator_type == "static_spec"

    # 3. w/o Offloading disables offloading
    sched_no_offload = instantiate_ablation_scheduler(ABLATION_REGISTRY["w/o Offloading"])
    assert sched_no_offload.enable_offload is False

    # 4. w/o Fallback disables fallback activation
    sched_no_fallback = instantiate_ablation_scheduler(ABLATION_REGISTRY["w/o Fallback"])
    assert sched_no_fallback.enable_fallback is False

    # 5. w/o Neighbor Reliability sets threshold to 0.0
    sched_no_rel = instantiate_ablation_scheduler(ABLATION_REGISTRY["w/o Neighbor Reliability"])
    assert sched_no_rel.reliability_threshold == 0.0

    # 6. w/o Watchdog disables active in-flight monitoring
    sched_no_watchdog = instantiate_ablation_scheduler(ABLATION_REGISTRY["w/o Watchdog"])
    assert sched_no_watchdog.enable_watchdog is False


def test_ablation_runner_mini_suite(tmp_path):
    """Run a small ablation execution and verify structured metrics output."""
    runner = AblationRunner(output_dir=str(tmp_path))
    summary = runner.run_ablations(
        seeds=[42],
        duration_ms=50.0,
        configs=["Full-GhostGuard", "w/o GNN", "w/o Offloading"],
    )

    assert "Full-GhostGuard" in summary
    assert "w/o GNN" in summary
    assert "w/o Offloading" in summary

    for name, metrics in summary.items():
        assert "deadline_miss_ratio" in metrics
        assert "critical_misses" in metrics
        assert "avg_response_time_ms" in metrics
        assert "avg_utility" in metrics
