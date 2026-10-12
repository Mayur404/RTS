# ADR 0011: Live resource dependency projection

The live snapshot adds `resource_graph` version 1.0, with resource vertices,
runtime task vertices, and directed `allocation` (running) / `demand` (queued)
edges. Demands come from admitted task instances, not authored dashboard data.
CPU/GPU utilization is simulated state, not host utilization or physical telemetry.
This bipartite graph explains contention; it does not assert deadlock detection.

Pipeline stage metadata adds nominal/degraded work and resource demands from
the immutable pipeline specification. Existing fields remain compatible.

Live metrics are reduced from retained canonical events. DMR divides unique
missed tasks by unique evaluated tasks (committed or deadline elapsed), excluding
pending tasks. Counts apply to the retained event window, not session lifetime.
`wcrt_ms` is maximum observed task response time, not an analytical bound or
end-to-end pipeline response time. Undefined values are null.

The live dashboard automatically starts and offers pause/resume. Pausing stops
step requests and visual advancement; an already submitted request may finish.
Seeded experiment APIs and publication artifacts remain separate from live data.

The snapshot also adds `model_status`: predictor/estimator identities, effective
live threshold, session inference count, bounded host latency observations, and
the explicit federated mode `pretrained_snapshot`. Host observations are not
charged simulated execution costs and cannot establish a timing guarantee.

`step_canonical_events` adds cursor-based new canonical events to the snapshot;
the legacy `step_events` telemetry field remains available. The dashboard uses
the canonical field for its execution log, omitting periodic resource samples
from the short visible list. Sequence cursors remain monotonic across pruning.
