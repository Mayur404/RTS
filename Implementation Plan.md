# GhostGuard Research-Grade Implementation Plan

**Project:** Predictive Runtime Protection for Distributed Real-Time AI Systems  
**Working name:** GhostGuard  
**Document status:** Implementation specification  
**Primary source:** `report` (project proposal)  
**Companion specification:** `UI Design.md`

## 1. Intended Outcome

Build a reproducible research prototype that can support the following carefully bounded claim:

> Under explicitly configured task, compute, interference, and network models, a calibrated predictive arbiter can reduce firm real-time deadline misses by choosing among local execution, feasible neighbor offload, and an analytically checked degraded/early-exit mode, while keeping its own decision overhead within a measured budget.

The completed project must provide four things from one consistent source of truth:

1. A deterministic, validated discrete-event simulator for heterogeneous edge nodes and DAG workloads.
2. A genuinely integrated predictor, federated remote-latency estimator, runtime arbiter, watchdog, and early-exit fallback.
3. A statistically defensible experiment suite with raw results, confidence intervals, ablations, sensitivity studies, and machine-readable provenance.
4. An interactive research dashboard that visualizes actual simulator events and clearly distinguishes measured, simulated, predicted, and analytically verified values.

The dashboard is a research inspection tool, not the source of experimental truth. Publication tables and plots must be generated from raw experiment artifacts, never from constants embedded in UI or plotting code.

## 2. Scope and Claim Boundaries

### In scope

- Periodic and optional sporadic DAG jobs with release times, precedence constraints, per-stage deadlines, end-to-end deadlines, criticality, and valid early-exit boundaries.
- Heterogeneous CPU/GPU nodes with separate queues, bounded concurrency, preemption rules, memory pressure, contention, and thermal derating.
- Wireless links with serialization time, propagation/base delay, stochastic jitter, packet loss, retry policy, and time-varying availability.
- Local scheduling, offloading, remote monitoring, cancellation, result return, and local recovery.
- A compact GNN or graph-aware model that predicts deadline-miss risk and time-to-violation from information available at decision time.
- A federated model that estimates remote execution latency and reliability from decentralized client traces.
- Fixed-priority response-time analysis for the degraded task set under documented assumptions. EDF demand-bound analysis may be added as a separate verification mode.
- Repeated simulation experiments, deterministic replay, seed-separated model evaluation, ablation studies, and publication artifact generation.

### Out of scope for the paper claim

- Physical robot safety certification.
- Claims about real RF multipath, cache interference, kernel scheduling, or GPU driver behavior unless hardware measurements are added.
- A claim that federated learning provides differential privacy. FedAvg alone does not provide that guarantee.
- Universal “zero deadline miss” or “guaranteed safe” language. Verification is conditional on the modeled task set, WCETs, scheduler, blocking assumptions, and overhead bounds.
- Accuracy/utility claims for degraded AI output unless a real model and task-quality metric are evaluated.

## 3. Current Repository Audit

The repository is a useful prototype, but several current results are demonstration artifacts rather than research-grade evidence. Preserve working behavior while addressing the following gaps.

| Area | Present now | Research-grade gap | Required disposition |
|---|---|---|---|
| Simulator | Event queue, periodic releases, devices, load/thermal state, schedulers | Stages are independently periodic rather than released through true DAG precedence; repeated `run()` calls can inject monitoring ticks again; resource and remote completion semantics need stronger invariants | Refactor around immutable scenario specs, DAG job instances, a monotonic run horizon, and explicit lifecycle events |
| Scheduling | FIFO, RM, EDF, reactive, always-offload, predictive-no-fallback, GhostGuard | Scheduler semantics are simplified; overhead is not charged consistently; some offload paths can rely on estimated completion events instead of actual remote completion | Define dispatch/preemption contracts and charge every decision/context/communication cost |
| Predictor | GNN architecture and saved weights exist | Runtime scheduler normally uses a heuristic surrogate because no predictor is injected; exceptions silently fall back; dataset labels are heuristic rather than observed counterfactual future outcomes | Add a versioned inference adapter, fail-visible fallback, rollout-derived labels, calibration, and latency measurements |
| Dataset | Disjoint seed lists | A seed split alone does not prevent correlated snapshots of the same run crossing evaluation procedures; labels use current slack/load rules | Split by scenario family and seed before sampling; label from future no-intervention rollouts; publish class balance and leakage checks |
| Federated learning | Client/server FedAvg code and standalone result file | Not connected to normal simulation runs; no modeled FL traffic/interference/staleness; no real ablation effect | Integrate model snapshots into candidate scoring and schedule FL work as explicit background events |
| Ablations | Six named configurations | `gnn` and `fl` flags currently do not alter scheduler construction, so multiple rows are identical by construction | Use typed feature flags and assert that every ablation changes the executed component graph |
| Early exit | Remaining work is proportionally clamped to degraded WCET | No task-specific structural exit boundaries or quality/utility value | Model discrete checkpoints, checkpoint cost, valid output, remaining WCET, and utility score |
| Verification | Utilization and interference calculation | Analyzer is described as exact RTA but uses a one-pass deadline-based bound; `scheduler_type` is unused; blocking, jitter, overhead, and convergence are missing | Implement iterative RTA to a fixed point and report assumptions/counterexamples; add EDF analysis only if needed |
| Experiment results | Summary JSON, figures, tables | Current aggregate results conflict with the README demonstration table; several paper plots/tables contain hard-coded or sampled values | Regenerate every artifact from raw run records with a provenance manifest |
| Dashboard | Attractive single-page mesh, scrubber, Gantt, controls | Several stages, values, and narrative milestones are authored in the tracer instead of derived from the simulator log; wording overstates guarantees | Drive frames from canonical events and use evidence labels defined in `UI Design.md` |
| Tests | 24 tests pass when pytest uses a writable `--basetemp` | Tests validate many fixed demonstration numbers and do not yet cover conservation, causality, replay hashes, real ablation wiring, or statistical artifacts | Add property/invariant, contract, golden-replay, and experiment-provenance tests |

