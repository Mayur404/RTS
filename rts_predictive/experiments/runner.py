"""
Experiment Runner executing benchmark evaluations across all schedulers and seeds.
Produces structured JSON metrics, comparative dataframes, and raw telemetry logs.
"""

import os
import json
from pathlib import Path
import uuid
from typing import Dict, List, Any, Optional
import pandas as pd

from rts_predictive.config import PredictiveRuntimeConfig
from rts_predictive.experiments.scenarios import (
    create_nominal_scenario,
    create_bursty_scenario,
    create_thermal_scenario,
    create_unreliable_neighbor_scenario
)
from rts_predictive.schedulers.local_fifo import LocalFIFOScheduler
from rts_predictive.schedulers.edf import EDFScheduler
from rts_predictive.schedulers.rm import RMScheduler
from rts_predictive.schedulers.reactive_fallback import ReactiveFallbackScheduler
from rts_predictive.schedulers.always_offload import AlwaysOffloadScheduler
from rts_predictive.schedulers.predictive_no_fallback import PredictiveNoFallbackScheduler
from rts_predictive.schedulers.predictive_runtime import PredictiveRuntimeScheduler


class ExperimentRunner:
    """Coordinates batch simulations across schedulers, seeds, and workloads."""

    def __init__(self, output_dir: str = "results"):
        self.output_dir = output_dir
        self.raw_dir = os.path.join(output_dir, "raw_runs")
        os.makedirs(self.raw_dir, exist_ok=True)

    def _instantiate_scheduler(self, name: str) -> Any:
        if name in ("rts_predictive", "rts_predictive_gnn"):
            from rts_predictive.gnn.model import load_pretrained_gnn
            return PredictiveRuntimeScheduler(
                gnn_predictor=load_pretrained_gnn(),
                enable_federated=(name == "rts_predictive"),
            )
        mapping = {
            "local_fifo": LocalFIFOScheduler(),
            "edf": EDFScheduler(),
            "rm": RMScheduler(),
            "reactive_fallback": ReactiveFallbackScheduler(),
            "always_offload": AlwaysOffloadScheduler(),
            "predictive_no_fallback": PredictiveNoFallbackScheduler(),
        }
        return mapping[name]

    def run_single_benchmark(
        self,
        scheduler_name: str,
        scenario_type: str = "bursty",
        seed: int = 42,
        fleet_size: int = 6,
        duration_ms: float = 500.0,
        experiment_id: Optional[str] = None,
        pair_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Runs a single deterministic simulation trial."""
        if scenario_type == "nominal":
            sim = create_nominal_scenario(seed=seed, fleet_size=fleet_size, duration_ms=duration_ms)
        elif scenario_type == "bursty":
            sim = create_bursty_scenario(seed=seed, fleet_size=fleet_size, duration_ms=duration_ms)
        elif scenario_type == "thermal":
            sim = create_thermal_scenario(seed=seed, fleet_size=fleet_size, duration_ms=duration_ms)
        elif scenario_type == "unreliable":
            sim = create_unreliable_neighbor_scenario(seed=seed, fleet_size=fleet_size, duration_ms=duration_ms)
        else:
            raise ValueError(f"unknown scenario type: {scenario_type}")

        scheduler = self._instantiate_scheduler(scheduler_name)
        components = {
            "predictor": getattr(scheduler, "predictor_type", "none"),
            "remote_estimator": getattr(scheduler, "estimator_type", "none"),
            "offload_enabled": getattr(scheduler, "enable_offload", False),
            "watchdog_enabled": getattr(scheduler, "enable_watchdog", False),
        }
        if components["predictor"] == "gnn":
            from rts_predictive.artifacts.canonical import sha256_file
            components["weights_sha256"] = sha256_file("models/gnn_predictive_runtime.pt")
            components["model_evidence"] = (
                "SIMULATION_CALIBRATED"
                if getattr(scheduler.gnn_predictor, "calibrated", False)
                else "WEIGHTS_ONLY"
            )
            components["model_bundle_version"] = getattr(
                scheduler.gnn_predictor, "bundle_version", None
            )
        if components["remote_estimator"] == "federated":
            components["federated_model_evidence"] = "SIMULATION_EVALUATED"
            components["federated_bundle_version"] = getattr(
                scheduler.federated_model, "bundle_version", None
            )
        sim.run_id = f"{scenario_type}-{seed}-{scheduler_name}-{uuid.uuid4().hex[:8]}"
        sim.attach_scheduler(scheduler)
        metrics = sim.run(duration_ms=duration_ms)

        from rts_predictive.artifacts import CanonicalEventWriter
        from rts_predictive.artifacts.code_provenance import code_provenance
        from scripts.generate_paper_artifacts import reduce_event_stream
        event_path = Path(self.raw_dir) / f"{sim.run_id}.jsonl"
        with CanonicalEventWriter(event_path, sim.run_id) as writer:
            for event in sim.canonical_events:
                writer.write(event)
            digest = writer.sha256
        reduced = reduce_event_stream(event_path)
        manifest_path = event_path.with_suffix(".manifest.json")
        manifest_path.write_text(json.dumps({
            "schema_version": "rts_predictive.run-manifest/1.0",
            "run_id": sim.run_id, "scenario": scenario_type,
            "experiment_id": experiment_id,
            "pair_id": pair_id,
            "seed": seed, "policy": scheduler_name,
            "rng": sim.random_streams.provenance(),
            "components": components,
            "duration_us": int(round(duration_ms * 1000)),
            **code_provenance(),
            "event_file": str(event_path.resolve()),
            "event_sha256": digest, "event_count": len(sim.canonical_events),
        }, indent=2), encoding="utf-8")
        metrics["deadline_miss_ratio"] = reduced["total_dmr"]
        metrics["critical_deadline_miss_ratio"] = reduced["critical_dmr"]
        metrics["deadline_missed_count"] = reduced["missed"]
        metrics["critical_misses"] = reduced["critical_missed"]
        metrics["worst_case_response_time_ms"] = (
            max(reduced["wcrt_us"].values()) / 1000 if reduced["wcrt_us"] else 0.0
        )
        metrics["jitter_ms"] = (
            max(reduced["jitter_us"].values()) / 1000 if reduced["jitter_us"] else 0.0
        )
        metrics["avg_response_time_ms"] = (
            reduced["average_response_time_us"] / 1000
            if reduced["average_response_time_us"] is not None else 0.0
        )
        metrics["avg_utility"] = reduced["average_utility"]
        metrics["total_offloads"] = reduced["offload_dispatches"]
        metrics["total_fallbacks"] = reduced["fallbacks"]
        metrics["manifest"] = str(manifest_path)
        metrics["components"] = components
        metrics["gnn_inferences"] = getattr(scheduler, "gnn_inferences_count", 0)
        metrics["heuristic_predictions"] = getattr(scheduler, "heuristic_predictions_count", 0)
        metrics["predictor_exception"] = getattr(scheduler, "last_predictor_exception", None)
        metrics["inference_latency"] = (
            scheduler.inference_latency_summary()
            if hasattr(scheduler, "inference_latency_summary") else None
        )

        metrics["scheduler"] = scheduler_name
        metrics["scenario"] = scenario_type
        metrics["seed"] = seed
        metrics["fleet_size"] = fleet_size
        return metrics

    def run_full_suite(
        self,
        schedulers: Optional[List[str]] = None,
        seeds: List[int] = [42, 101, 202],
        scenarios: List[str] = ["bursty", "thermal", "unreliable"],
        duration_ms: float = 400.0
    ) -> Dict[str, Any]:
        """Runs comprehensive comparative benchmarks across all baselines."""
        target_schedulers = schedulers or [
            "local_fifo",
            "edf",
            "rm",
            "reactive_fallback",
            "always_offload",
            "predictive_no_fallback",
            "rts_predictive"
        ]

        all_runs: List[Dict[str, Any]] = []
        experiment_id = f"benchmark-{uuid.uuid4().hex[:12]}"

        for scen in scenarios:
            for seed in seeds:
                # First run local baseline to compute prevented violations baseline
                pair_id = f"{scen}-seed-{seed}"
                base_metrics = self.run_single_benchmark(
                    "local_fifo", scen, seed, duration_ms=duration_ms,
                    experiment_id=experiment_id, pair_id=pair_id,
                )
                base_misses = base_metrics["deadline_missed_count"]

                for sched_name in target_schedulers:
                    m = (dict(base_metrics) if sched_name == "local_fifo" else
                         self.run_single_benchmark(sched_name, scen, seed,
                                                   duration_ms=duration_ms,
                                                   experiment_id=experiment_id,
                                                   pair_id=pair_id))
                    # A negative value exposes policies that increase misses.
                    m["violations_prevented"] = base_misses - m["deadline_missed_count"]
                    all_runs.append(m)

        # Aggregate metrics by scheduler
        df = pd.DataFrame(all_runs)
        summary_table = df.groupby("scheduler").agg({
            "deadline_miss_ratio": ["mean", "std"],
            "deadline_missed_count": "mean",
            "critical_misses": "mean",
            "violations_prevented": "mean",
            "avg_response_time_ms": "mean",
            "worst_case_response_time_ms": "max",
            "jitter_ms": "mean",
            "total_offloads": "mean",
            "total_fallbacks": "mean"
        }).reset_index()

        # Format summary
        summary_json = {
            "experiment_id": experiment_id,
            "num_runs": len(all_runs),
            "scenarios": scenarios,
            "seeds": seeds,
            "results_by_scheduler": {}
        }
        for sched_name in target_schedulers:
            sub = df[df["scheduler"] == sched_name]
            from rts_predictive.experiments.statistics import bootstrap_mean_ci
            dmr_ci = bootstrap_mean_ci(sub["deadline_miss_ratio"], seed=17)
            paired_effect = bootstrap_mean_ci(sub["violations_prevented"], seed=23)
            summary_json["results_by_scheduler"][sched_name] = {
                "deadline_miss_ratio_mean": round(float(sub["deadline_miss_ratio"].mean()), 4),
                "deadline_miss_ratio_std": (
                    round(float(sub["deadline_miss_ratio"].std()), 4)
                    if len(sub) > 1 else None
                ),
                "deadline_miss_ratio_ci95": dmr_ci,
                "paired_violations_prevented_ci95": paired_effect,
                "avg_response_time_ms": round(float(sub["avg_response_time_ms"].mean()), 2),
                "worst_case_response_time_ms": round(float(sub["worst_case_response_time_ms"].max()), 2),
                "jitter_ms": round(float(sub["jitter_ms"].mean()), 2),
                "critical_misses_avg": round(float(sub["critical_misses"].mean()), 1),
                "violations_prevented_avg": round(float(sub["violations_prevented"].mean()), 1),
                "total_offloads_avg": round(float(sub["total_offloads"].mean()), 1),
                "total_fallbacks_avg": round(float(sub["total_fallbacks"].mean()), 1)
            }

        # Save artifacts
        summary_path = os.path.join(self.output_dir, "summary.json")
        with open(summary_path, "w") as f:
            json.dump(summary_json, f, indent=2)

        raw_path = os.path.join(self.raw_dir, "benchmark_runs.json")
        with open(raw_path, "w") as f:
            json.dump(all_runs, f, indent=2)

        return summary_json
