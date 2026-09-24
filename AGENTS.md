# PredictiveRuntime Agent Rules

Read `Implementation Plan.md` and `UI Design.md` before making material changes.

## Scientific integrity

- Never hard-code experimental results into the dashboard, plot generators, tables, or paper artifacts.
- Never generate empirical-looking samples for a plot presented as measured or simulated evidence.
- Every reported metric must trace to a versioned run manifest and raw event record.
- Use “verified” only for a matching verification certificate and always preserve its assumptions.
- Do not claim physical-system safety from the simulator.
- Clearly distinguish simulated, predicted, measured, and analytical values.

## Architecture

- `rts_predictive/domain/` owns shared immutable specifications, runtime identifiers, canonical events, and schema versions.
- Simulation time is represented internally as integer microseconds.
- A task may have multiple execution attempts but at most one committed result.
- Canonical events are the source of truth for metrics, replay frames, dashboard state, and artifacts.
- Shared schema changes require an architecture decision record under `docs/adr/`.

## Coordination

- One writer owns a shared contract at a time.
- Subagents are read-only unless explicitly assigned a disjoint file set.
- Do not modify files outside the task’s stated ownership boundary.
- Do not silently change an API, event, scenario, result, or model-bundle schema.
- Keep generated results out of feature commits unless the task specifically regenerates a frozen artifact set.

## Testing

- Add meaningful tests for changed behavior and failure paths.
- Prefer invariants and behavioral assertions over tests that lock in desired paper numbers.
- Run targeted tests first, followed by:

```powershell
.venv\Scripts\python.exe -m pytest tests -q --basetemp .pytest-tmp-agent
```

- Remove the temporary test directory after the test process exits.

## Handoff

Every feature-agent handoff must include the commit hash, summary, files changed, tests executed,
schema or API changes, assumptions, and unresolved risks.

