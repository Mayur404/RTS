# ADR 0012: Integer-time layered research simulation

Add a separate research engine and additive `/api/research/sessions` endpoints.
Legacy simulation APIs and frozen model bundles remain unchanged. Domain owns
`rts_predictive.research-config/1.0`; snapshots use `research-snapshot/1.0`.
Canonical events retain their existing envelope and add research lifecycle
payloads documented by the engine and reducer. New run manifests bind both
paired policies to one configuration, raw events and starting model hashes.

Time, work, completion and deadline comparisons use integer microseconds.
Service rates use integer parts per million with carried residuals. CPU is EDF;
GPU preemption is possible only at explicit layer checkpoints. Configured
dispatch/inference/FL work occupies the same CPU as foreground tasks. Measured
host costs are audit observations and do not change the deterministic clock.

Every device runs autonomy (branched), control and telemetry workflows. An
end-to-end job is an outcome even when a failed predecessor blocks later stages.
Job DMR over all released jobs is the primary paired metric. Task DMR has a
separate denominator of tasks that became ready. Cancelled remote work remains
charged until modeled acknowledgement. Result return is required for origin
commit; one task can commit at most once.

FedAvg uses actual local SGD and sample-weighted updates, with timestamped
training, shared-radio transfers and atomic publication. Existing model bundles
are transfer baselines; previous calibration is not validation of this new
scenario. Layer utility is a configured proxy. Analytical timing certificates
remain scoped to their explicit independent fixed-priority partitions.

## Contract additions completed with this decision

The new kernel supports EDF, FIFO (CPU non-preemptive), RM, unconditional offload, reactive degradation, and predictive without fallback. These comparisons use the same integer work/transport kernel. Canonical payload additions include current-attempt flags, private execution observations, censored latency markers, separate neural execution and analytical retry-delivery reliability, frozen FL observation sets, resource samples, and atomic publications. Projection metrics include response/jitter, critical-task DMR and returned offload successes. These are additive fields; no legacy event envelope changes.

Source/model ZIP archives preserve the actual dirty source and starting bundles. Manifests include environment versions and archive/event/metric hashes. Completed evidence routes have a strict UUID and filename whitelist and remain accessible independently of in-memory session eviction.

Analytical reference certificates describe a hypothetical independent fixed-priority control CPU partition, with explicit minimum service rate, release jitter, exclusions and configuration binding. They never authorize or certify live EDF/GPU/offload decisions. The main snapshot makes this non-applicability explicit.

Host timing instrumentation: newly created runs emit canonical HOST_INFERENCE and HOST_TRAIN observations marked MEASURED_ON_HOST. The projection derives the host inference card from those events. This metadata does not alter modeled CPU costs, task/transport ordering or policy outcomes. Completed manifests additionally hash host observation and final remote-model files. Frozen studies preceding this instrumentation retain their separately recorded host observations and original archived source.

The snapshot exposes declared inference/dispatch/training budgets separately from canonical measured host observations. No empirical timing constant is embedded in the UI.
