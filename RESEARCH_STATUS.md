# PredictiveRuntime research readiness

**Audit date:** 2026-09-24
**Status:** Working simulator prototype; research claims remain conditional.

The simulator runs and its automated tests pass. This is evidence of the
implemented behavior, not proof that the simulator accurately represents a
physical real-time system. No 100% correctness or physical safety claim is
supported.

## Checks performed

- The complete repository suite passes over 100 tests on 2026-09-24.
- A future pipeline release is now emitted at its scheduled time. A remote
  pipeline stage releases successors only when its result reaches the origin.
  A stage's relative deadline starts when the stage becomes ready and is capped
  by the pipeline end-to-end deadline. See ADR 0006.
- A task-specific nine-feature GNN was trained on future deadline outcomes,
  calibrated on validation seeds, and packaged with an integrity hash. Its
  held-out simulator test contains 224 samples (AUROC 0.8063, AUPRC 0.8080,
  ECE 0.0481). These are simulation-derived model results.
- The FedAvg remote estimator uses accumulated execution service observations,
  disjoint train/validation/test seeds, and a versioned bundle. Its 745-sample
  simulator test reports 1.68 ms MAE and 0.953 empirical q95 coverage.
- Deadline events and terminal task states now agree in the checked bursty
  run, and its state and canonical-event reductions both report 7 misses.
  API v1 replay frames no longer invent utilization or temperature values.
- One-run benchmark summaries use null for undefined variance. Policy
  regressions remain visible as negative baseline-minus-policy miss counts.
- The full policy loads both bundles. Prediction latency is observed during
  each run and reported as count, p50, p95, and maximum rather than embedded
  as a constant.
- Live sessions extend DAG releases beyond their initial scheduling window,
  expose cursor-based canonical events, and prune history to a bounded rolling
  window. Live output is marked `LIVE_NON_EVIDENCE`.

## Blocking gaps for a research claim

1. The engine still represents execution work and some link and thermal timing
   in floating point milliseconds. The event queue quantizes to integer
   microseconds, but the whole simulator does not yet satisfy the integer-time
   invariant.
2. Predictor inference and federated communication are not consistently charged
   as foreground/background resource demand in the simulator. Network retries,
   propagation variation, and hardware-calibrated WCETs are not validated.
3. The packaged models have in-family simulated held-out tests but still need
   out-of-family scenarios and independent trace or hardware validation.
4. Published experiments still need at least 30 paired seeds, sensitivity
   studies, event/metric reconciliation, and independent
   validation against an established simulator or measured hardware traces.
5. The fixed-priority certificate covers only its stated uniprocessor task
   model and assumptions. It does not certify the dynamic offload pipeline or
   physical hardware.

## Evidence rule

Only cite results reduced from canonical events and bound to a run manifest.
Use **SIMULATED**, **PREDICTED**, **MEASURED**, or **ANALYTICAL** with the
corresponding source and assumptions. Do not describe an uncalibrated model as
calibrated or a simulator result as a hardware measurement.