Baseline verification performed during planning:

```powershell
.venv\Scripts\python.exe -m pytest tests -q --basetemp .pytest-tmp-plan
# 24 passed
```

The test result confirms current consistency; it does not validate the scientific claims above.

## 4. Research Questions and Success Criteria

### RQ1 — Deadline reliability

Does GhostGuard reduce total and critical deadline-miss ratio compared with local FIFO, RM, EDF, always-offload, reactive degradation, and predictive offload without fallback?

- **Primary endpoint:** critical deadline-miss ratio.
- **Secondary endpoints:** total DMR, p95/p99 response time, maximum observed lateness, jitter, and task utility.
- **Success condition:** lower mean critical DMR than the strongest baseline under at least the bursty, thermal, and unreliable-neighbor families, with a 95% confidence interval for paired improvement reported.

### RQ2 — Prediction usefulness

Does the learned predictor provide enough calibrated lead time to enable a feasible intervention?

- Metrics: AUROC, AUPRC, recall at the selected operating point, Brier score, expected calibration error, time-to-violation MAE, mean/median lead time, and intervention opportunity rate.
- Success condition: the chosen threshold is selected on validation data only; test recall and calibration are reported with inference latency and graph size.

### RQ3 — Component contribution

Which gains come from prediction, federated estimation, reliability filtering, offloading, watchdog monitoring, and fallback?

- Use executable ablations, not label-only configurations.
- Report paired per-seed changes and intervention counts so a lower DMR caused by excessive degradation is visible.

### RQ4 — Cost of protection

What compute, network, energy proxy, and output-quality cost is paid for improved timing?

- Metrics: decision overhead, scheduler utilization, bytes transmitted, wasted remote work, fallback rate, early-exit rate, normalized output utility, FL traffic, and background interference.
- Report Pareto curves rather than claiming one threshold is universally optimal.

### RQ5 — Conditional schedulability

Are configured degraded modes schedulable under their stated fixed-priority assumptions?

- Success condition: iterative RTA converges to `R_i <= D_i` for every task claimed to be verified, including release jitter, blocking, and bounded runtime overhead where applicable.
- The runtime may display “verified for configuration `<hash>`”; it must not generalize the result beyond that configuration.

## 5. Target Architecture and Source of Truth

```text
Scenario YAML/JSON + seed + code revision
                  |
                  v
        Scenario compiler/validator
                  |
                  v
         Discrete-event simulator
       /       |         |        \
 task DAG   resources   network   FL background events
       \       |         |        /
                  v
         canonical event stream
                  |
       +----------+-----------+
       |                      |
       v                      v
 metrics reducer       replay/frame reducer
       |                      |
       v                      v
 raw run record          dashboard API
       |
       v
 statistical aggregation -> tables/plots/paper manifest
```

No dashboard reducer may invent a state transition. No plot generator may synthesize observations when it is presented as an empirical result.

### Recommended package boundaries

```text
ghostguard/
  domain/          # immutable specifications, IDs, enums, validation
  simulator/       # event loop, lifecycle reducers, clocks, RNG streams
  workloads/       # DAG templates, release generators, early-exit profiles
  resources/       # CPU/GPU/memory/thermal models
  network/         # links, transmissions, loss/retry, topology
  predictors/      # GNN adapter, heuristic baseline, calibration
  federated/       # client learning, aggregation, staleness, FL events
  policies/        # scheduling and arbitration policies
  verification/    # fixed-priority RTA and optional EDF DBF
  experiments/     # matrix expansion, execution, aggregation, statistics
  artifacts/       # tables, plots, manifests
  api/             # validated run/replay/compare endpoints
frontend/          # research dashboard defined in UI Design.md
configs/           # versioned scenario and experiment specifications
results/           # generated, never hand-edited research artifacts
```

