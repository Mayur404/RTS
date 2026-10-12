# 0014: Runtime projection consistency and event auditing

Status: accepted. Owner: primary agent.

The canonical engine remains the execution authority. Fix the research reducer's existing host/state/phase semantics: an attempt's `host` means its execution host, never the sender of a cancellation; task state follows queue, preemption, and commitment events; event and resource samples agree on attempt phases. Snapshot tasks gain additive `committed_attempt` and `commit_us` fields from TASK_COMMIT. Attempts gain `cancel_requested_us` from CANCEL_REQUEST. Preserve immutable offload identity separately for metric denominators. Historical manifests retain their original metrics and archived source; new reconciliation compares engine outcomes and current reducer results. No old evidence is overwritten.

Handoff histories add existing PREEMPT and TRANSFER_FAILED events. The timeline terminates a slot-residence segment at each checkpoint or preemption, rather than drawing overlapping execution intervals through every restart. A shared selector drives all handoff views; inspecting a task without an offload displays no unrelated handoff. Resource allocations use actual sampled slot identifiers, not task state alone.

Hardware capacities require positive integer values, excluding booleans. Monotonic simulation horizons reject booleans and backwards requests even beyond completion. These validation restrictions preserve the integer-time model and do not change valid default scenario or neural/model schemas.

An independent canonical trace audit checks precedence, commitment, service conservation, transfer arrival, exclusive resources, and finite-run resolution. Audit findings are bounded simulator consistency checks, not timing certificates or physical-system safety verification. Publication studies remain frozen; projection-only corrections do not imply remeasured model quality or a new statistical study.


Trace audit reports use domain-owned `research-trace-audit/1.0` and bind the manifest, source/configuration identities and exact raw-event checksum. New source archives also include the frontend assets, plans and ADRs, so the displayed prototype can be reconstructed alongside the Python engine. No old archive is rewritten.
