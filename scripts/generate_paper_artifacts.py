"""Build simulation tables and figures from validated canonical event streams."""

from __future__ import annotations

import json
from pathlib import Path
from rts_predictive.artifacts.code_provenance import code_provenance

from rts_predictive.artifacts import CanonicalEventWriter, iter_canonical_events
from rts_predictive.experiments.scenarios import create_bursty_scenario
from rts_predictive.experiments.plotting import generate_all_plots
from rts_predictive.schedulers.edf import EDFScheduler
from rts_predictive.schedulers.local_fifo import LocalFIFOScheduler
from rts_predictive.schedulers.predictive_runtime import PredictiveRuntimeScheduler


POLICIES = {
    "local_fifo": LocalFIFOScheduler,
    "edf": EDFScheduler,
    "predictive_runtime": PredictiveRuntimeScheduler,
}


def reduce_event_stream(path):
    """Derive released jobs, misses, response times, and jitter from JSONL."""
    releases, misses, commits, responses = {}, set(), set(), {}
    offloads = fallbacks = 0
    utilities = []
    for event in iter_canonical_events(path):
        task_id = event.get("task_id")
        payload = event["payload"]
        kind = event["event_type"]
        if kind == "OFFLOAD_DISPATCH":
            offloads += 1
        elif kind in ("FALLBACK_TRIGGER", "OFFLOAD_ABORT"):
            fallbacks += 1
        if kind == "TASK_READY" and task_id:
            if task_id in releases:
                raise ValueError(f"duplicate release: {task_id}")
            releases[task_id] = (event["timestamp_us"], payload["task_name"],
                                 bool(payload["is_critical"]))
        elif kind == "DEADLINE" and task_id:
            misses.add(task_id)
        elif kind == "TASK_COMMIT" and task_id:
            if task_id not in releases or task_id in commits:
                raise ValueError(f"invalid commit: {task_id}")
            commits.add(task_id)
            utilities.append(float(payload.get("output_utility", 1.0)))
            if payload.get("deadline_met") is False:
                misses.add(task_id)
            released_at, name, _ = releases[task_id]
            responses.setdefault(name, []).append(event["timestamp_us"] - released_at)
    if misses - releases.keys():
        raise ValueError("deadline event without task release")
    critical = {task_id for task_id, (_, _, flag) in releases.items() if flag}
    n = len(releases)
    all_responses = [value for values in responses.values() for value in values]
    return {
        "released": n,
        "missed": len(misses),
        "critical_released": len(critical),
        "critical_missed": len(misses & critical),
        "total_dmr": len(misses) / n if n else None,
        "critical_dmr": len(misses & critical) / len(critical) if critical else None,
        "wcrt_us": {name: max(values) for name, values in responses.items()},
        "jitter_us": {name: max(values) - min(values) for name, values in responses.items()},
        "response_times_us": all_responses,
        "average_response_time_us": sum(all_responses) / len(all_responses) if all_responses else None,
        "average_utility": sum(utilities) / len(utilities) if utilities else None,
        "offload_dispatches": offloads,
        "fallbacks": fallbacks,
        "censored": len(releases.keys() - misses - commits),
    }


def generate_paper_artifacts(output_dir="research_runs/paper", plots_dir="research_runs/plots",
                             *, duration_ms=100, seeds=(42,)):
    output = Path(output_dir)
    raw_dir = output / "raw_runs"
    raw_dir.mkdir(parents=True, exist_ok=True)
    source = code_provenance()
    records = []
    for seed in seeds:
        for policy, scheduler_factory in POLICIES.items():
            run_id = f"bursty-{seed}-{policy}"
            sim = create_bursty_scenario(seed=seed, fleet_size=3, duration_ms=duration_ms)
            sim.run_id = run_id
            sim.attach_scheduler(scheduler_factory())
            sim.run(duration_ms=duration_ms)
            event_path = raw_dir / f"{run_id}.jsonl"
            with CanonicalEventWriter(event_path, run_id) as writer:
                for event in sim.canonical_events:
                    writer.write(event)
                event_sha256 = writer.sha256
            manifest = {
                "schema_version": "rts_predictive.run-manifest/1.0",
                "run_id": run_id, "scenario": "bursty", "seed": seed,
                "policy": policy, "duration_us": duration_ms * 1000,
                **source,
                "event_file": str(event_path.resolve()),
                "event_sha256": event_sha256,
                "event_count": len(sim.canonical_events),
            }
            manifest_path = raw_dir / f"{run_id}.manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            records.append({"manifest": str(manifest_path),
                            "metrics": reduce_event_stream(event_path)})

    lines = [r"\begin{table}[t]", r"\centering",
             r"\caption{Simulated task outcomes from canonical event streams.}",
             r"\begin{tabular}{lrrrr}", r"\toprule",
             r"Policy & Released & Missed & Total DMR & Critical DMR \\",
             r"\midrule"]
    for record in records:
        manifest = json.loads(Path(record["manifest"]).read_text(encoding="utf-8"))
        metric = record["metrics"]
        total = "--" if metric["total_dmr"] is None else f'{metric["total_dmr"]:.4f}'
        critical = "--" if metric["critical_dmr"] is None else f'{metric["critical_dmr"]:.4f}'
        lines.append(f'{manifest["policy"]} ({manifest["seed"]}) & {metric["released"]} & '
                     f'{metric["missed"]} & {total} & {critical} ' + r"\\")
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}"]
    table_path = output / "table1_benchmark_summary.tex"
    table_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    figures = generate_all_plots(records, plots_dir)
    index = {"schema_version": "rts_predictive.artifact-index/1.0", "runs": records,
             "table": str(table_path), "figures": figures}
    (output / "PAPER_DATA.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    return index


if __name__ == "__main__":
    generate_paper_artifacts()