An incremental migration is preferred; existing import paths can be retained through compatibility wrappers until tests are moved.

## 6. Canonical Domain Model

### 6.1 Immutable specifications

Use frozen dataclasses or validated Pydantic models for:

- `TaskSpec`: task type, resource demand, period/minimum inter-arrival time, relative deadline, criticality, preemption mode, payload sizes, nominal WCET distribution, degraded alternatives, and output utility.
- `PipelineSpec`: DAG nodes, dependency edges, source release model, end-to-end deadline, drop/skip policy, and sink task.
- `ExitPointSpec`: checkpoint ID, elapsed-work interval, checkpoint overhead, remaining WCET, output utility, and whether it produces a structurally valid result.
- `DeviceSpec`: CPU/GPU capacities, concurrency, memory, speed factors, thermal constants, and scheduler.
- `LinkSpec`: directed endpoints, bandwidth, base latency, jitter distribution, loss model, retry limit, and availability process.
- `FaultSpec`: target, onset, duration, shape, severity, and correlation group.
- `ScenarioSpec`: schema version, duration, warm-up, drain interval, fleet, pipelines, faults, seed, and instrumentation level.
- `PolicySpec`: policy name/version and all thresholds.
- `ExperimentSpec`: scenarios, policies, seed list, repetitions, metrics, and output path.

All specs receive a stable SHA-256 configuration hash after canonical JSON serialization.

### 6.2 Runtime entities

- `PipelineJob`: one source release and its end-to-end deadline.
- `TaskInstance`: one stage of one pipeline job; initially blocked until predecessors complete.
- `ExecutionAttempt`: local or remote attempt with a unique ID. A task may have multiple attempts but at most one committed result.
- `Transmission`: request or result transfer with byte count and link snapshot.
- `DecisionRecord`: risk prediction, candidate estimates, rejected reasons, selected action, and overhead.
- `VerificationCertificate`: configuration hash, analysis type, assumptions, per-task iteration trace, outcome, and analyzer version.

### 6.3 Task lifecycle

```text
BLOCKED -> READY -> DISPATCHED -> RUNNING -> CHECKPOINT* -> COMPLETED -> COMMITTED
                  \-> TRANSMITTING -> REMOTE_READY -> REMOTE_RUNNING --/
RUNNING/CHECKPOINT -> DEGRADED_RUNNING -> COMPLETED
TRANSMITTING/REMOTE_RUNNING -> CANCEL_REQUESTED -> CANCELLED or LATE_REMOTE_RESULT_DISCARDED
Any unfinished state at deadline -> DEADLINE_MISSED
```

Required invariants:

- One task has at most one committed output.
- A successor cannot become ready before all required predecessor outputs are committed.
- Simulation time never moves backward.
- Remaining work never becomes negative.
- A cancelled attempt cannot later complete as a successful committed attempt.
- Network bytes, compute service time, and scheduler overhead are conserved in metrics.
- All stochastic draws come from named seeded RNG streams and are recordable for replay.

## 7. Simulator Implementation Logic

### 7.1 Event loop

Use a priority queue ordered by `(timestamp_ns, event_priority, insertion_sequence)`. Integer microseconds or nanoseconds avoid cumulative floating-point ordering errors while the UI can continue displaying milliseconds.

Core event types:

- `PIPELINE_RELEASE`, `TASK_READY`, `DISPATCH_DECISION_START`, `DISPATCH_DECISION_END`
- `EXECUTION_START`, `EXECUTION_QUANTUM_END`, `PREEMPT`, `CHECKPOINT_REACHED`
- `REQUEST_TX_START`, `REQUEST_TX_END`, `REMOTE_EXECUTION_START`, `RESULT_TX_START`, `RESULT_TX_END`
- `WATCHDOG_TICK`, `CANCEL_REQUEST`, `CANCEL_ACK`, `LATE_RESULT_DISCARDED`
- `DEADLINE`, `TASK_COMMIT`, `PIPELINE_COMPLETE`, `PIPELINE_DROP`
- `FAULT_START`, `FAULT_END`, `THERMAL_UPDATE`, `LINK_STATE_CHANGE`
- `FL_LOCAL_TRAIN_START/END`, `FL_UPLOAD_START/END`, `FL_AGGREGATE`, `MODEL_PUBLISH`

The simulation must support `run_until(t)` without re-adding old periodic events. Schedule instrumentation ticks once or derive frames after the run from events.

### 7.2 CPU/GPU service model

