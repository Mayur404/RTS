# PredictiveRuntime UI design

The product has exactly two primary views: Simulation and Results.

## Simulation

An SVG facility shows roads, operations/logistics buildings, an edge hub, assembly
cells, loading areas, landscaping and a drone pad. Colored rovers follow the road;
drones patrol the courtyard. Travel follows accepted simulation time and is
explicitly illustrative. It never changes runtime/link metrics. Pause freezes
travel; manual drag or keyboard movement holds a device until reset.

Devices show recorded CPU/GPU occupied capacity and exact resource-owning tasks.
Background interference and GPU CPU reservations are distinct from idle lanes.
Callouts choose positions around icons to limit overlap. The camera persists
through updates, supports mouse/touch/keyboard pan/zoom, fit and device focus.

The selected device's primary and other configured workflow DAGs are visible
together. Nodes use canonical states; arrows become solid only after predecessor
commitment. Inspection pins an exact task and its recorded evidence. Changing the
workflow or closing inspection clears stale protection selection.

Directional live arrows represent actual in-flight requests, results, cancellations
and learning updates. Queued/finished transfers are excluded. Serialization holds
the marker at the sender; brief smoothing uses accepted observations only.
An orange dashed recovery arrow shows an admitted watchdog fallback while its
task is active. It disappears on commitment, deadline miss or skip; the recorded
timeline remains inspectable. It is a mechanism, not a network packet. In-flight
network cancellation or discarded-result traffic may legitimately outlive a task.
Packet SVG nodes persist across snapshots and same-snapshot redraws preserve
their animations. Pausing clears interpolation; completed runs have no live links.

Controls select conditions, 2–8 devices, task mix and 50–150% release rate, plus a
0.05–3× presentation speed slider. Settings create a new paired run after any
pending step finishes. Pause/resume and exact 1000-us stepping cannot overlap
requests. Hidden tabs stop stepping. Reduced motion suppresses interpolation.

Recovery stress is an explicitly configured scenario, not an authored outcome.
Slow motion arms pause after a watchdog abort or local early exit. Milestones bind
to canonical timestamps; absent events stay unrecorded. A committed recovery task
can belong to a missed workflow. Predictions and certificates retain their scopes.

## Results

Lead with an honest final/provisional plain-language conclusion. Show on-time,
missed and active workflows; simulated release/drain time; completed-workflow
durations; fallback-task outcomes; watchdog and early-exit counts; paired prevented
and extra misses; per-device totals and exact changed-workflow examples.

Prevented and extra misses join identical job identities. Final net change must
equal baseline-minus-protected missed jobs. Active pairs remain unresolved.
Fallback completion is a task outcome, not a whole-workflow rescue. Mechanism
counts overlap and are not added as saved workflows. Timing averages use on-time
workflows in each run and may cover different cohorts.

Record/metric/identity/deadline inconsistencies display a review alert. Graphs use
accepted observations, never generated samples. Completed runs expose raw events,
metrics, checksummed manifests and archived source/model/configuration identity.
Evidence labels distinguish simulated, predicted, measured and analytical values.
No physical-system safety or universal deadline guarantee is asserted.

Keep controls keyboard-operable, task DOM stable between snapshots, labels readable,
and diagrams/tables scrollable inside their panels on phones. Product flows expose
implementation detail only when it helps understand the evidence.
