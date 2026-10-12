# 0016: Isolated inspection snapshots and paired outcome explanations

Status: accepted. Owner: primary agent.

ResearchProjection snapshots must be detached copies. Later event consumption or a caller modifying a returned nested record must not change a previous snapshot or the reducer's state. A snapshot task adds a `diagnostics` object containing that task's latest canonical prediction, decision and watchdog records, when present. The existing bounded recent-record lists remain compatible. Inspection uses task diagnostics rather than a newer task's device-wide output.

Paired session snapshots also detach model identity and analytical-reference metadata. Caller mutation must not change later manifests or the reference certificate's scope.

Job projections add `terminal_us` from JOB_COMPLETE/JOB_MISS. The first direct TASK_DEADLINE (excluding siblings dropped with the job) adds `failure_task`, `failure_us` and `failure_reason` to its job. These preserve observed failure attribution, not inferred causes. Failure at the job's deadline is labeled as exhausted end-to-end budget; no hardware root cause is invented.

The paired outcome view joins actual released job identifiers. A resolved pair is both met, rescued, regressed or both missed. Pending pairs remain pending and are excluded from resolved counts. Their denominators and sums must reconcile with the two policy projections. Selecting a baseline mark still inspects the protected job and explicitly compares both recorded outcomes.

The independent trace audit additionally checks exclusive delivered-service intervals per device/lane, using canonical SERVICE/CPU_OVERHEAD busy intervals. It rejects attempt creation or commitment in a terminal job, duplicate job/task definitions and commitments after task failure. An already dispatched peer can still consume service until its cancellation is acknowledged or its lease expires. These checks do not imply physical timing guarantees.

All changes are additive snapshot fields or stronger audit behavior. Event/config/model schemas and scheduling/prediction algorithms are unchanged. Frozen experiment artifacts retain their original provenance.
