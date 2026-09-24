# Predictive Runtime Research Prototype

This repository contains a discrete-event simulation prototype for distributed
real-time workloads. Its outputs are **simulated**. They do not establish safety
of any physical system.

## Run the project

From PowerShell in the repository root (`D:\Course\RTS2`), start the browser
console with the existing virtual environment:

```powershell
cd D:\Course\RTS2
.\.venv\Scripts\python.exe scripts\run_web.py
```

The app opens at `http://localhost:8000`. The live workspace has continuous
playback, a larger movable fleet view, an actual pipeline DAG, and a peer
interaction graph. Dragging nodes changes only their screen layout. The app
also contains a seeded experiment runner, canonical event inspector, model
inventory, and evidence guide. API documentation is at `http://localhost:8000/docs`.
Stop the server with Ctrl+C.

Each browser tab gets its own live simulation session. Live sessions are held in
memory and are cleared when the server stops.

To generate paper artifacts separately:

```powershell
.\.venv\Scripts\python.exe scripts\generate_paper_artifacts.py
```

To check the installation, run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q --basetemp .pytest-tmp-agent
```

If `.venv` is absent, create it first with `py -3 -m venv .venv`, then run
`.\.venv\Scripts\python.exe -m pip install -r requirements.txt`.

The publication artifact command writes to `research_runs/`: canonical `.jsonl` event records,
versioned run manifests, a LaTeX table, and 300 DPI PNG and vector PDF plots.
Metrics and figures in this pipeline are reduced from those event records.
The browser console uses the FastAPI service's `/api/live` and `/api/v1/runs`
endpoints. Run exports include the canonical events and in-session provenance.

## Evidence boundaries

- Fixed-priority response-time analysis is implemented in
  `rts_predictive/verification/timing_analyzer.py`. A `VERIFIED` result applies
  only to the task set and assumptions bound to its certificate.
- The simulator currently retains some floating-point millisecond execution
  state. Integer-microsecond event timestamps at the artifact boundary do not
  make the entire simulator an exact integer-time model.
- The default `rts_predictive` benchmark loads integrity-checked GNN and
  federated bundles. Their calibration and evaluation use simulator rollouts
  with disjoint seeds; this is simulated model evidence, not hardware evidence
  or a physical safety certificate.
- GNN prediction events record calibrated probability, predicted time to
  violation, cause attribution, model source, and observed host inference
  latency. Run manifests record both component identities and weight hashes.
- Dashboard replay is reduced from canonical events. Resource values remain
  unavailable unless a `RESOURCE_SAMPLE` event recorded them.

The architecture and design specifications are in [Implementation Plan.md](Implementation%20Plan.md)
and [UI Design.md](UI%20Design.md). Schema and evidence decisions are in `docs/adr/`.
The formulas and their current scope are documented in `docs/mathematical_audit.md`.