- Maintain separate resource queues and capacities.
- State whether GPU work is non-preemptive, preemptive only at layer boundaries, or time-sliced. Use the chosen rule in both simulation and verification assumptions.
- Compute delivered service from base speed, active concurrency, injected contention, memory pressure, and thermal multiplier.
- Charge dispatch, preemption, graph construction, model inference, serialization, and context-switch costs as work on the correct resource.
- Sample execution demand once per attempt from a configured bounded distribution; record both sampled demand and declared WCET.
- Validate that no sampled execution time exceeds WCET unless the scenario explicitly models a WCET violation.

### 7.3 DAG release semantics

- Release only source stages at the pipeline release time.
- Release each downstream stage when dependencies commit; optionally add communication/copy cost between resources.
- Support per-stage relative deadlines and an end-to-end absolute deadline.
- Define behavior when a predecessor misses: drop job, use stale data, or activate a degraded path. This must be scenario data, not scheduler-specific hidden logic.

### 7.4 Network model

For a directed link `i -> j`:

`T_tx = queue_wait + base_latency + payload_bits / effective_bandwidth + jitter + retry_delay`

- Sample outbound and return paths separately; do not multiply one sampled delay by two.
- Queue simultaneous transfers on shared channel capacity.
- Record packet loss and retry/cancellation behavior.
- Update neighbor estimates from completed outcomes only; distinguish censored/aborted samples.
- Model cancellation latency. Local fallback can start immediately if configured, but remote compute remains charged until cancellation is observed.

### 7.5 Thermal and contention model

- Use a documented first-order thermal model or an explicitly labeled trace-driven derating function.
- Calibrate nominal constants from literature or hardware measurements where possible.
- Separate endogenous load from exogenous injected contention.
- Include correlated faults as a scenario-level process so origin and peer shocks can share a cause.

### 7.6 Early-exit implementation

Replace proportional work clamping with task-specific valid boundaries:

```text
Exit E0: full model       WCET 15.0 ms, utility 1.00
Exit E1: branch head 2    WCET  9.0 ms, utility 0.91
Exit E2: branch head 1    WCET  5.0 ms, utility 0.79
Exit E3: safety heuristic WCET  2.5 ms, utility 0.55
```

At each checkpoint, compute a conservative finish bound including checkpoint overhead and higher-priority interference. Select the highest-utility exit whose bound meets the deadline. If none is feasible, execute the configured minimum safety action and record an unavoidable miss; never silently mark it safe.

## 8. Prediction Pipeline

### 8.1 Prediction target

At decision time `t`, predict whether the selected task or pipeline will miss within horizon `H` under the reference “continue current policy with no GhostGuard intervention” trajectory. This counterfactual definition prevents the label from being changed by the intervention it triggers.

For each sampled state:

1. Snapshot the simulator, including all RNG states.
2. Fork a no-intervention reference rollout to `min(deadline, t + H)`.
3. Label `y_miss` from the observed outcome.
4. Label `y_ttv` from the first irreversible violation or deadline event; use censoring metadata if no violation occurs in the horizon.
5. Label the dominant cause from accumulated blocking/service attribution, not from a load threshold.

Store the scenario ID, seed, timestamp, task ID, configuration hash, and feature schema version with every sample.

### 8.2 Graph schema

Recommended node types:

- task instance
- CPU queue/resource
- GPU queue/resource
- device
- directed network link or peer summary

Recommended edges:

- `depends_on`
- `queued_on`
- `running_on`
- `contends_with`
- `located_on`
- `reachable_via`

Features must be causally available at time `t`: remaining work estimate, absolute/normalized slack, age, criticality, queue position, demand, resource utilization, temperature/derating, link statistics, estimator staleness, and peer reliability. Normalize using training-split statistics saved with the model.

### 8.3 Training and evaluation

- Split first by scenario family and seed; then generate snapshots. Never randomly split adjacent snapshots.
- Keep a final extrapolation set with unseen fault severity or fleet size.
- Handle imbalance with class weights or balanced sampling, but report the natural test prevalence.
- Select architecture and threshold on validation data only.
- Calibrate probabilities with temperature scaling or isotonic regression fitted on validation data.
- Save weights, normalization constants, feature schema, calibration object, threshold, training config, dependency versions, and data-manifest hash as one model bundle.
- Benchmark inference after warm-up for multiple graph sizes. Report median, p95, p99, maximum observed latency, hardware/OS, and number of threads.
- The scheduler must expose which predictor was used: `gnn`, `heuristic`, or `unavailable`. Silent exception fallback is prohibited.

### 8.4 Runtime adapter contract

```python
Prediction(
    miss_probability: float,
    ttv_ms: float | None,
    cause_probabilities: dict[str, float],
    inference_us: int,
    model_version: str,
    calibrated: bool,
)
```

If inference fails or exceeds its budget, record the failure and execute a declared fail-safe policy. The experiment matrix must include this behavior.

## 9. Federated Remote Estimation

