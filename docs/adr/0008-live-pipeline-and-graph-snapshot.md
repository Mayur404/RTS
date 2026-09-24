# ADR 0008: Live pipeline and graph snapshot

Status: Accepted

## Context

The live UI needs a workload DAG whose edges and stage states correspond to the workload being simulated. The former live session scheduled independent periodic task profiles, so a connected DAG drawn over that run would be misleading.

## Decision

The live session schedules the reference six-stage `PipelineSpec` on each fleet node for both the PredictiveRuntime and EDF simulators. This uses the existing causal `schedule_periodic_pipeline` path. The `/api/live/start`, `/api/live/step`, and `/api/live/reset` snapshots add a `pipeline` object with the pipeline ID, stage specifications, dependency edges, and the latest released job on each node. A stage is `WAITING` until that job releases it; released stages use their actual simulator task state and timestamps. The UI labels this as simulated state.

The fleet and interaction views consume the snapshot's configured `links` and `active_offloads`. Dragging changes only browser layout coordinates and has no effect on simulated positions, network behavior, or metrics.

The `pipeline` object also exposes `focus_jobs`, an inspection cursor that selects the oldest incomplete job per node and falls back to the latest completed job. `latest_jobs` remains available for compatibility. Stage records include remaining simulated work, execution device, and degraded-mode state. In-flight offload records expose their simulated request, remote execution, or result phase and bounded progress. These additions drive animation but do not create events or affect scheduling.

Each live start returns a `session_id`; subsequent step and fault requests may supply it to address that run. The browser supplies it. Requests without an ID retain the single-session behavior for older clients, and unknown IDs return 404. The server keeps the 16 most recently created sessions in memory.

The fleet definitions contain diagram coordinates. For live simulation, ten diagram units represent one modeled meter before applying the 45 m peer-link threshold. This explicit, uncalibrated geometry gives six- and eight-node scenarios connected peer graphs. Browser dragging affects only the drawing.

## Consequences

Live-run metrics now describe DAG workloads and are not directly comparable to earlier live sessions that used independent tasks. The separate experiment API and its schemas are unchanged. The live snapshot remains transient and is not a canonical experiment artifact. A continuously drawn browser clock may interpolate only up to the latest confirmed simulator time; events and metrics update from completed API steps. Live sessions disappear when the server restarts or their entry is evicted.
