# ADR 0004: Conditional Timing Certificates

- **Status:** Accepted
- **Date:** 2026-09-20

## Context

The prototype labels fallback as verified even though its one-pass timing estimate does not match the runtime scheduler, resource model, activation time, overhead, or interference behavior.

## Decision

1. The first supported analysis is constrained-deadline, single-resource, fully preemptive fixed-priority RTA.
2. Analysis uses integer time, explicit priorities, jitter, blocking, and bounded overhead.
3. RTA iterates to a fixed point and retains every iteration.
4. Unsupported scheduler/resource/self-suspension configurations return `UNSUPPORTED`; exhaustion returns `INCONCLUSIVE`.
5. Certificates bind to scenario, task set, scheduler, resource partition, hardware, overhead, and fallback configuration hashes.
6. Runtime may display `VERIFIED` only while every binding and assumption matches.
7. User-facing wording is “schedulable under certificate assumptions,” never physical-system “safe.”

## Consequences

- Current PredictiveRuntime and EDF configurations cannot receive a certificate until runtime semantics match a supported analyzer.
- EDF demand-bound analysis is deferred to a later, separate analysis type.
- Paper tables must render from certificate data or state `NOT CERTIFIED`.

