# ADR 0020: bounded authoring for the layered simulator

Status: accepted. Ownership: API adapter and frontend scenario designer.

The dashboard previously started a fixed four-device EDF/protected pair. Add a
versioned `research-designer/1.0` request contract that compiles into the existing
immutable ResearchConfig, PipelineSpec and TaskSpec contracts. No canonical event,
model feature or existing domain schema is changed. Existing start requests remain
valid. Optional `scenario` and `baseline` fields are additive; supplied scenario
settings take precedence over the legacy preset fields.

New routes: GET `/api/research/scenarios/templates/{family}` and POST
`/api/research/scenarios/validate`. Validation does not run inference, create run
directories or consume a session slot. Session creation repeats validation. Unknown
fields, cyclic/disconnected graphs, duplicate identities, invalid work bounds,
unsupported settings and insufficient drain are rejected. Strict integer fields
reject booleans/fractional times. Limits are eight devices, six workflows, sixteen
stages each, 32 faults and 6000 released task instances per interactive run.

Only implemented semantics are exposed: periodic firm workflows replicated on each
device, one preemptive CPU slot, one four-layer GPU slot, fixed modeled task memory,
complete mesh and shared sender radios. Generic topological SVG layouts replace
task-name/Device_1..4 positioning assumptions. Directed edges describe configuration;
runtime edge states still require canonical predecessor commitment. Designer values
are CONFIGURED, not measured observations.

Custom scenarios carry `custom_scenario_unvalidated` model scope; pretrained
calibration is not generalized to edited fleets or workloads. The six existing
baseline policies are selectable; raw artifact routing now accepts their names.
Pause/resume remains the active run transport. Creating a new run is a separate
setup action. Previous completed evidence persists; unfinished sessions close as
INTERRUPTED. Source/model/config manifests continue to bind each pair.

Physical robot motion, camera workloads, generalized nonpreemptive CPU tasks,
custom topology/link specifications, arbitrary memory demands and sporadic releases
are not implemented by this adapter. Such fields cannot be silently accepted.
