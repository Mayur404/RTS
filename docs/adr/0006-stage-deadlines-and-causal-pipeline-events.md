# ADR 0006: Stage deadlines and causal pipeline events

## Status

Accepted

## Context

The pipeline contract gives each task a relative deadline and the pipeline an
end-to-end deadline. A blocked successor has no execution release until all
predecessors commit. Treating its relative deadline as starting at the pipeline
release can make a late stage expire before it becomes ready. A scheduled
future pipeline also must not appear in the canonical event stream before its
release time.

## Decision

Source stages are released at the pipeline release. A successor is released at
the commit time of its last predecessor. Its absolute deadline is the earlier
of that release plus the stage relative deadline and the pipeline end-to-end
deadline. `PIPELINE_RELEASE` is emitted when its queue event is processed.
Local and remote stage results use one commit path; a remote result may release
successors only after it returns to the origin. A missed stage does not commit.

## Consequences

Stage relative deadlines retain their stated meaning, and every ready event
is causally ordered after its prerequisites. The pipeline can still miss its
end-to-end deadline, which remains a separate observed outcome. This decision
changes runtime deadline semantics and invalidates earlier pipeline metrics.
