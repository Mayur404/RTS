# ADR 0021: fail-visible neural inference and configured utility

Status: accepted. Shared event-payload writer: layered research engine.

The audit found runtime GNN exceptions/invalid risks escaped the simulator rather
than executing the documented failure policy. Add canonical PREDICTOR_UNAVAILABLE
events with error type/reason, model version and the declared local recovery route.
Failed calls record MEASURED_ON_HOST latency; malformed/non-finite risks are never
emitted as predictions. Use the existing reactive local bound/conditional fallback
admission, otherwise full local execution. Do not infer a favorable risk or offload
on a failed recommendation. Successful inference behavior and model weights remain
unchanged. Actual GNN heads must contain finite tensors.

Projection counts include failed attempts and remove the old task prediction on
failure. The selected task retains its error and the fail-safe decision explicitly
marks predictor_unavailable. Canonical envelope/schema and existing metric keys
are unchanged; the event and DECISION flag are additive. Older traces retain their
original reduction semantics. Failure timing is empirical and may be host-dependent;
it is separate from configured charged decision work.

Normal attempts honor TaskSpec.output_utility, rather than unconditional 1.0;
degraded attempts retain ExitPointSpec.output_utility. Constant demand takes its
declared nominal work rather than a random draw between configured bounds. Default
uniform scenarios with full utility 1.0 retain their outcomes. Both fixes honor
existing immutable contracts; no domain/model schema changes are introduced.

The UI reorganizes existing canonical projections into focused inspection views.
View switching/expanding details never advances simulation time. Run replacement
must clear prior-run evidence links and preserve the previous run on setup failure.

Remote-estimator exceptions or invalid latency/reliability reject that candidate
with an explicit estimator_unavailable reason; they cannot authorize an offload.
Invalid/failed client training emits FL_TRAIN_FAILED and consumes the failed
delivery without preventing healthy clients from completing a round. Updates must
match frozen sample counts and model tensor shapes, contain finite loss/weights,
and declare their actual serialized size. Publication exceptions restore both
remote weights and version and emit FL_ROUND_SKIPPED with aggregation_failure.
These additive failure records preserve the canonical envelope and domain schema.