### 9.1 Model and output

Predict a distribution or upper quantile of remote completion latency plus completion probability. Candidate selection needs a conservative upper bound, not only a mean.

Suggested outputs:

- `q50_exec_ms`, `q95_exec_ms`
- `p_success_before_deadline`
- calibration/uncertainty measure
- model version and age

### 9.2 Federated protocol

- Partition traces non-IID by device hardware, workload, and link conditions.
- Model client availability and minimum sample count.
- Run local training, upload, aggregation, download, and activation as timestamped background events.
- FedAvg weights by actual local sample count; report client participation and staleness.
- Charge CPU/GPU time and bytes to the simulator.
- Compare against local-only, static specification, stale federated, current federated, and centralized pooled reference models.
- Do not call centralized training an “upper bound” unless it is empirically so for the evaluated run; call it a pooled-data reference.

## 10. Runtime Arbitration Logic

For a task `i` at time `t`:

1. Charge graph construction and predictor overhead.
2. If prediction is below the validated threshold and conservative local finish bound is feasible, schedule locally.
3. Otherwise enumerate eligible neighbors and calculate, for each candidate `j`:

   `B_offload(j) = q95(T_send) + q95(T_queue,j + T_exec,j) + q95(T_return) + O_decision + margin`

4. Reject a candidate when reliability is too low, estimate is stale, memory/model capability is insufficient, or `t + B_offload(j) > d_i`.
5. Compare feasible offload utility with feasible local exit options. Select the highest expected utility subject to the timing constraint; use deterministic tie-breaking.
6. Create an `ExecutionAttempt` and arm a watchdog at the earliest of:
   - predicted latest-safe-abort time,
   - link/peer heartbeat deadline,
   - next remote checkpoint.
7. At watchdog time, recompute the conservative completion bound. Continue only if the remote attempt is still feasible.
8. If aborted, start the highest-utility locally feasible exit, send cancellation, and discard any late remote result unless it wins an explicitly allowed first-valid-result race.

Every decision emits a record containing accepted and rejected candidates, estimates, margins, chosen action, and overhead. This record is essential for debugging and the UI decision inspector.

## 11. Formal Timing Verification

### 11.1 Fixed-priority iterative RTA

For each task `i`, define execution cost `C_i`, blocking `B_i`, release jitter `J_i`, scheduler/predictor overhead `O_i`, and higher-priority tasks `hp(i)`.

Initialize:

`R_i^(0) = C_i + B_i + O_i`

Iterate:

`R_i^(k+1) = C_i + B_i + O_i + sum_{j in hp(i)} ceil((R_i^k + J_j) / T_j) * (C_j + O_j)`

Stop when:

- `R_i^(k+1) == R_i^k`: converged; verified if `R_i <= D_i`.
- `R_i^(k+1) > D_i`: not schedulable.
- iteration limit reached: inconclusive/error, never “verified.”

Use integer time units. Produce the full iteration trace for audit. If GPU non-preemption creates blocking, include the maximum relevant lower-priority critical section in `B_i`.

### 11.2 Verification modes

- `FP_PREEMPTIVE`: exact constrained-deadline RTA under the declared assumptions.
- `FP_WITH_BLOCKING`: RTA with non-preemptive sections.
- `EDF_DBF`: processor-demand test for supported task models.
- `SIMULATION_ONLY`: no analytical certificate; UI must say so.

The analyzer must reject mismatches, such as requesting EDF verification while using a fixed-priority equation.

### 11.3 Certificate contents

- scenario/configuration hash
- task parameters and priorities
- overhead and blocking bounds
- scheduler and analysis type
- assumptions
- per-task iterations, WCRT, deadline, margin, and status
- analyzer version and generation timestamp

## 12. Experimental Design

### 12.1 Factors

Use a preregistered matrix with at least:

- Fleet size: 2, 4, 6, 8
- Offered utilization: low, medium, high, overload
- Fault family: nominal, bursty CPU, bursty GPU, thermal, link jitter/loss, unreliable peer, correlated origin/peer fault
- Fault severity and duration: at least three levels each
- Network quality: at least three bandwidth/jitter regimes
- Workload: multiple DAG widths/depths and criticality mixes
- Scheduler/policy: all seven baselines plus full GhostGuard

Use at least 30 paired test seeds per cell where runtime permits. If fewer are used, justify power/precision and report wide uncertainty honestly. Run warm-up and drain intervals so boundary censoring is not counted as a miss.

### 12.2 Baseline fairness

- Give all policies the same scenario realization, task demands, link samples, and initial state through common random numbers.
- Charge each policy’s decision overhead.
- Tune baseline thresholds on validation scenarios, not test scenarios.
- Ensure “always offload” dispatches a task once, not repeatedly at each scheduler callback.
- Ensure reactive fallback has a realistic observation delay.
- Use the same degraded execution profiles across policies that are allowed fallback.

