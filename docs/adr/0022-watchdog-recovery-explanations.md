# ADR 0022: recorded watchdog recovery explanations

Status: accepted. Contract writer: layered research engine and its projection.

The timed audit found that an exhausted result transfer left no arrival in the
watchdog's transfer set. Treating that empty set as a zero remaining bound hid
known delivery failure until the latest fallback window. Record exhausted request
and result delivery per attempt. At the next charged watchdog observation, a
known failure triggers recovery only if the existing conditional fallback analysis
admits a structurally valid exit. Feature ablations remain authoritative.

WATCHDOG_CHECK gains reason, remote_transfer_failed, margin_us and next_check_us.
remote_bound_us is null when delivery has already failed; null does not mean zero.
The original canonical envelope remains unchanged. The independent trace auditor
checks these reasons against preceding TRANSFER_FAILED events and deadline gates.
Existing archived traces retain their original audit scope and are not rewritten.

Handoff projection histories retain FALLBACK_ANALYSIS, FALLBACK_ADMITTED,
FALLBACK_BOUND_CHECK and OUTPUT_VALIDATION/REJECTED milestones. Snapshot budgets
gain deadline margin and watchdog period; runtime_features exposes executed flags.
These are additive research-snapshot/1.0 fields. No domain or model schema changes.

UI inspection resolves prediction, decision and watchdog to one task. The overview
links to the latest actual recovery; it never fabricates a demonstration. Parallel
cancellation is shown separately from local fallback execution. Certificates retain
their finite-job assumptions; no physical-system safety claim is introduced.
