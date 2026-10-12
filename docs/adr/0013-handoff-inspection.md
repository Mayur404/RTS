# 0013: Persistent canonical handoff inspection

Status: accepted. Owner: primary implementation agent.

The research snapshot adds `before.handoffs` and `after.handoffs` without changing canonical events, scheduling, or metrics. Each entry identifies the remote attempt, task, job, origin, destination, dispatch time, terminal state, and original canonical milestone records. The reducer retains the finite run history; snapshots expose the last 48 handoffs. This additive dashboard contract preserves event sequence and integer microsecond timestamps. A local fallback commit is RECOVERED; a remote commit is RETURNED. Packet loss and cancellation do not imply success. Watchdog summaries preserve the last check's bound fields when an abort arrives; their timestamp is explicitly a historical observation, not a fresh estimate.

The interface derives timelines and selection from these records. It does not fabricate packets, progress, completed stages, or recovery outcomes. The default unreliable scenario exercises real recovery; other scenarios remain available through a family URL parameter. This presentation change does not affect research experiments or model calibration.
