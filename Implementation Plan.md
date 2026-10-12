# PredictiveRuntime implementation specification

Read with [UI Design.md](UI%20Design.md), [research methods](docs/research_methods.md)
and [architecture decisions](docs/adr/). The [final research project](docs/research_project_final.tex)
defines the study; code, run configurations and manifests define executed behavior.

## Objective and boundaries

Provide reproducible paired simulations of heterogeneous edge devices executing
dependent real-time AI/control work. Compare baseline scheduling with predictive
placement, remote monitoring and conditionally admitted shorter local paths on
identical seeded releases, demands and faults. Preserve negative and zero effects.
Broader statistical and hardware validation remains research work.

The facility is presentation only. Physical motion, RF/5G coverage, semantic AI
accuracy and safety are not established. Configured work budgets, predicted bounds,
host measurements and analytical certificates are separate quantities.

## Architecture and contracts

- `rts_predictive/domain/`: immutable specifications, runtime identifiers, canonical
  events and schema versions. Shared changes require an ADR.
- `rts_predictive/simulator/research_engine.py`: finite event kernel, DAG readiness,
  CPU/GPU queues/service, memory, sender radios, cancellation and single commitment.
- `rts_predictive/predictors/`, `gnn/`, `federated/`: versioned inference, calibration,
  private observations, actual local training and federated estimator publication.
- `rts_predictive/verification/`: conditional analysis with explicit assumptions;
  reference CPU partitions do not certify dynamic EDF/GPU/offload execution.
- `rts_predictive/dashboard/`: event-derived snapshots, metrics and learning records.
- `rts_predictive/artifacts/`, `experiments/`: raw events, provenance, audits and
  statistical artifacts. Never invent samples or hard-code desired paper metrics.
- `rts_predictive/api/`: typed session/scenario APIs and retained compatibility APIs.
- `frontend/`: self-contained two-view facility and plain results.
- `scripts/`, `tests/`: training, experiments, independent replay and invariants.

Time and work are integer microseconds; rates are integer parts per million.
Successors become ready only after predecessor results commit at their origin.
Each stage deadline is bounded by its job's end-to-end deadline. A failed stage can
drop its workflow. Multiple attempts are allowed; at most one result commits.
Late/cancelled work remains accounted until real cancellation or lease resolution.

Use declared CPU/GPU/memory capacities, checkpoint boundaries, queue order and
payload-byte serialization. Decision, inference and federated work compete with
foreground tasks. Telemetry and thermal/utility behavior are configured assumptions.
Demand samples are hidden from prediction and keyed to scenario/task identities.

## Runtime control and learning

The GNN uses the current versioned task/resource graph, with explicit failure
handling. Candidate placement uses current rates, queues, memory, transport and a
remote estimator. A watchdog monitors remote attempts; local shorter paths require
matching conditional admission. Future workloads/faults can invalidate predictions.

Federated clients train on recorded local outcomes, transmit updates, aggregate
actual delivered participants and publish versions. CPU, radio and coordination
costs are modeled. No privacy or physical accuracy guarantee follows from FedAvg.
Custom fleet/workload calibration is unvalidated.

## Primary API and interface

- `POST /api/research/sessions`: create an EDF/protected pair or supported comparator.
- `GET /api/research/sessions/{id}`: detached canonical snapshot.
- `POST /api/research/sessions/{id}/step`: advance by validated integer microseconds.
- `DELETE /api/research/sessions/{id}`: close safely; concurrent retained references
  cannot continue a closed session.
- Scenario template/validation endpoints compile bounded inputs without silently
  changing schemas. Interactive fleets support up to eight devices.
- Completed artifact/evidence endpoints expose manifests, events, configuration,
  metrics and code/model archives. Incomplete results stay provisional.

Only Simulation and Results are visible. Device travel is illustrative; task,
resource, transfer, recovery and result projections use actual records. Prevented
misses join exact paired jobs; task recovery and whole-workflow rescue stay distinct.

## Verification and delivery

Test monotonic time, service conservation, sender serialization, memory/capacity,
precedence, deadline/terminal latches, cancellation, one commit and closed sessions.
Check model tensors and real private SGD/FedAvg independently. Audit raw checksums,
configuration identity, replay metrics and paired releases. Test adverse outcomes,
missing predictions/outputs, transport failures and boundary conditions.

Run targeted checks before the full suite in AGENTS.md. Browser acceptance checks
cover playback, pause/step, touch/keyboard camera, inspection, recovery, counts,
mobile containment and downloads. Never use desired paper numbers as test targets.

Generate evidence into ignored output directories. Keep runtime model bundles and
source in Git; preserve raw records and exact source/configuration manifests when
making empirical claims. Historical local studies are not included in a clone.
Publication needs broader calibrated workloads, seed-separated evaluation,
complete comparator/ablation studies, uncertainty, sensitivity and hardware-derived
budgets. Passing implementation checks is not universal or physical validation.
