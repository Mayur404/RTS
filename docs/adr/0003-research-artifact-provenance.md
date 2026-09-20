# ADR 0003: Research Artifact Provenance

- **Status:** Accepted
- **Date:** 2026-09-20

## Context

The legacy artifact generator embeds benchmark values and creates empirical-looking plots from scripted or randomly sampled data. Aggregate simulator output and paper-facing tables currently disagree.

## Decision

1. Every run receives an immutable run ID and versioned manifest.
2. Raw canonical events and decision records are persisted before metrics are reduced.
3. Metrics record units, numerator, denominator, eligibility rules, source event checksum, and warm-up/drain bounds.
4. Aggregate artifacts list all source run IDs and checksums.
5. Publication generation accepts a frozen aggregate ID and fails when data or provenance are missing.
6. Conceptual or scripted visuals are labeled `DEMONSTRATION` and kept separate from empirical figures.
7. Canonical uncompressed JSON is hashed; compression is a transport concern and does not change evidence identity.

## Consequences

- Existing paper tables and plots remain legacy demonstrations until regenerated.
- The dashboard must not supply fallback values when API metrics are missing.
- Tamper detection and metric recomputation become testable.