### 12.3 Required ablations

- Full GhostGuard
- Without GNN: documented heuristic predictor
- Without FL: static/specification estimator
- Without offloading
- Without watchdog
- Without local fallback/early exit
- Without neighbor reliability filter
- Without probability calibration
- Without charging decision overhead (diagnostic only)

Each ablation must have a component-graph assertion proving the intended module is absent or replaced.

### 12.4 Metrics

Primary:

- total DMR and critical DMR
- per-pipeline end-to-end DMR
- p50/p95/p99 response time and maximum observed lateness
- output utility delivered on time

Mechanism:

- offload attempts, admission rate, timely success rate, cancellation rate
- fallback and early-exit rate by exit point
- watchdog true/false interventions
- prediction lead time and calibration
- decision/inference p50/p95/p99/max overhead
- FL accuracy, q95 error, bytes, compute time, and model age
- wasted local/remote compute and network bytes

Statistical reporting:

- per-seed raw values
- mean/median and 95% bootstrap confidence intervals
- paired effect sizes against the strongest baseline
- two-sided paired test where appropriate, with multiple-comparison correction for families of comparisons
- number of runs, seeds, exclusions, and failures

Avoid reporting only a single deterministic showcase. Keep it as a walkthrough, separate from hypothesis-testing results.

## 13. Artifact and Provenance Contract

Every run directory should contain:

```text
results/runs/<run_id>/
  manifest.json
  scenario.json
  events.jsonl.zst
  decisions.jsonl.zst
  metrics.json
  verification.json           # when applicable
  stdout.log
```

`manifest.json` must include:

- run ID, UTC timestamp, completion status
- git commit and dirty-tree flag
- configuration/model/data hashes
- policy version and seed
- Python and dependency versions
- platform and processor description
- command line
- artifact checksums

Aggregate artifacts must list all source run IDs. Plot scripts read raw/aggregated data and fail if required fields are absent. They must not provide plausible default numbers.

Publication output:

```text
results/aggregates/<experiment_id>/summary.parquet
results/aggregates/<experiment_id>/statistics.json
results/paper/figures/*.pdf
results/paper/figures/*.png
results/paper/tables/*.tex
results/paper/provenance.json
```

## 14. API Contracts

### Core endpoints

- `POST /api/v1/runs` — validate a scenario and start a run; returns `202` plus `run_id`.
- `GET /api/v1/runs/{run_id}` — state, progress, manifest summary, and errors.
- `GET /api/v1/runs/{run_id}/events?from_us=&to_us=&types=` — canonical paginated event stream.
- `GET /api/v1/runs/{run_id}/frames?resolution_us=` — server-reduced replay frames.
- `GET /api/v1/runs/{run_id}/metrics` — final metrics with evidence type and units.
- `POST /api/v1/compare` — run IDs/policies and requested metrics; returns aligned comparison data.
- `GET /api/v1/models` — predictor bundles, versions, calibration, and measured latency.
- `GET /api/v1/verification/{config_hash}` — verification certificate.
- `GET /api/v1/experiments/{experiment_id}` — aggregate status and artifacts.

Validate ranges and enum values. Do not use permissive CORS in production mode. Return structured errors with `code`, `message`, `field`, and `details`.

## 15. Phased Delivery Plan

### Phase 0 — Freeze claims and make results honest

**Work**

- Add a `RESEARCH_STATUS.md` or README section distinguishing demonstration artifacts from validated results.
- Remove unconditional “guaranteed,” “100% safe,” and “measured” wording where evidence is synthetic or conditional.
- Mark the current Section 12 walkthrough as a deterministic demonstration.
- Add configuration and event schema versions.

**Acceptance gate**

- No generated paper claim depends on a literal benchmark number in Python, JavaScript, HTML, or LaTeX templates.

### Phase 1 — Canonical domain model and simulator invariants

**Work**

- Introduce immutable specs and runtime attempt IDs.
- Implement DAG dependency release and end-to-end jobs.
- Make `run_until()` monotonic and idempotent with respect to instrumentation.
- Implement single-commit and cancellation semantics.
- Add named RNG streams and replay hashes.

**Tests**

- Unit tests for every lifecycle transition.
- Property tests for monotonic time, no double commit, conservation of service, and deterministic replay.
- Golden trace for a minimal two-task DAG.

**Acceptance gate**

- Two identical runs produce byte-identical canonical event streams after excluding timestamps in the manifest.

### Phase 2 — Resource, network, and early-exit fidelity

**Work**

- Separate CPU/GPU queues and define preemption boundaries.
- Add shared-channel transmission queues, independent request/return samples, loss/retry, and cancellation cost.
- Replace proportional degradation with explicit exit points and utility.
- Add bounded overhead and thermal model parameters.

**Acceptance gate**

