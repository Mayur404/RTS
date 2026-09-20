"""
Script to execute the complete real-time systems benchmark suite.
Runs all 7 schedulers, outputs comparative tables, and generates publication plots.
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ghostguard.experiments.runner import ExperimentRunner
from ghostguard.experiments.ablations import AblationRunner
from ghostguard.experiments.generate_plots import generate_all_research_artifacts


def main():
    print("==================================================")
    print("     GHOSTGUARD BENCHMARK & EXPERIMENT HARNESS    ")
    print("==================================================")

    output_dir = "results"
    os.makedirs(output_dir, exist_ok=True)

    print("\n[1/3] Running multi-scheduler comparative benchmarks across seeds...")
    runner = ExperimentRunner(output_dir=output_dir)
    bench_summary = runner.run_full_suite(
        schedulers=[
            "local_fifo",
            "edf",
            "rm",
            "reactive_fallback",
            "always_offload",
            "predictive_no_fallback",
            "ghostguard"
        ],
        seeds=[42, 101, 202],
        scenarios=["bursty", "thermal", "unreliable"],
        duration_ms=400.0
    )

    print("\nBenchmark Results Summary (Deadline Miss Ratio):")
    for s_name, res in bench_summary["results_by_scheduler"].items():
        print(f"  {s_name:25s}: {res['deadline_miss_ratio_mean']*100:5.2f}% ± {res['deadline_miss_ratio_std']*100:.2f}% | Violations Prevented: {res['violations_prevented_avg']}")

    print("\n[2/3] Running ablation study...")
    ab_runner = AblationRunner(output_dir=output_dir)
    ab_summary = ab_runner.run_ablations(seeds=[42, 101], duration_ms=400.0)

    print("\nAblation Results Summary:")
    for a_name, res in ab_summary.items():
        print(f"  {a_name:30s}: Miss Ratio: {res['deadline_miss_ratio']*100:5.2f}% | Critical Misses: {res['critical_misses']}")

    print("\n[3/3] Generating publication-quality figures and LaTeX tables...")
    artifacts = generate_all_research_artifacts(output_dir=output_dir)

    print("\nGenerated Figures:")
    for fig in artifacts["figures"]:
        print(f"  {fig}")

    print("\nGenerated Tables:")
    for tbl in artifacts["tables"]:
        print(f"  {tbl}")

    print("\nBenchmark experiment suite completed successfully.")
    print("==================================================")


if __name__ == "__main__":
    main()
