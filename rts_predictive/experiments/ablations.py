"""
Ablation Study Runner.
Quantifies the individual contributions of PredictiveRuntime components:
1. Full PredictiveRuntime (All components active)
2. w/o GNN (Replaced with analytical queue threshold heuristic)
3. w/o Federated Learning (Replaced with static uncalibrated speed assumption)
4. w/o Offloading (Local verified fallback only)
5. w/o Fallback (Predictive offloading only, no recovery)
6. w/o Neighbor Reliability (Blind offloading without reliability filtering)
7. w/o Watchdog (No active in-flight monitoring of remote execution)
"""

import os
import json
from pathlib import Path
import uuid
from dataclasses import dataclass
from typing import Dict, List, Any, Mapping
import pandas as pd

from rts_predictive.experiments.scenarios import create_bursty_scenario
from rts_predictive.schedulers.predictive_runtime import PredictiveRuntimeScheduler


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
    "Full-PredictiveRuntime": AblationConfig(
        name="Full-PredictiveRuntime",
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


def instantiate_ablation_scheduler(config: AblationConfig) -> PredictiveRuntimeScheduler:
    """Instantiates a PredictiveRuntime scheduler configured strictly according to ablation flags."""
    return PredictiveRuntimeScheduler(
        risk_threshold=0.60,
        reliability_threshold=0.50 if config.enable_reliability_filter else 0.0,
        safety_margin_ms=3.0,
        enable_gnn=config.enable_gnn,
        enable_federated=config.enable_federated,
        enable_offload=config.enable_offload,
        enable_watchdog=config.enable_watchdog,
        enable_fallback=config.enable_fallback,
        enable_reliability_filter=config.enable_reliability_filter,
    )


def assert_ablation_component_graph(scheduler: PredictiveRuntimeScheduler, config_name: str) -> None:
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
    else:
        assert scheduler.gnn_predictor is not None, f"{config_name}: GNN weights unavailable"
    if not cfg.enable_federated:
        assert scheduler.federated_model is None
        assert scheduler.estimator_type == "static_spec"
    else:
        assert scheduler.federated_model is not None, f"{config_name}: federated model unavailable"
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
        experiment_id = f"ablation-{uuid.uuid4().hex[:12]}"

        for name in target_configs:
            cfg = ABLATION_REGISTRY[name]
            for seed in seeds:
                sim = create_bursty_scenario(seed=seed, fleet_size=6, duration_ms=duration_ms)
                sim.schedule_contention_burst(
                    target_device_id="Device_2",
                    start_time_ms=150.0,
                    duration_ms=120.0,
                    cpu_load=0.98,
                    gpu_load=0.98,
                )
                sched = instantiate_ablation_scheduler(cfg)
                assert_ablation_component_graph(sched, name)
                components = {
                    "predictor": sched.predictor_type,
                    "remote_estimator": sched.estimator_type,
                    "federated_model_evidence": (
                        "UNTRAINED" if sched.federated_model is not None else None
                    ),
                }
                if sched.gnn_predictor is not None:
                    from rts_predictive.artifacts.canonical import sha256_file
                    components["weights_sha256"] = sha256_file("models/gnn_predictive_runtime.pt")
                    components["model_evidence"] = (
                        "SIMULATION_CALIBRATED"
                        if getattr(sched.gnn_predictor, "calibrated", False)
                        else "WEIGHTS_ONLY"
                    )
                if sched.federated_model is not None:
                    components["federated_model_evidence"] = "SIMULATION_EVALUATED"
                    components["federated_bundle_version"] = getattr(
                        sched.federated_model, "bundle_version", None
                    )
                sim.run_id = f"ablation-{seed}-{uuid.uuid4().hex[:12]}"
                sim.attach_scheduler(sched)

                m = sim.run(duration_ms=duration_ms)
                from rts_predictive.artifacts import CanonicalEventWriter
                from rts_predictive.artifacts.code_provenance import code_provenance
                from scripts.generate_paper_artifacts import reduce_event_stream
                raw_dir = Path(self.output_dir) / "raw_runs"
                raw_dir.mkdir(parents=True, exist_ok=True)
                event_path = raw_dir / f"{sim.run_id}.jsonl"
                with CanonicalEventWriter(event_path, sim.run_id) as writer:
                    for event in sim.canonical_events:
                        writer.write(event)
                    digest = writer.sha256
                reduced = reduce_event_stream(event_path)
                manifest_path = event_path.with_suffix(".manifest.json")
                manifest_path.write_text(json.dumps({
                    "schema_version": "rts_predictive.run-manifest/1.0",
                    "run_id": sim.run_id, "scenario": "bursty_neighbor_stress", "seed": seed,
                    "experiment_id": experiment_id,
                    "pair_id": f"bursty_neighbor_stress-seed-{seed}",
                    "rng": sim.random_streams.provenance(),
                    "policy": name, "duration_us": int(round(duration_ms * 1000)),
                    "components": components,
                    **code_provenance(),
                    "event_file": str(event_path.resolve()),
                    "event_sha256": digest, "event_count": len(sim.canonical_events),
                }, indent=2), encoding="utf-8")
                m["deadline_miss_ratio"] = reduced["total_dmr"]
                m["critical_misses"] = reduced["critical_missed"]
                m["avg_response_time_ms"] = (
                    reduced["average_response_time_us"] / 1000
                    if reduced["average_response_time_us"] is not None else 0.0
                )
                m["total_offloads"] = reduced["offload_dispatches"]
                m["total_fallbacks"] = reduced["fallbacks"]
                m["avg_utility"] = reduced["average_utility"]
                m["manifest"] = str(manifest_path)
                m["components"] = components
                m["gnn_inferences"] = sched.gnn_inferences_count
                m["heuristic_predictions"] = sched.heuristic_predictions_count
                m["predictor_exception"] = getattr(sched, "last_predictor_exception", None)
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
                "avg_utility": (
                    round(float(sub["avg_utility"].mean()), 3)
                    if "avg_utility" in sub and pd.notna(sub["avg_utility"].mean())
                    else None
                ),
                "run_manifests": list(sub["manifest"]),
            }

        os.makedirs(self.output_dir, exist_ok=True)
        out_path = os.path.join(self.output_dir, "ablation_summary.json")
        with open(out_path, "w") as f:
            json.dump(summary, f, indent=2)

        return summary

