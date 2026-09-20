# GhostGuard Research Evidence Status

**Status date:** 2026-09-20  
**Prototype checkpoint:** `demo-v0`

The current repository contains a functional demonstration prototype, not yet a validated research result. The implementation and UI can illustrate the proposed workflow, but the existing headline benchmark numbers, plots, and timing claims must not be cited as empirical evidence.

## What is currently usable

- A deterministic demonstration flow for local execution, offload, watchdog intervention, and fallback.
- Prototype scheduler, GNN, federated-learning, API, dashboard, plotting, and timing-analysis modules.
- A baseline automated test suite.
- A detailed research-grade implementation and UI plan.

## Known evidence blockers

- The current deadline-expiry and metric lifecycle can classify missed tasks incorrectly.
- Workload stages are independently periodic rather than released through a true DAG.
- Remote execution completion is based on scheduled estimates rather than committed remote-result events.
- The normal GhostGuard experiment path does not inject the trained GNN or federated estimator.
- Several ablation switches do not change executable behavior.
- Current timing analysis is a one-pass sufficient bound, not exact iterative fixed-priority RTA, and is not bound to the runtime scheduler configuration.
- Dashboard milestones and several publication plots/tables contain authored or synthetic values rather than reductions over canonical run events.
- Existing `results/summary.json` and paper-facing tables disagree materially.

## Evidence labels

- **DEMONSTRATION:** Authored walkthrough intended to explain the proposed control flow.
- **SIMULATED:** Derived from a versioned simulator run and canonical event stream.
- **PREDICTED:** Produced by a named model bundle.
- **MEASURED:** Timed on identified hardware with a recorded method.
- **ANALYTICAL:** Produced by a configuration-bound timing certificate under explicit assumptions.

Until the acceptance gates in `Implementation Plan.md` are satisfied, the Section 12 dashboard and existing paper figures must be labeled **DEMONSTRATION**. Phrases such as “guaranteed safe,” “100% temporal safety,” and “empirically measured” are not supported by the current artifacts.

## Promotion gate

Results may be promoted from demonstration to research evidence only when:

1. Simulator lifecycle and deadline accounting invariants pass.
2. Metrics are reduced from canonical events.
3. Predictor and federated model identities are recorded in run manifests.
4. Ablations alter the intended component graph.
5. Timing certificates match the scheduler, task set, resource model, overheads, and configuration hashes.
6. Figures and tables list their source run IDs and checksums.
7. Repeated paired-seed results include uncertainty and effect sizes.