- Hand-calculated micro-scenarios match simulator completion times; early exit occurs only at declared boundaries.

### Phase 3 — Exact conditional verification

**Work**

- Implement iterative fixed-priority RTA with blocking, jitter, and overhead.
- Add certificate generation and invalid-assumption checks.
- Optionally implement EDF demand-bound analysis as a separately tested analyzer.

**Acceptance gate**

- Analyzer matches textbook task sets and intentionally rejects unschedulable and unsupported configurations.

### Phase 4 — Research dataset and predictor

**Work**

- Implement simulator snapshot/fork support.
- Generate counterfactual rollout labels.
- Version graph schema and normalization.
- Train, calibrate, evaluate, and package the compact model.
- Implement runtime adapter and explicit fallback behavior.

**Acceptance gate**

- Test data contain no training scenario/seed groups; model bundle is reproducible from a data manifest; runtime records actual model version and latency.

### Phase 5 — Federated integration

**Work**

- Produce local training samples from completed attempts.
- Schedule local training and communication as background workload.
- Publish versioned global snapshots atomically.
- Use q95 latency and reliability outputs in candidate scoring.

**Acceptance gate**

- Enabling/disabling FL changes executed events and candidate estimates; FL cost appears in resource and byte metrics.

### Phase 6 — Arbiter and baseline correctness

**Work**

- Implement conservative local/offload/exit bounds.
- Add latest-safe-abort watchdog logic.
- Implement typed feature flags for every ablation.
- Audit every baseline for single dispatch and equal-cost accounting.

**Acceptance gate**

- Each action is reconstructable from its decision record; ablation component assertions pass; late remote returns cannot double-complete a task.

### Phase 7 — Experiment harness and statistics

**Work**

- Add versioned YAML experiment specs and matrix expansion.
- Run paired seeds in parallel processes while retaining deterministic per-run state.
- Add checkpoint/resume and failure reporting.
- Aggregate with confidence intervals, effect sizes, and sensitivity plots.

**Acceptance gate**

- A clean checkout can reproduce a small smoke experiment and its checksums with one command; full experiment artifacts contain complete provenance.

### Phase 8 — Research dashboard

Implement the screens, visual semantics, accessibility, and data contracts in `UI Design.md`.

**Acceptance gate**

- Every rendered transition is traceable to a canonical event; evidence badges and units appear; keyboard and responsive acceptance checks pass.

### Phase 9 — Paper package and reproducibility release

**Work**

- Generate final tables/figures from frozen run IDs.
- Update paper methods, assumptions, limitations, and threats to validity.
- Add environment lockfile, exact commands, artifact index, and data/model cards.
- Perform a clean-machine reproduction rehearsal.

**Acceptance gate**

- A reviewer can map every headline number to aggregate data, source runs, scenario/config hashes, and raw events.

## 16. Suggested Six-Week Execution Schedule

| Week | Primary delivery | Parallel supporting work |
|---|---|---|
| 1 | Phases 0–1: claim audit, schemas, lifecycle invariants | UI information architecture and scenario schema |
| 2 | Phase 2: resource/network/early-exit fidelity | RTA textbook fixtures |
| 3 | Phases 3–4: verification and rollout dataset | Predictor benchmark harness |
| 4 | Phases 5–6: FL integration and arbiter/baselines | API v1 and replay reducer |
| 5 | Phases 7–8: pilot experiment and dashboard | Accessibility and artifact provenance |
| 6 | Phase 9: full runs, statistics, paper figures, reproduction | Threats-to-validity review and demo rehearsal |

If the deadline is shorter, prioritize simulator correctness, actual GNN integration, true ablations, iterative RTA, and artifact provenance. A smaller honest experiment is stronger than a large polished experiment generated from inconsistent data.

## 17. File-Level Work Map

| Existing path | Planned responsibility/change |
|---|---|
| `ghostguard/config.py` | Split validated immutable specs from runtime state; retain compatibility exports |
| `ghostguard/simulator/engine.py` | Monotonic event loop, DAG release, lifecycle events, RNG/replay |
| `ghostguard/simulator/tasks.py` | Pipeline jobs, attempts, exit points, single-commit semantics |
| `ghostguard/simulator/resources.py` | Separate queue/capacity, overhead, calibrated thermal/service models |
| `ghostguard/schedulers/ghostguard.py` | Pure decision policy using predictor/estimator interfaces and bound calculator |
| `ghostguard/gnn/dataset.py` | Snapshot/fork rollout labels and manifest-backed splits |
| `ghostguard/gnn/trainer.py` | calibration, threshold selection, model bundle, full metrics |
| `ghostguard/federated/*` | background events, q95 estimates, staleness, integration |
| `ghostguard/verification/timing_analyzer.py` | iterative RTA/certificates; remove unused scheduler argument behavior |
| `ghostguard/experiments/ablations.py` | typed component substitutions with wiring assertions |
| `ghostguard/experiments/runner.py` | versioned matrix, run manifests, paired seeds, resume |
| `ghostguard/experiments/plotting.py` | data-driven plots only; no generated pseudo-observations |
| `ghostguard/dashboard/timeline_tracer.py` | replace authored story frames with event-to-frame reducer |
| `ghostguard/api/server.py` | `/api/v1` asynchronous run/replay/compare contracts and strict validation |
| `frontend/*` | implement `UI Design.md`; remove hard-coded metrics and claims |
| `scripts/generate_paper_artifacts.py` | consume frozen aggregate artifacts and emit provenance |
| `tests/*` | invariants, contracts, exact verification, replay, ablation and provenance tests |

