"""
Script to execute the PredictiveRuntime ablation study suite.
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rts_predictive.experiments.ablations import AblationRunner


def main():
    print("==================================================")
    print("          PREDICTIVE_RUNTIME ABLATION STUDY SUITE         ")
    print("==================================================")
    runner = AblationRunner(output_dir="results")
    summary = runner.run_ablations(seeds=[42, 101, 202], duration_ms=450.0)

    print("\nAblation Breakdown (Impact on Deadline Miss Ratio):")
    for name, m in summary.items():
        print(f"  {name:30s} -> Miss Ratio: {m['deadline_miss_ratio']*100:5.2f}% | Critical Misses: {m['critical_misses']}")

    print("\nAblation results saved to results/ablation_summary.json")
    print("==================================================")


if __name__ == "__main__":
    main()
