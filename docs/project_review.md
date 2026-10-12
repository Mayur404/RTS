# Project review — 12 October 2026

The maintained application has two tabs: Simulation and Results. The repository
keeps the current facility renderer, event-driven runtime, model bundle, audit
tools, architecture decisions, methods, user guide and final LaTeX/PDF.

## Cleanup

Retired dashboard assets, duplicate paper/plot packages, old review folders and
intermediate handoff documents were removed from the publishable tree. Useful
timing, recovery and transfer assertions were migrated to the current UI. Tests
specific to retired views were removed; the watchdog observation auditor was
retained because it checks matching conditional certificates and admissions.

The root implementation and UI specifications now describe the current product.
Generated experiments, compilation files, caches and local agent/credential
folders are ignored. Development browser requirements are separate from runtime
requirements. The final research document retains exactly three references.

Original obsolete files and exact pre-cleanup versions of rewritten files remain
in an ignored, checksummed local backup under
`.validation/repository-cleanup-20261012/`. Historical raw training and experiment
evidence was preserved locally. These local archives are not included in a clone.

## Checks

After cleanup, the required full suite passed: **438 tests**, with 2,335 existing
PyTorch/PyG compatibility warnings on Python 3.14. The current UI/API targeted
suite passed 80 tests; the retained watchdog failure suite passed nine tests.
The test total excludes assertions for retired interfaces.

```powershell
.venv\Scripts\python.exe -m pytest tests -q --basetemp .pytest-tmp-agent
```

Four Playwright checks passed against the cleaned application: facility motion
and workflow dependencies, ground-map gestures and recovery visibility, automatic
playback and pause, and final deadline results. The results check reconciled the
displayed fallback/watchdog/early-exit counts with downloaded canonical records
and exercised the inconsistent-record warning. Browser evidence is local under
the cleanup validation directory. These are implementation checks, not a new
experimental benchmark or physical-system safety evidence.

## Scope and remaining limits

Cleanup introduces no runtime, event, scenario or model-bundle schema changes.
Existing runtime changes are documented in [architecture decisions](adr/).
The implementation assumes the configured simulated compute/link/fault models;
illustrative facility travel does not change scheduling. Custom workload budgets
need independent calibration. Historical empirical claims require their original
raw events and versioned manifests, which are not all shipped in Git.

See [research methods](research_methods.md) and
[publication scope](publication_readiness_review.md) for the evidence boundaries.

## Live connection lifecycle follow-up

Fixed historical watchdog arrows remaining on the map after recovery finishes.
The map now shows only active admitted watchdog recovery; terminal-task history
stays in the protection timeline. Active host indicators disappear from completed,
missed and skipped task nodes. Early-exit nodes explicitly show their canonical
outcome, and missing resource samples clear stale task-owner labels.

Live packet elements persist across observations. Repeated renders of an accepted
snapshot preserve animation identity; interrupted interpolation starts at the
displayed position. Pausing clears animations, completed packets are removed, and
completed runs have no live connections. Actual in-flight cancellation/result
traffic is retained until its canonical network event resolves.

The full suite passed **449 tests** (the same 2,335 dependency warnings). Chrome
checks passed for real packet lifecycle/animation continuity, recorded recovery
completion and final-map clearing, playback/pause, and facility/task layout.
Local evidence is under `.validation/live-connections-fix/`. This follow-up changes
presentation and checks only; runtime/API/event/model schemas and metrics are
unchanged. Device travel remains illustrative.
