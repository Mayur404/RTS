# PredictiveRuntime

A paired discrete-event simulator for distributed real-time AI workflows.
Compare EDF with predictive placement, watchdog monitoring and local early-exit
recovery on identical seeded workloads. Tasks, compute usage, transfers and results
come from canonical events.

## Run

From the repository root in PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe scripts\run_web.py
```

On an existing setup, run only the last command. Open the printed address, normally
http://localhost:8000. Stop with Ctrl+C.

## Simulation and Results

**Simulation** shows an illustrated facility with moving drones/rovers, live
simulated CPU/GPU usage and the exact resource-owning tasks. Drag devices, pan the
ground, wheel/pinch to zoom, or use Fit and Focus device. Inspect all a device's
workflow DAGs and their committed-predecessor arrows.

Choose 2–8 devices, task mix, 50–150% release rate and 0.05–3× playback speed.
Pause, step exactly 1 ms, or use Slow motion to inspect recorded watchdog/fallback/
early-exit milestones. Recovery stress injects explicit peer faults at 98 ms.
Travel is illustrative and does not alter scheduling or configured link timing.

**Results** explains on-time/missed/active workflows, simulation duration,
completion times, fallback-task outcomes, prevented and extra misses, and
per-device totals. A finished fallback task does not imply a saved workflow.
Active results stay provisional. Completed runs expose raw events, metrics,
checksummed manifests and source/model/configuration archives.

See the [user guide](docs/simulation_user_guide.md). API documentation is at `/docs`;
the primary interface is `/api/research/sessions`. Compatibility APIs remain,
but the retired dashboards are excluded from this repository.

## Research and evidence

- [Final standalone LaTeX](docs/research_project_final.tex) and [PDF](docs/research_project_final.pdf), with exactly three references.
- [Research methods](docs/research_methods.md), [publication scope](docs/publication_readiness_review.md), and [documentation index](docs/README.md).
- [Current review](docs/project_review.md) and [architecture decisions](docs/adr/).

Time/work use integer microseconds. At most one task result commits. GNN inference
and local SGD/FedAvg execute actual model calculations; resource service, thermal
effects, utility and communications remain configured simulation models.
Custom workload calibration is unvalidated. Measurements, predictions and
conditional certificates retain separate scopes. No physical-system safety,
RF/5G fidelity or universal deadline guarantee is claimed.

Generated runs belong under `.validation/` or `research_runs/` and are ignored by
Git. Historical raw training/developer evidence and obsolete-file backups remain
local. A clone includes runnable code/models and the final document, not every
historical experiment. Use each raw manifest/source archive when citing results.

## Checks

```powershell
.venv\Scripts\python.exe -m pytest tests -q --basetemp .pytest-tmp-agent
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe scripts\check_facility_scene.py --url http://127.0.0.1:8000 --output .validation/new-facility-check
.venv\Scripts\python.exe scripts\check_plain_results.py --url http://127.0.0.1:8000 --output .validation/new-results-check
.venv\Scripts\python.exe scripts\check_ground_map.py --url http://127.0.0.1:8000 --output .validation/new-recovery-check
.venv\Scripts\python.exe scripts\check_simple_playback.py --url http://127.0.0.1:8000 --output .validation/new-playback-check
.venv\Scripts\python.exe scripts\check_result_logic.py --output .validation/new-result-audit
```

Browser checks use Playwright and installed Google Chrome on Windows. Node.js is
needed for JavaScript invariant tests and the result audit. Start the app before
browser checks; use fresh output folders. Remove the pytest temporary directory
after the process exits. Additional independent model/trace checks are available
through `scripts/verify_runtime_end_to_end.py` and `scripts/verify_learning_stress.py`.
