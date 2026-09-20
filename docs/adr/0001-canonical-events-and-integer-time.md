# ADR 0001: Canonical Events and Integer Simulation Time

- **Status:** Accepted
- **Date:** 2026-09-20

## Context

The prototype mixes simulator telemetry, authored dashboard frames, and hard-coded publication values. Floating-point millisecond timestamps also make equal-time event ordering and deterministic replay harder to audit.

## Decision

1. Internal simulation time will use non-negative integer microseconds.
2. Events will be ordered by `(timestamp_us, priority, sequence)`.
3. Every event will carry a schema version, stable event identifier, run identifier, and typed payload.
4. The canonical event stream will be the sole input to metric reduction, replay-frame construction, dashboard state, and publication aggregation.
5. Human-facing APIs may format time in milliseconds, but serialized research artifacts retain integer microseconds.

## Consequences

- Existing float-millisecond code requires an incremental compatibility layer.
- Authored dashboard milestones must be replaced by event-derived milestones.
- Deterministic replay can be checked using canonical serialization and hashes.
- Schema evolution must be explicit and tested.

