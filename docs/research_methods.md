# Research methods and claim boundaries

The implemented experiment is a discrete-event study, not a physical robot
deployment. `docs/research_project_final.tex` describes the research architecture; ADR 0012 and the
versioned run configuration define the implemented model. Refer to each run's
archived source for exact policy rules rather than assuming that a proposal
diagram is a formal algorithm specification.

## Workload and time

The base API template uses four heterogeneous devices; the facility UI supports
2–8 and starts with six. The mixed workload has three independent workflows: a six-stage
autonomy DAG, a two-stage control chain, and a three-stage telemetry chain.
Autonomy forks after Sense into ObstacleDetection and Perception and joins at
Tracking; planning and actuation follow. All stages must reach the sink.
The ready time of a successor is the time all predecessor results commit at its
origin. Its absolute deadline is

\[
d_v=\min(r_v+D_v,\ r_J+D_J).
\]

Execution demand is drawn once per task instance from its declared uniform
bounds, using a stream keyed by scenario seed and task identifier. Policies
therefore share releases, demands and fixed interference intervals. Demand is
hidden from the predictor: remaining features use declared budget minus observed
delivered work. A degraded path uses its explicit remaining work and checkpoint
overhead, rather than scaling the sampled demand to a desired result.

Time and work use integer microseconds; rates use integer parts per million.
For elapsed time \(\Delta t\), rate \(s\), and carried fractional residual \(q\),
the service accumulator computes

\[
w=\left\lfloor(\Delta t\,s+q)/10^6\right\rfloor,
\quad q'=(\Delta t\,s+q)\bmod10^6.
\]

Consumed service is capped at remaining work and the next GPU layer boundary.
There is one CPU execution slot and one GPU layer slot per device. GPU work
reserves configured CPU capacity; memory admission is bounded. A zero available
service rate delivers zero work. Configured thermal dynamics modify service
rates at sample boundaries. Stable ordering processes completion/delivery before
an equal-time deadline. Completion at the deadline is valid.

## Policies and communication

The protected arbiter uses actual GNN inference plus conservative declared-work
estimates at the *current* resource state. A remote candidate includes request
serialization/propagation, remote queued work, execution, and result return.
Estimates do not bound future interference or future arrivals and are not timing
certificates. The watchdog periodically rechecks remote feasibility and the
latest available local degraded recovery. Separate attempt identities permit
continued remote work while cancellation is in flight, but only the active
attempt can commit once. A lost cancellation stops compute at the task's
deadline lease. Results that arrive after failure/cancellation cannot commit.

Each sender radio serializes payloads; propagation is separate from serialization.
Loss and jitter use keyed random streams and a bounded number of retries. The
delivery-reliability calculation \((1-p^{k+1})^2\) assumes independent packet
attempts at stationary loss \(p\), with \(k\) retries, for request and return.
It is an analytical channel approximation, separate from the neural execution
reliability head. Controllers share current-state telemetry; telemetry transport
delay is not modeled. No physical wireless-network guarantee follows.

FIFO uses non-preemptive CPU execution; RM uses shorter periods first; EDF uses
earlier absolute deadlines. Unconditional offloading selects the shortest
estimated eligible remote route without deadline admission. Reactive degradation
uses current declared-work deadline pressure without a neural predictor.
Predictive without fallback uses the same predictor and remote estimates but
cannot activate a degraded path. All comparators share the work/transport kernel.

## Learning

The research GNN starts from the original GNN bundle and is fine-tuned on actual
EDF rollout graphs. Training seeds are 4100–4105; validation seeds 4200–4201;
held-out test seeds 4300–4301. Training/validation contain bursty and thermal
families; the test additionally contains unreliable-network scenarios. Graphs
are captured at TASK_READY before controller work. Labels come from future
canonical TASK_DEADLINE events, including firm workflow drops. No future
execution demand or outcome enters graph features. Validation log loss selects
weights; validation-only temperature scaling and F1 select calibration and the
decision threshold. Test metrics are evaluated once after those choices.

