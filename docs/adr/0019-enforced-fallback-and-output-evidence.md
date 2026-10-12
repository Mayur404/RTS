# 0019: Enforced fallback response bounds and executed output contracts

The former current-rate fallback test did not bound future interference. Protected
and reactive fallback attempts now run above ordinary work on their execution lane,
in admission order. CPU fallback is preemptive; GPU fallback waits for at most the
running ordinary attempt's declared remainder and already admitted fallbacks.
Later admissions cannot overtake it. Controller work has lower CPU priority.

An additive `FALLBACK_ANALYSIS` certificate records remaining declared budgets,
worst configured background load until the stage deadline, thermal floor, memory
assumption, scenario binding, margin and decision time. Each admission binds its
certificate through `FALLBACK_ADMITTED`. No workflow, remote or physical-system
guarantee follows. FIFO/RM fallback analysis is unsupported. Zero capacity and
insufficient memory reject admission. Bounds use integer ceiling per attempt.

Additive attempt fields retain admission order, certificate and exit identity.
ResearchConfig gains an explicit positive host inference budget and optional
overrun enforcement. Host timings remain measurements; finite samples cannot
prove hard WCET. Enforcement discards late neural recommendations after return;
it cannot interrupt a running Python/PyTorch call. Default simulation is independent
of host wall time; enabling enforcement intentionally makes decisions host-dependent.

Actual synthetic two-stage tensor outputs now accompany autonomy attempts. An
early head uses a prefix; the full head uses all features. Input/model/output hashes,
probabilities, head identity and structural checks enter canonical events. These
are a reproducible synthetic workload, not camera perception or measured utility.
Configured execution budgets and utilities remain explicit modeling assumptions.
Invalid executed outputs cannot commit. Original event envelopes and model bundle
feature schemas are unchanged; new event payloads use their own version tags.
