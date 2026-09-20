# ADR 0002: Execution Attempts and Single-Commit Semantics

- **Status:** Accepted
- **Date:** 2026-09-20

## Context

An offloaded task may be cancelled while a local fallback starts. Without separate attempt identities, a late remote return can race the fallback and mutate the same task twice.

## Decision

1. A logical task instance may own multiple execution attempts.
2. Every local, remote, and degraded execution receives a unique attempt identifier.
3. At most one attempt may commit the logical task’s result.
4. Cancellation changes attempt state; it does not directly complete the logical task.
5. Late results are recorded and discarded unless an explicitly configured first-valid-result policy permits the attempt to commit.
6. Metrics charge compute and network work for all attempts, including cancelled and discarded work.

## Consequences

- Offload and fallback logic becomes auditable.
- Wasted work becomes measurable.
- Lifecycle tests must include cancellation races and duplicate result delivery.

