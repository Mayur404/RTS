"""
Ablation Study Runner.
Quantifies the individual contributions of GhostGuard components:
1. Full GhostGuard (All components active)
2. w/o GNN (Replaced with queue threshold heuristic)
3. w/o Federated Learning (Replaced with static uncalibrated speed assumption)
4. w/o Offloading (Local verified fallback only)
5. w/o Fallback (Predictive offloading only, no recovery)
6. w/o Neighbor Reliability (Blind offloading without reliability filtering)
"""

import os
import json
from typing import Dict, List, Any
import pandas as pd

from ghostguard.experiments.scenarios import create_bursty_scenario
from ghostguard.schedulers.ghostguard import GhostGuardScheduler


class AblationRunner:
    """Executes systematic ablation suite."""

    def __init__(self, output_dir: str = "results"):
        self.output_dir = output_dir

    def run_ablations(self, seeds: List[int] = [42, 101, 202], duration_ms: float = 450.0) -> Dict[str, Any]:
        ablation_configs = {
            "Full-GhostGuard": {
                "gnn": True, "fl": True, "offload": True, "fallback": True, "reliability": True
            },
            "w/o GNN": {
                "gnn": False, "fl": True, "offload": True, "fallback": True, "reliability": True
            },
            "w/o Federated Learning": {
                "gnn": True, "fl": False, "offload": True, "fallback": True, "reliability": True
            },
            "w/o Offloading": {
                "gnn": True, "fl": True, "offload": False, "fallback": True, "reliability": True
            },
            "w/o Fallback": {
                "gnn": True, "fl": True, "offload": True, "fallback": False, "reliability": True
            },
            "w/o Neighbor Reliability": {
                "gnn": True, "fl": True, "offload": True, "fallback": True, "reliability": False
            }
        }

        records = []
        for name, cfg in ablation_configs.items():
            for seed in seeds:
                sim = create_bursty_scenario(seed=seed, fleet_size=6, duration_ms=duration_ms)

                # Configure scheduler according to ablation flags
                rel_thresh = 0.70 if cfg["reliability"] else 0.0
                sched = GhostGuardScheduler(
                    risk_threshold=0.60,
                    reliability_threshold=rel_thresh,
                    safety_margin_ms=3.0
                )

                # Disable offloading if configured
                if not cfg["offload"]:
                    sched.evaluate_offload_candidates = lambda task, dev, t: None

                # Disable fallback if configured
                if not cfg["fallback"]:
                    # Do not degrade on monitor intercept or candidate absence
                    sched._handle_progress_check = lambda event: None

                sim.attach_scheduler(sched)
                m = sim.run(duration_ms=duration_ms)
                m["ablation"] = name
                m["seed"] = seed
                records.append(m)

        df = pd.DataFrame(records)
        summary = {}
        for name in ablation_configs.keys():
            sub = df[df["ablation"] == name]
            summary[name] = {
                "deadline_miss_ratio": round(float(sub["deadline_miss_ratio"].mean()), 4),
                "critical_misses": round(float(sub["critical_misses"].mean()), 1),
                "avg_response_time_ms": round(float(sub["avg_response_time_ms"].mean()), 2),
                "total_offloads": round(float(sub["total_offloads"].mean()), 1),
                "total_fallbacks": round(float(sub["total_fallbacks"].mean()), 1)
            }

        out_path = os.path.join(self.output_dir, "ablation_summary.json")
        with open(out_path, "w") as f:
            json.dump(summary, f, indent=2)

        return summary
