"""
Publication-Quality Figure and Table Generation for GhostGuard Research.
Produces Matplotlib visualizations and LaTeX / CSV comparative tables in results/.
"""

import os
import json
import matplotlib
# Experiment scripts run in terminals and CI, where a desktop Tk backend may
# not exist. Select a non-interactive renderer before importing pyplot.
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def setup_matplotlib_style():
    """Configures clean academic aesthetic for research plots."""
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.size"] = 10
    plt.rcParams["axes.titlesize"] = 12
    plt.rcParams["axes.labelsize"] = 11
    plt.rcParams["xtick.labelsize"] = 9
    plt.rcParams["ytick.labelsize"] = 9
    plt.rcParams["legend.fontsize"] = 9
    plt.rcParams["figure.titlesize"] = 13
    plt.rcParams["lines.linewidth"] = 1.8
    plt.rcParams["axes.grid"] = True
    plt.rcParams["grid.alpha"] = 0.3


def generate_all_research_artifacts(output_dir: str = "results"):
    setup_matplotlib_style()
    fig_dir = os.path.join(output_dir, "figures")
    tbl_dir = os.path.join(output_dir, "tables")
    os.makedirs(fig_dir, exist_ok=True)
    os.makedirs(tbl_dir, exist_ok=True)

    summary_path = os.path.join(output_dir, "summary.json")
    if not os.path.exists(summary_path):
        from ghostguard.experiments.runner import ExperimentRunner
        runner = ExperimentRunner(output_dir)
        runner.run_full_suite()

    with open(summary_path, "r") as f:
        data = json.load(f)

    results = data["results_by_scheduler"]

    # 1. Figure 1: Deadline Miss Ratio Comparison Bar Chart
    sched_labels = [
        ("local_fifo", "Local-FIFO", "#888888"),
        ("edf", "EDF-Local", "#4A90E2"),
        ("rm", "RM-Local", "#50E3C2"),
        ("reactive_fallback", "Reactive-Degradation", "#F5A623"),
        ("always_offload", "Always-Offload", "#D0021B"),
        ("predictive_no_fallback", "Predictive-NoFallback", "#9013FE"),
        ("ghostguard", "GhostGuard (Proposed)", "#27AE60"),
    ]

    names = [s[1] for s in sched_labels if s[0] in results]
    miss_ratios = [results[s[0]]["deadline_miss_ratio_mean"] * 100 for s in sched_labels if s[0] in results]
    colors = [s[2] for s in sched_labels if s[0] in results]

    fig, ax = plt.subplots(figsize=(9, 4.5))
    bars = ax.bar(names, miss_ratios, color=colors, edgecolor="black", alpha=0.85, width=0.55)

    for bar in bars:
        yval = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2.0, yval + 0.5, f"{yval:.1f}%", ha="center", va="bottom", fontweight="bold")

    ax.set_ylabel("Deadline Miss Ratio (%)")
    ax.set_title("Deadline Miss Ratio across Schedulers (Lower is Better)")
    ax.set_ylim(0, max(miss_ratios) * 1.25)
    plt.xticks(rotation=22, ha="right")
    plt.tight_layout()
    fig_path1 = os.path.join(fig_dir, "deadline_miss_comparison.png")
    plt.savefig(fig_path1, dpi=300)
    plt.close()

    # 2. Figure 2: Ablation Study Impact
    ablation_path = os.path.join(output_dir, "ablation_summary.json")
    if not os.path.exists(ablation_path):
        from ghostguard.experiments.ablations import AblationRunner
        ab_runner = AblationRunner(output_dir)
        ab_runner.run_ablations()

    with open(ablation_path, "r") as f:
        ab_data = json.load(f)

    ab_names = list(ab_data.keys())
    ab_ratios = [ab_data[k]["deadline_miss_ratio"] * 100 for k in ab_names]

    fig, ax = plt.subplots(figsize=(8.5, 4.2))
    bars = ax.barh(ab_names, ab_ratios, color="#2E86AB", edgecolor="black", alpha=0.85, height=0.5)
    for bar in bars:
        xval = bar.get_width()
        ax.text(xval + 0.3, bar.get_y() + bar.get_height()/2.0, f"{xval:.1f}%", ha="left", va="center", fontweight="bold")

    ax.set_xlabel("Deadline Miss Ratio (%)")
    ax.set_title("GhostGuard Component Ablation Study (Lower is Better)")
    ax.set_xlim(0, max(ab_ratios) * 1.2)
    ax.invert_yaxis()
    plt.tight_layout()
    fig_path2 = os.path.join(fig_dir, "ablation_study.png")
    plt.savefig(fig_path2, dpi=300)
    plt.close()

    # 3. Figure 3: Federated Learning Convergence Curve. Never invent values:
    # this chart is emitted only from the artifact written by run_federated.py.
    fig_path3 = None
    federated_path = os.path.join(output_dir, "federated_results.json")
    if os.path.exists(federated_path):
        with open(federated_path, "r") as f:
            federated_data = json.load(f)
        history = federated_data.get("federated_rounds", [])
        if history and all("mae_exec_time_ms" in record for record in history):
            rounds = [record["round"] for record in history]
            fedavg_mae = [record["mae_exec_time_ms"] for record in history]
            reference = federated_data.get("centralized_pooled_data_reference", {}).get("centralized_mae_ms")
            fig, ax = plt.subplots(figsize=(7, 3.8))
            ax.plot(rounds, fedavg_mae, marker="o", color="#E67E22", label="FedAvg (decentralized)")
            if reference is not None:
                ax.axhline(reference, linestyle="--", color="#27AE60", label="Centralized pooled-data reference")
            ax.set_xlabel("Federated aggregation round")
            ax.set_ylabel("Execution-time estimation MAE (ms)")
            ax.set_title("Cross-Device Execution Model Convergence")
            ax.legend()
            plt.tight_layout()
            fig_path3 = os.path.join(fig_dir, "fl_convergence.png")
            plt.savefig(fig_path3, dpi=300)
            plt.close()

    # 4. Generate LaTeX Table and CSV
    rows = []
    for s_key, s_label, _ in sched_labels:
        if s_key in results:
            r = results[s_key]
            rows.append({
                "Scheduler": s_label,
                "Miss Ratio (%)": f"{r['deadline_miss_ratio_mean']*100:.1f} ± {r['deadline_miss_ratio_std']*100:.1f}",
                "Avg Response Time (ms)": f"{r['avg_response_time_ms']:.1f}",
                "Worst-Case RT (ms)": f"{r['worst_case_response_time_ms']:.1f}",
                "Jitter (ms)": f"{r['jitter_ms']:.1f}",
                "Violations Prevented": f"{r['violations_prevented_avg']:.1f}",
                "Offloads": f"{r['total_offloads_avg']:.1f}",
                "Fallbacks": f"{r['total_fallbacks_avg']:.1f}",
            })

    df_table = pd.DataFrame(rows)
    csv_path = os.path.join(tbl_dir, "benchmark_results.csv")
    df_table.to_csv(csv_path, index=False)

    latex_code = df_table.to_latex(index=False, caption="Real-Time Systems Benchmark Evaluation Results", label="tab:benchmark_results")
    tex_path = os.path.join(tbl_dir, "benchmark_results.tex")
    with open(tex_path, "w") as f:
        f.write(latex_code)

    return {
        "figures": [path for path in [fig_path1, fig_path2, fig_path3] if path],
        "tables": [csv_path, tex_path]
    }
