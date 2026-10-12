# 0015: Scheduling identity, service capacity, and deadline inspection

Status: accepted. Owner: primary agent.

RM ranks stage attempts and their decision/watchdog operations by the containing periodic workflow's period. Stages are precedence-triggered and their optional standalone period cannot override the actual release process. On CPU preemption, memory admission subtracts the replaced CPU holder's allocation, since this kernel releases memory on preemption. GPU allocation remains independently charged.

Zero-remaining-work operations complete immediately even at a zero service rate. Positive work stays blocked while capacity is zero; the correction must not fabricate service during a full-capacity fault.

FL chooses the highest configured CPU-speed node, breaking ties by identifier, as its coordinator; it no longer requires a literal Device_2. The default fleet still chooses its edge server. RUN_START and FL_ROUND_START add the coordinator identity. No config/model schema or default release/workload changes are introduced.

RESOURCE_SAMPLE adds `cpu_rate_ppm`, `gpu_rate_ppm`, and effective `gpu_cpu_reservation_ppm`, derived with the same integer arithmetic used for service. Sampled operations add their runtime `id`, `deadline_us`, and associated `task` when present. Task snapshots add `first_start_us` and `terminal_us` from canonical lifecycle events. These are additive fields under the existing event envelope and snapshot contracts. Frozen evidence retains its original source and metrics.

The UI distinguishes occupancy from per-slot service rate, displays sampled CPU/GPU queues including modeled overhead, and plots each ready stage's actual response interval against its readiness-based deadline and the job deadline. Blocked stages have no fabricated readiness or stage deadline. A firm job drop can terminate a sibling before its own stage deadline; the view labels that distinction. Timing bars are observed simulated intervals and admission estimates remain conditional predictions, not certificates.

`audit_research_events` adds an optional keyword-only `devices` argument containing canonical device specs. When supplied, the independent auditor checks sampled memory capacities and new service-rate fields against hardware speeds and capacity fractions. The manifest CLI validates the canonical configuration hash and supplies those specs. Older traces without rate fields retain the previous lifecycle/service audit scope.
