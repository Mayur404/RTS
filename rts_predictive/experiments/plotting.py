"""Publication plots calculated from event-derived metrics and observations."""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def generate_all_plots(records, output_dir):
    """Create 300 DPI raster and vector figures from reduced JSONL records."""
    if not records:
        raise ValueError("at least one event-backed run is required")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    labels = [Path(record["manifest"]).stem.removesuffix(".manifest")
              for record in records]
    totals = [record["metrics"]["total_dmr"] for record in records]
    critical = [record["metrics"]["critical_dmr"] for record in records]
    if any(value is None for value in totals + critical):
        raise ValueError("cannot plot DMR for a run without released tasks")

    paths = []
    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = list(range(len(records)))
    ax.bar([i - 0.2 for i in x], totals, width=0.4, label="Total DMR")
    ax.bar([i + 0.2 for i in x], critical, width=0.4, label="Critical DMR")
    ax.set_xticks(x, labels, rotation=20, ha="right")
    ax.set_ylabel("Deadline-miss ratio")
    ax.set_ylim(0, 1)
    ax.legend()
    fig.tight_layout()
    for suffix in ("png", "pdf"):
        path = output / f"deadline_miss_ratio.{suffix}"
        fig.savefig(path, dpi=300)
        paths.append(str(path))
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    for label, record in zip(labels, records):
        values = sorted(record["metrics"]["response_times_us"])
        if values:
            ax.step([value / 1000 for value in values],
                    [(index + 1) / len(values) for index in range(len(values))],
                    where="post", label=f"{label} (n={len(values)})")
    ax.set_xlabel("Observed response time (ms)")
    ax.set_ylabel("Empirical cumulative fraction")
    ax.set_ylim(0, 1)
    ax.legend()
    fig.tight_layout()
    for suffix in ("png", "pdf"):
        path = output / f"response_time_ecdf.{suffix}"
        fig.savefig(path, dpi=300)
        paths.append(str(path))
    plt.close(fig)
    return paths
