# ADR 0023: Auditable model estimates and learning inspection

Date: 2026-10-11. Status: accepted.

## Context

The research policy uses a real GNN and a separate federated execution/reliability
MLP. Its coarse federated phase dictionary mixes local-training sample counts
with published sample totals and cannot explain incomplete rounds. Candidate
records identify an estimator version but do not preserve its exact float32 input
or learned outputs. The pretrained reliability temperature is loaded but was
omitted from the research estimate path. Online publications must not inherit
the pretrained model's empirical calibration or quantile-coverage claims.

## Decision

- Require the research GNN bundle and its declared feature schema. Missing files
  do not silently select a legacy model trained on a different graph definition.
- Validate GNN output dimensions, probability domain and timing outputs. Validate
  federated calibration metadata and update shapes, dtypes, devices, sample counts,
  bytes and finite losses before transporting an update.
- Apply the pretrained reliability temperature at estimator version zero. Online
  SGD/FedAvg publications use raw reliability (temperature one), are marked
  unevaluated, and retain the latency multiplier only as an unvalidated heuristic.
- Add nested `remote-estimate-evidence/1.0` diagnostics to successful real-model
  decision candidates: exact float32 input, learned execution estimate,
  reliability transformation, parameter digest and model version. Existing
  candidate fields keep their meanings. This is predicted evidence, not a bound
  certificate or newly measured coverage result.
- Add explicit round identifiers to FL skip events and activation timestamps/model
  metadata to publication events. Existing readers may ignore additive fields.
- Add a `learning` snapshot section with schema `learning-view/1.0`, reduced only
  from canonical events. It separates GNN attempts/outcomes, client observation
  counts, training, transfer progress, aggregation, skipped/incomplete rounds,
  publication and estimator use. Retain at most twelve detailed rounds, while
  preserving cumulative counts and the latest publication. Snapshots are detached.
- Preserve the existing `federated` snapshot section for compatibility and all
  existing metric definitions. Domain schema identifiers live under `domain/`.
- Add a Models & learning tab. It shows actual per-client stages and losses,
  round history, CPU/network costs and provenance, including failures and empty
  observations. It states that GNN weights are frozen while the MLP is updated.

## Consequences

These are additive event-payload/snapshot fields; the canonical event envelope,
scenario, model-bundle, API request and metric schemas do not change. Old traces
without estimator inputs remain auditable under their original scope; the new
model replayer checks estimate diagnostics only when present. Historical frozen
results are preserved. Applying previously omitted initial reliability calibration
can change new scheduling outcomes and requires a fresh runtime matrix.

The simulator remains centralized instrumentation of modeled clients; raw client
records are not sent in modeled FL messages. FedAvg is not differential privacy.
Current-workload and online calibration remain research gaps.