## 18. Verification and Test Strategy

### Unit tests

- event ordering and boundary timestamps
- task/job state transitions
- queue discipline and preemption
- link serialization, loss, and retry
- early-exit selection
- predictor bundle/schema mismatch
- FedAvg weighted aggregation and staleness
- RTA convergence and failure
- metric formulas and units

### Property/invariant tests

- no task commits twice
- no predecessor violation
- service and bytes are conserved
- replay is deterministic
- more supplied execution work cannot finish earlier under identical state unless policy changes
- zero-capacity link never delivers
- an infeasible candidate is never selected

### Integration tests

- origin overload -> safe offload
- origin overload -> peer shock -> cancellation -> local exit
- no peer -> local degraded mode
- predictor timeout -> declared fail-safe
- stale FL model -> rejected/penalized candidate
- correlated mesh failure -> honest unavoidable miss

### Statistical regression tests

Use small fixed smoke matrices to test schema, determinism, and broad ordering only. Do not assert the paper’s final numeric results in unit tests. Store tolerance-based expectations for invariants, not desired conclusions.

### UI/contract tests

- OpenAPI schema snapshots
- event/frame reducer golden files
- component tests for empty/loading/error/partial states
- Playwright keyboard, responsive, and screenshot tests
- axe accessibility scan with zero serious/critical issues

## 19. Research Risks and Mitigations

| Risk | Consequence | Mitigation |
|---|---|---|
| Simulator favors GhostGuard assumptions | Invalid comparison | Shared models, common random numbers, baseline review, publish scenarios |
| Label leakage from adjacent snapshots | Inflated predictor scores | Group split before sampling; leakage audit |
| Predictor improves DMR by degrading everything | Low task utility hidden | Jointly report on-time utility and fallback rate |
| Mean latency underestimates tail | Unsafe offloads | Use calibrated quantiles and sensitivity analysis |
| “Verified” conflicts with simulated scheduler | False assurance | Hash-bound certificate and runtime assumption checks |
| FL adds no meaningful effect | Weak contribution | Integrate costs/outputs; report null result honestly |
| Hard-coded artifacts diverge from raw runs | Non-reproducible paper | Provenance-enforced generation that fails on missing data |
| Too many experimental cells | Schedule overrun | Pilot, power/precision analysis, freeze core matrix first |

## 20. Definition of Done

The research implementation is complete only when all statements below are true:

- [ ] DAG dependencies and end-to-end deadlines are actually simulated.
- [ ] The saved and calibrated predictor is invoked in GhostGuard experiment runs.
- [ ] The federated estimator is invoked, versioned, and charged as background work.
- [ ] Early exit uses valid task-specific checkpoints and reports utility.
- [ ] Offload cancellation and late return behavior cannot double-complete work.
- [ ] Fixed-priority RTA is iterative and includes declared overhead, jitter, and blocking.
- [ ] Every baseline and ablation changes executable behavior as specified.
- [ ] At least 30 paired seeds per primary cell are run, or a documented precision justification is provided.
- [ ] Confidence intervals, effect sizes, model calibration, and inference tail latency are reported.
- [ ] Dashboard states derive from canonical events and contain evidence labels.
- [ ] Figures and LaTeX tables contain no embedded experimental constants.
- [ ] Every paper number maps through `provenance.json` to raw run IDs.
- [ ] A clean-environment smoke reproduction passes.
- [ ] Paper language states the simulation and verification assumptions without universal safety claims.

## 21. Immediate Next Actions

1. Freeze the current prototype as a `demo-v0` tag or archive before refactoring.
2. Implement the canonical scenario/event schemas and single-commit attempt model.
3. Replace the demonstration tracer with a reducer over canonical events.
4. Correct the RTA analyzer and its paper wording.
5. Wire the saved GNN and FL estimator into the scheduler with explicit model identity.
6. Replace the current ablation booleans with real dependency substitutions.
7. Run a small pilot matrix to estimate variance and determine the final seed count.
8. Implement the dashboard shell and experiment inspector from `UI Design.md` after the API/event contracts stabilize.

