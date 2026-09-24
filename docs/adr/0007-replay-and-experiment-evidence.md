# ADR 0007: Replay and experiment evidence

## Status

Accepted

## Context

The API v1 replay reducer previously assigned fixed CPU, GPU, temperature,
network latency, and six timestamp-based narrative stages to canonical events.
Those values were not recorded by the simulator event stream. A benchmark with
one paired seed also serialized undefined standard deviation as NaN, and its
"violations prevented" field hid regressions by clamping negative differences.

## Decision

Replay frames show only event-derived counters, fault state, offload state,
and latest event. Unobserved telemetry fields are null. The historical
showcase routes carry `DEMONSTRATION` evidence labels. Experiment manifests
record the actual predictor and remote estimator selected at runtime. A
single-run sample standard deviation is null. The baseline-minus-policy miss
difference remains signed.
An explicit `rts_predictive_gnn` policy loads saved weights and records their
SHA-256 digest and inference counts. The default policy remains identified as
a heuristic; saved weights are marked `UNVALIDATED`.

## Consequences

Existing clients must render null as unavailable. Old generated results and
replay frames are stale and must be regenerated before citation. The event
schema version is unchanged; the frame and manifest meanings changed.
