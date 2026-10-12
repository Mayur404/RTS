# 0017: Terminal task state and truthful resource edges

Status: accepted. Owner: primary agent.

A task's COMMITTED/MISSED/SKIPPED state is terminal. A delayed remote request or another GPU layer may still execute until cancellation acknowledgment or lease expiry, but restarting that attempt must not overwrite the terminal task state. Commitment and watchdog intervention additionally require an active workflow. The distinction between task/result eligibility and attempt service remains explicit.

RESOURCE_SAMPLE remains the source of allocation edges. Solid resource-to-work arrows require an actual CPU/GPU slot owner, or the current sender serialization interval for radio. Dashed work-to-resource arrows describe queued requests. Propagating packets have already released the radio and do not hold it. A checkpoint waits for its associated CPU decision operation rather than holding the GPU. Controller and FL operations are represented as CPU work. Memory allocations belong only to running attempts; queued attempts show prospective memory demand. TASK_PLANNED adds memory_demand_mb. Domain constants own the unchanged 32 MB CPU and 128 MB GPU footprints; the frontend reads the canonical demand.

Task snapshots add canonical `handoff_ids`. Snapshot `handoff_history_total` and `handoff_history_limit` expose the existing bounded handoff history. If a selected task was offloaded but its detailed history is outside that window, the UI labels that limitation instead of asserting that no handoff happened.

The detailed task DAG distinguishes committed predecessor edges from pending ones. The result-queued storyboard milestone uses a recorded result TX_START rather than execution completion, and its wording identifies that this is a queued transfer request, not proof of completed transport. Packet loss, cancellation and task failure remain separate facts.

The independent auditor rejects nonpositive/noninteger CPU overhead as well as duplicate terminal events and overlapping exclusive CPU/GPU service and sender radio serialization. Radio propagation may overlap after serialization releases the sender. No model/config/event-envelope schema changes are made. TASK_PLANNED and snapshot fields are additive. Frozen study artifacts remain unchanged; new runs must retain their own source version.
