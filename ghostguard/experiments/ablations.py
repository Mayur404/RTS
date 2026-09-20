"""
Ablation Study Runner.
Quantifies the individual contributions of GhostGuard components:
1. Full GhostGuard (All components active)
2. w/o GNN (Replaced with analytical queue threshold heuristic)
3. w/o Federated Learning (Replaced with static uncalibrated speed assumption)
4. w/o Offloading (Local verified fallback only)
5. w/o Fallback (Predictive offloading only, no recovery)
6. w/o Neighbor Reliability (Blind offloading without reliability filtering)
7. w/o Watchdog (No active in-flight monitoring of remote execution)
"""

import os
import json
from dataclasses import dataclass
from typing import Dict, List, Any, Mapping
import pandas as pd

from ghostguard.experiments.scenarios import create_bursty_scenario
from ghostguard.schedulers.ghostguard import GhostGuardScheduler


@dataclass(frozen=True)
class AblationConfig:
    name: str
    enable_gnn: bool = True
    enable_federated: bool = True
    enable_offload: bool = True
    enable_watchdog: bool = True
    enable_fallback: bool = True
    enable_reliability_filter: bool = True


ABLATION_REGISTRY: Dict[str, AblationConfig] = {
    "Full-GhostGuard": AblationConfig(
        name="Full-GhostGuard",
        enable_gnn=True,
        enable_federated=True,
        enable_offload=True,
        enable_watchdog=True,
        enable_fallback=True,
        enable_reliability_filter=True,
    ),
    "w/o GNN": AblationConfig(
        name="w/o GNN",
        enable_gnn=False,
        enable_federated=True,
        enable_offload=True,
        enable_watchdog=True,
        enable_fallback=True,
        enable_reliability_filter=True,
    ),
    "w/o Federated Learning": AblationConfig(
        name="w/o Federated Learning",
        enable_gnn=True,
        enable_federated=False,
        enable_offload=True,
        enable_watchdog=True,
        enable_fallback=True,
        enable_reliability_filter=True,
    ),
    "w/o Offloading": AblationConfig(
        name="w/o Offloading",
        enable_gnn=True,
        enable_federated=True,
        enable_offload=False,
        enable_watchdog=True,
        enable_fallback=True,
        enable_reliability_filter=True,
    ),
    "w/o Fallback": AblationConfig(
        name="w/o Fallback",
        enable_gnn=True,
        enable_federated=True,
        enable_offload=True,
        enable_watchdog=True,
        enable_fallback=False,
        enable_reliability_filter=True,
    ),
    "w/o Neighbor Reliability": AblationConfig(
        name="w/o Neighbor Reliability",
        enable_gnn=True,
        enable_federated=True,
        enable_offload=True,
        enable_watchdog=True,
        enable_fallback=True,
        enable_reliability_filter=False,
    ),
    "w/o Watchdog": AblationConfig(
        name="w/o Watchdog",
        enable_gnn=True,
        enable_federated=True,
        enable_offload=True,
        enable_watchdog=False,
        enable_fallback=True,
        enable_reliability_filter=True,
    ),
}


def instantiate_ablation_scheduler(config: AblationConfig) -> GhostGuardScheduler:
    """Instantiates a GhostGuard scheduler configured strictly according to ablation flags."""
    return GhostGuardScheduler(
        risk_threshold=0.60,
        reliability_threshold=0.70 if config.enable_reliability_filter else 0.0,
        safety_margin_ms=3.0,
        enable_gnn=config.enable_gnn,
        enable_federated=config.enable_federated,
        enable_offload=config.enable_offload,
        enable_watchdog=config.enable_watchdog,
        enable_fallback=config.enable_fallback,
        enable_reliability_filter=config.enable_reliability_filter,
    )


def assert_ablation_component_graph(scheduler: GhostGuardScheduler, config_name: str) -> None:
    """Validates that the scheduler component graph matches the intended ablation configuration."""
    cfg = ABLATION_REGISTRY.get(config_name)
    if cfg is None:
        raise ValueError(f"Unknown ablation configuration: {config_name}")

    assert scheduler.enable_gnn == cfg.enable_gnn, f"{config_name}: enable_gnn mismatch"
    assert scheduler.enable_federated == cfg.enable_federated, f"{config_name}: enable_federated mismatch"
    assert scheduler.enable_offload == cfg.enable_offload, f"{config_name}: enable_offload mismatch"
    assert scheduler.enable_watchdog == cfg.enable_watchdog, f"{config_name}: enable_watchdog mismatch"
    assert scheduler.enable_fallback == cfg.enable_fallback, f"{config_name}: enable_fallback mismatch"
    assert scheduler.enable_reliability_filter == cfg.enable_reliability_filter, f"{config_name}: enable_reliability_filter mismatch"

    if not cfg.enable_gnn:
        assert scheduler.gnn_predictor is None
        assert scheduler.predictor_type == "heuristic"
    if not cfg.enable_federated:
        assert scheduler.federated_model is None
        assert scheduler.estimator_type == "static_spec"
    if not cfg.enable_reliability_filter:
        assert scheduler.reliability_threshold == 0.0


class AblationRunner:
    """Executes systematic ablation suite with verified component-graph substitutions."""

    def __init__(self, output_dir: str = "results"):
        self.output_dir = output_dir

    def run_ablations(
        self,
        seeds: List[int] = [42, 101, 202],
        duration_ms: float = 450.0,
        configs: List[str] = None,
    ) -> Dict[str, Any]:
        target_configs = configs or list(ABLATION_REGISTRY.keys())
        records = []

        for name in target_configs:
            cfg = ABLATION_REGISTRY[name]
            for seed in seeds:
                sim = create_bursty_scenario(seed=seed, fleet_size=6, duration_ms=duration_ms)
                sched = instantiate_ablation_scheduler(cfg)
                assert_ablation_component_graph(sched, name)
                sim.attach_scheduler(sched)

                m = sim.run(duration_ms=duration_ms)
                m["ablation"] = name
                m["seed"] = seed
                records.append(m)

        df = pd.DataFrame(records)
        summary = {}
        for name in target_configs:
            sub = df[df["ablation"] == name]
            summary[name] = {
                "deadline_miss_ratio": round(float(sub["deadline_miss_ratio"].mean()), 4),
                "critical_misses": round(float(sub["critical_misses"].mean()), 1),
                "avg_response_time_ms": round(float(sub["avg_response_time_ms"].mean()), 2),
                "total_offloads": round(float(sub["total_offloads"].mean()), 1),
                "total_fallbacks": round(float(sub["total_fallbacks"].mean()), 1),
                "avg_utility": round(float(sub["avg_utility"].mean()), 3) if "avg_utility" in sub else 1.0,
            }

        os.makedirs(self.output_dir, exist_ok=True)
        out_path = os.path.join(self.output_dir, "ablation_summary.json")
        with open(out_path, "w") as f:
            json.dump(summary, f, indent=2)

        return summary

