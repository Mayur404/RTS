"""
Script to execute the complete real-time systems benchmark suite.
Runs all 7 schedulers, outputs comparative tables, and generates publication plots.
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rts_predictive.experiments.runner import ExperimentRunner
from rts_predictive.experiments.ablations import AblationRunner
from rts_predictive.experiments.generate_plots import generate_all_research_artifacts


def main():
    parser = argparse.ArgumentParser(description="Reproducible, event-backed simulated policy experiments")
    parser.add_argument("--output", default="research_runs/experiment_suite")
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(1000, 1030)),
                        help="Paired evaluation seeds; defaults to 30 seeds outside the model's training seeds")
    parser.add_argument("--duration-ms", type=float, default=400.0)
    parser.add_argument("--scenarios", nargs="+", choices=["nominal", "bursty", "thermal", "unreliable"],
                        default=["nominal", "bursty", "thermal", "unreliable"])
    parser.add_argument("--skip-ablations", action="store_true")
    args = parser.parse_args()
    if args.duration_ms <= 0 or len(set(args.seeds)) != len(args.seeds) or any(seed < 0 for seed in args.seeds):
        parser.error("duration must be positive and seeds must be unique non-negative integers")
    print("==================================================")
    print("     PREDICTIVE_RUNTIME BENCHMARK & EXPERIMENT HARNESS    ")
    print("==================================================")

    output_dir = args.output
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
            "rts_predictive"
        ],
        seeds=args.seeds,
        scenarios=args.scenarios,
        duration_ms=args.duration_ms
    )

    print("\nBenchmark Results Summary (Deadline Miss Ratio):")
    for s_name, res in bench_summary["results_by_scheduler"].items():
        print(f"  {s_name:25s}: {res['deadline_miss_ratio_mean']*100:5.2f}% ± {res['deadline_miss_ratio_std']*100:.2f}% | Violations Prevented: {res['violations_prevented_avg']}")

    if not args.skip_ablations:
        print("\n[2/3] Running ablation study...")
        ab_runner = AblationRunner(output_dir=output_dir)
        ab_summary = ab_runner.run_ablations(seeds=args.seeds, duration_ms=args.duration_ms)
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
