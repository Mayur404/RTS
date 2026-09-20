"""
Unit tests for Analytical Timing Verification of Fallback Modes.
"""

import pytest
from ghostguard.verification.timing_analyzer import TimingAnalyzer


def test_analytical_timing_verification():
    res = TimingAnalyzer.verify_fallback_mode("Perception")

    assert res.is_verified is True
    assert "Fallback VERIFIED under current configured timing assumptions" in res.status_statement
    assert res.worst_case_response_time_ms <= res.critical_deadline_ms
    assert res.degraded_utilization <= 1.0
    assert len(res.assumptions) > 0


def test_nonexistent_task_verification():
    res = TimingAnalyzer.verify_fallback_mode("NonExistentTask")
    assert res.is_verified is False
