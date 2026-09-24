"""Checks that small benchmark summaries remain valid research artifacts."""

import json
import pytest

from rts_predictive.experiments.runner import ExperimentRunner


def test_single_pair_has_no_fabricated_variance_and_records_components(tmp_path):
    runner = ExperimentRunner(output_dir=str(tmp_path))
    summary = runner.run_full_suite(
        schedulers=["local_fifo", "rts_predictive"],
        seeds=[42], scenarios=["bursty"], duration_ms=50.0,
    )
    assert summary["num_runs"] == 2
    assert summary["results_by_scheduler"]["rts_predictive"]["deadline_miss_ratio_std"] is None
    json.dumps(summary, allow_nan=False)

    runs = json.loads((tmp_path / "raw_runs" / "benchmark_runs.json").read_text())
    assert len(runs) == 2
    predictive = next(run for run in runs if run["scheduler"] == "rts_predictive")
    manifest = json.loads(open(predictive["manifest"], encoding="utf-8").read())
    assert manifest["components"]["predictor"] == "gnn"
    assert manifest["components"]["model_evidence"] == "SIMULATION_CALIBRATED"
    assert manifest["components"]["remote_estimator"] == "federated"
    assert manifest["components"]["federated_model_evidence"] == "SIMULATION_EVALUATED"
    assert predictive["violations_prevented"] == (
        runs[0]["deadline_missed_count"] - predictive["deadline_missed_count"]
    )


def test_runner_rejects_unknown_scenario_instead_of_mislabeling(tmp_path):
    runner = ExperimentRunner(output_dir=str(tmp_path))
    with pytest.raises(ValueError, match="unknown scenario"):
        runner.run_single_benchmark("local_fifo", "misspelled", duration_ms=10)


def test_explicit_gnn_policy_runs_inference_and_records_weight_identity(tmp_path):
    runner = ExperimentRunner(output_dir=str(tmp_path))
    run = runner.run_single_benchmark(
        "rts_predictive_gnn", scenario_type="bursty", seed=42,
        fleet_size=2, duration_ms=50,
    )
    assert run["gnn_inferences"] > 0
    assert run["heuristic_predictions"] == 0
    assert run["predictor_exception"] is None
    assert run["inference_latency"]["count"] == run["gnn_inferences"]
    assert run["inference_latency"]["p95_us"] > 0
    assert run["components"]["predictor"] == "gnn"
    assert len(run["components"]["weights_sha256"]) == 64
    assert run["components"]["model_evidence"] == "SIMULATION_CALIBRATED"