Calibration supports that held-out release-state distribution. Protected
checkpoints induce covariate and policy shift; their calibration requires
additional experiments. The resource-cause head is trained on a resource-state
proxy, not causal interventions. Time-to-failure is exploratory and its test
error must accompany any claim. High AUROC does not excuse low precision.

The remote service estimator starts from its original bundle. Each simulated
client stores private bounded observations, freezes a local dataset per round,
executes real SGD, and uploads weights over the modeled network. A censored
deadline failure contributes to reliability loss but not completed-latency loss.
FedAvg publishes

\[
\theta_{t+1}=\sum_i\frac{n_i}{\sum_j n_j}\theta_{t,i}
\]

only after enough updates, modeled aggregation work and all participant downloads
complete. Runtime decisions use the last published version. Simulator audit
events preserve private observations for research reproducibility; clients exchange
parameters rather than raw observations. This is simulated distributed learning,
not a privacy guarantee or a physical distributed deployment.

Inference, dispatch, watchdog, training and aggregation costs are declared work
budgets competing with tasks. Observed host latency is recorded separately and
does not alter deterministic simulation time. A configured 250 µs inference
budget is not a measured host WCET. Hardware calibration and budget sensitivity
are needed before real-time deployment claims.

## Endpoints and experiments

Primary final deadline-miss ratio is

