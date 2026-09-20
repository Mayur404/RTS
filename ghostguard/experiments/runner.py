"""
Experiment Runner executing benchmark evaluations across all schedulers and seeds.
Produces structured JSON metrics, comparative dataframes, and raw telemetry logs.
"""

import os
import json
from typing import Dict, List, Any, Optional
import pandas as pd

from ghostguard.config import GhostGuardConfig
from ghostguard.experiments.scenarios import (
    create_nominal_scenario,
    create_bursty_scenario,
    create_thermal_scenario,
    create_unreliable_neighbor_scenario
)
from ghostguard.schedulers.local_fifo import LocalFIFOScheduler
from ghostguard.schedulers.edf import EDFScheduler
from ghostguard.schedulers.rm import RMScheduler
from ghostguard.schedulers.reactive_fallback import ReactiveFallbackScheduler
from ghostguard.schedulers.always_offload import AlwaysOffloadScheduler
from ghostguard.schedulers.predictive_no_fallback import PredictiveNoFallbackScheduler
from ghostguard.schedulers.ghostguard import GhostGuardScheduler


class ExperimentRunner:
    """Coordinates batch simulations across schedulers, seeds, and workloads."""

    def __init__(self, output_dir: str = "results"):
        self.output_dir = output_dir
        self.raw_dir = os.path.join(output_dir, "raw_runs")
        os.makedirs(self.raw_dir, exist_ok=True)

    def _instantiate_scheduler(self, name: str) -> Any:
        mapping = {
            "local_fifo": LocalFIFOScheduler(),
            "edf": EDFScheduler(),
            "rm": RMScheduler(),
            "reactive_fallback": ReactiveFallbackScheduler(),
            "always_offload": AlwaysOffloadScheduler(),
            "predictive_no_fallback": PredictiveNoFallbackScheduler(),
            "ghostguard": GhostGuardScheduler(),
        }
        return mapping[name]

    def run_single_benchmark(
        self,
        scheduler_name: str,
        scenario_type: str = "bursty",
        seed: int = 42,
        fleet_size: int = 6,
        duration_ms: float = 500.0
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
            sim = create_bursty_scenario(seed=seed, fleet_size=fleet_size, duration_ms=duration_ms)

        scheduler = self._instantiate_scheduler(scheduler_name)
        sim.attach_scheduler(scheduler)
        metrics = sim.run(duration_ms=duration_ms)

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
            "ghostguard"
        ]

        all_runs: List[Dict[str, Any]] = []

        for scen in scenarios:
            for seed in seeds:
                # First run local baseline to compute prevented violations baseline
                base_metrics = self.run_single_benchmark("local_fifo", scen, seed, duration_ms=duration_ms)
                base_misses = base_metrics["deadline_missed_count"]

                for sched_name in target_schedulers:
                    m = self.run_single_benchmark(sched_name, scen, seed, duration_ms=duration_ms)
                    m["violations_prevented"] = max(0, base_misses - m["deadline_missed_count"])
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
            "num_runs": len(all_runs),
            "scenarios": scenarios,
            "seeds": seeds,
            "results_by_scheduler": {}
        }
        for sched_name in target_schedulers:
            sub = df[df["scheduler"] == sched_name]
            summary_json["results_by_scheduler"][sched_name] = {
                "deadline_miss_ratio_mean": round(float(sub["deadline_miss_ratio"].mean()), 4),
                "deadline_miss_ratio_std": round(float(sub["deadline_miss_ratio"].std() or 0.0), 4),
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
