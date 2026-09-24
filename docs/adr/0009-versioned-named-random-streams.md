# ADR 0009: Versioned named random streams

## Status

Accepted.

## Context

A single pseudo-random generator coupled task-release jitter to packet loss and
future stochastic mechanisms. Adding a draw in one mechanism could therefore
change unrelated outcomes for the same run seed.

## Decision

Simulator randomness is partitioned into named streams. Each stream seed is
derived with SHA-256 from the RNG schema version, root run seed, and stream
name. Run manifests record the version, root seed, and derived stream seeds.

The initial schema is `rts_predictive.rng/1`. Defined streams cover release
jitter, execution time, network loss, network latency, and fault injection.
Unknown named streams are derived by the same rule. Python's process-randomized
`hash()` is never used for seed derivation.

## Consequences

Runs remain reproducible within an RNG schema version, and adding random draws
to one domain does not alter another domain's sequence. Changing the derivation
or the meaning of a stream requires a new RNG schema version.
