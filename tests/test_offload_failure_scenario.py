"""
Integration test for the Section 12 Deterministic Offload Failure Demonstration Scenario.
Verifies that:
1. Baseline EDF misses deadlines under severe dynamic contention.
2. GhostGuard predictive arbitration catches impending risk.
3. GhostGuard active monitoring intercepts neighbor degradation mid-flight.
4. Local degraded fallback activates and preserves critical deadline.
"""

import pytest
from ghostguard.experiments.scenarios import create_deterministic_failure_demo_scenario
from ghostguard.schedulers.edf import EDFScheduler
from ghostguard.schedulers.ghostguard import GhostGuardScheduler


def test_deterministic_offload_failure_scenario():
    # 1. Test Baseline
    sim_base = create_deterministic_failure_demo_scenario(seed=42)
    sched_base = EDFScheduler()
    sim_base.attach_scheduler(sched_base)
    m_base = sim_base.run(duration_ms=200.0)

    # Under this severe scenario, baseline must suffer deadline misses
    assert m_base["deadline_missed_count"] > 0
    assert m_base["critical_misses"] > 0

    # 2. Test GhostGuard
    sim_gg = create_deterministic_failure_demo_scenario(seed=42)
    sched_gg = GhostGuardScheduler(
        risk_threshold=0.60,
        reliability_threshold=0.70,
        safety_margin_ms=3.0
    )
    sim_gg.attach_scheduler(sched_gg)
    m_gg = sim_gg.run(duration_ms=200.0)

    # GhostGuard must achieve lower deadline misses and successfully invoke fallback
    assert m_gg["critical_misses"] < m_base["critical_misses"]
    assert sched_gg.verified_fallbacks_invoked > 0
    assert sched_gg.aborted_offloads_recovered_by_fallback > 0