\[
\mathrm{DMR}=100\frac{\#\text{missed end-to-end jobs}}{\#\text{released jobs}}.
\]

A failed predecessor makes its end-to-end job missed; blocked successors do not
vanish from this denominator. The fixed release window plus sufficient drain
resolves every released job. Provisional display includes active released jobs;
it is not a final success estimate. Task DMR separately uses tasks that became
ready. Utility is a configured proxy averaged over committed task outputs, not
measured perception accuracy or end-to-end application quality.

The paired effect in percentage points is EDF DMR minus protected DMR. Relative
reduction divides by EDF DMR only when it is nonzero. Negative effects and
undefined zero-baseline relative effects remain visible. The suite averages
per-seed paired effects separately by family and obtains percentile intervals
from 5,000 paired seed resamples (bootstrap seed 91). Resampling is inference
from actual seed outcomes, not newly simulated evidence. Fixed fault schedules
limit the population represented by these intervals.

Final manifests bind configuration, model hashes, source/archive hashes,
environment, raw events and metrics. `scripts/verify_research_artifacts.py`
reconciles those artifacts and checks precedence, deadlines and single commitment.
Plot generators consume actual per-seed results. The dashboard never embeds an
expected improvement percentage.

## Analytical scope and remaining validation

Exact fixed-priority RTA uses integer fixed-point recurrence and preserves its
certificate bindings and assumptions. The UI's hypothetical isolated control
partition reserves a declared minimum CPU rate, overapproximates independent
stage release jitter, and excludes all other workload/learning/network activity.
It is a reference experiment, not the runtime's EDF/GPU/DAG scheduler. Both
unschedulable and conditionally verified reference outcomes remain visible.
The proposal's broad fallback-schedulability claim needs an appropriate dynamic
multi-resource analysis or an implemented partition that matches its certificate.

Further publication work should compare every baseline with enough paired seeds,
vary link/service/overhead/telemetry assumptions, assess protected-distribution
calibration, cross-check against independent traces/simulators, and calibrate
hardware budgets. Model fidelity, semantic validity of degraded AI output and
physical safety are outside this simulator's evidence.

## Primary sources consulted

- [FedAvg, McMahan et al.](https://proceedings.mlr.press/v54/mcmahan17a.html): local SGD and sample-weighted aggregation.
- [Calibration, Guo et al.](https://proceedings.mlr.press/v70/guo17a.html): temperature scaling on a separate validation set.
- [SeReMAS](https://arxiv.org/abs/2105.15105): predictive edge placement in uncertain mobile systems; its replication strategy is distinct from this prototype's abort-and-recover policy.
- [Adaptive multi-robot placement](https://arxiv.org/abs/2606.00552): placement feedback under contention; this implementation uses a separate predictive policy.
- [Fixed-priority RTA assumptions](https://doi.org/10.1007/s11241-018-9305-z): analysis applicability must match scheduler/task assumptions.
- [SimPy event ordering](https://simpy.readthedocs.io/en/4.0.2/topical_guides/time_and_scheduling.html): deterministic tie ordering; this project implements its own integer kernel.

The proposal's Toba paper is listed by [coauthor Sanjoy Baruah](https://research.engineering.wustl.edu/~baruah/Pubs.shtml). ACM/IEEE full-text retrieval for the Toba and V-FedGNN references was unavailable in this session; no additional implementation detail was inferred from inaccessible full texts.

Normal GPU dispatch can change owners only at a layer boundary. Cancellation delivery and deadline lease expiry are modeled as external aborts: they may terminate a layer and discard its partial output. This abstract abort is not a measured GPU-kernel cancellation implementation; no partially interrupted layer is committed as a valid early-exit output.
## Conditional live fallback analysis (ADR 0019)

The live certificate concerns one admitted fallback stage, not the entire dynamic
EDF/offload task set. Fallbacks have priority above ordinary lane work and CPU
controller operations and retain FIFO admission order. CPU fallback is preemptive;
GPU fallback waits for the running layer. For conservatism the bound charges the
running ordinary GPU attempt's entire declared remaining demand, rather than its
sampled next-layer demand. Already admitted fallback remainders also interfere.
Later fallback admissions cannot overtake the analyzed attempt.

Let `r_min` be the integer PPM service rate at the maximum configured background
load overlapping `[admission, deadline]`, the thermal floor 450000, and (on CPU)
the maximum GPU CPU reservation. Let `W` contain the fallback's declared remaining
work plus checkpoint overhead, the existing admitted fallback remainders, and
the ordinary GPU blocking term. The conditional response bound is
`R = sum(ceil(w * 1000000 / r_min) for w in W)`.
Admission requires `admission + R + margin <= stage deadline`. Zero service,
insufficient lane memory and incompatible scheduler modes reject admission.
Memory capacity must accommodate both possible concurrent lane allocations.
Each term is rounded separately to include fractional-service startup losses.

Under these assumptions the rate never falls below `r_min`; the lane cannot serve
later arrivals before the analyzed fallback; every existing interference term is
bounded by its declaration. Summing their service times therefore bounds completion.
Cancellation can only reduce the interference. Certificates bind scenario, policy,
scheduler contract, checkpoint, task and admission time. Completion checks and
independent raw-trace audits check this relation. Declared execution demands,
configured faults, instantaneous simulator bookkeeping and thermal behavior are
model assumptions, not physical-device timing evidence. Successor stages and
remote service are outside this certificate.

## Executed partial outputs and hardware timing

The synthetic workload executes actual PyTorch prefix/full classifier heads. The
prefix uses the first two features; the full head also executes the second stage.
Seeded input, constant model weights, probabilities and output checksums are recorded
and replayable. A result must be a finite normalized three-class tensor with the
matching head/checkpoint contract to commit. This establishes structural validity
for this explicitly synthetic workload. It does not establish perception accuracy,
robot-command validity, or the configured utility's empirical correctness. Host
tensor execution does not advance simulation time; its declared execution budget
is represented by lane work.

`scripts/profile_inference.py` measures actual GNN calls over every supported task
node count and records source/model/environment bindings and raw timing samples.
Completed paired runs also produce `inference-timing.json` from canonical host
observations, with its checksum in the run manifest. The observed maximum and p99
are empirical. Finite samples cannot prove a hard WCET on a general-purpose OS.
The explicit host budget can optionally discard late neural recommendations;
detection happens after the call returns and does not preempt PyTorch. Default
simulation monitors timings without making outcomes depend on host wall time.
Enforced mode intentionally depends on the measured host and preserves each
overrun/discard in the trace. Its simulated controller charge remains a separate
configured quantity.
