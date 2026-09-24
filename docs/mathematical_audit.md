# Mathematical audit of the current prototype

## Fixed-priority response time analysis

`TimingAnalyzer` analyzes one fully preemptive processor with independent
constrained-deadline sporadic tasks and unique static priorities. For each task
it starts with `R(0) = C + B + O` and iterates

`R(k+1) = C + B + O + Σ ceil((R(k) + J_h) / T_h) (C_h + O_h)`

over higher-priority tasks. All input and intermediate values are integer
microseconds. The analyzer returns `VERIFIED` only on a fixed point no greater
than the relative deadline; a value above the deadline is `NOT_SCHEDULABLE`;
the 1000-iteration cap without convergence is `INCONCLUSIVE`. The certificate
binds the task set and assumptions by hash. This result does not cover the
dynamic predictive scheduler, network suspension, DAG precedence, or physical
hardware without a separate justified model.

## Offload feasibility

The scheduler evaluates the estimated absolute completion time as current
time plus request link backlog and transfer, remote queue work, estimated
remote execution, response link backlog and transfer, and a configured margin.
It selects a candidate only if this estimate is at most the job deadline.
The check is predictive; actual remote completion and result receipt are
separate simulation events. No analytical worst-case bound or certified
network delay is asserted for this estimate.

## Event-derived metrics

The artifact reducer counts unique `TASK_READY` task IDs as released jobs,
unique `DEADLINE` events and late `TASK_COMMIT` outcomes as misses. Total DMR
is missed/released; critical DMR uses the corresponding critical subset.
No denominator silently drops pending jobs. For a task type, observed WCRT is
the maximum committed response time, and observed jitter is its maximum minus
minimum committed response time. Pending jobs are reported as censored.
Results with no denominator use `null`, not a numeric zero.

## Model metrics

`expected_calibration_error` uses equal-width bins and computes
`Σ_b |Σ_{i∈b} p_i - Σ_{i∈b} y_i| / N`, equivalent to the count-weighted
absolute difference between bin confidence and observed frequency. The
metric requires held-out binary observations; the repository does not yet
contain a versioned held-out calibration study.

The training dataset now marks risk from future deadline events in an
unmodified local FIFO rollout. Time-to-violation loss and MAE use only samples
where a miss was actually observed within the lookahead window. AUC and lead
time are absent when the held-out sample cannot define them. The auxiliary
resource-class label remains a contemporaneous proxy, not a verified causal
explanation.

FedAvg weights each participating client's tensor by its sample count divided
by the total participating sample count. Round metadata counts one model
download and one upload per participating client in bytes. Link serialization,
energy, and concurrent background interference for FL rounds are not yet
modeled in the discrete-event runtime.
