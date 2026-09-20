"""Tests for exact, conditional fixed-priority timing verification."""

from dataclasses import replace

import pytest

from ghostguard.verification import (
    AnalysisProvenance,
    AnalysisRequest,
    CertificateBinding,
    FixedPriorityTask,
    TimingAnalyzer,
    VerificationStatus,
)


def task(
    task_id: str,
    *,
    period_ms: int,
    deadline_ms: int,
    wcet_ms: float,
    priority: int,
    jitter_ms: float = 0,
    blocking_ms: float = 0,
    overhead_ms: float = 0,
    resource_id: str = "safety-cpu",
) -> FixedPriorityTask:
    """Construct exact microsecond fixtures from short millisecond literals."""

    return FixedPriorityTask(
        task_id=task_id,
        period_us=int(period_ms * 1000),
        deadline_us=int(deadline_ms * 1000),
        wcet_us=int(wcet_ms * 1000),
        priority=priority,
        jitter_us=int(jitter_ms * 1000),
        blocking_us=int(blocking_ms * 1000),
        overhead_us=int(overhead_ms * 1000),
        resource_id=resource_id,
    )


def default_degraded_critical_tasks() -> tuple[FixedPriorityTask, ...]:
    return (
        task("Sense", period_ms=20, deadline_ms=20, wcet_ms=1.5, priority=10),
        task(
            "ObstacleDetection",
            period_ms=20,
            deadline_ms=20,
            wcet_ms=2.5,
            priority=9,
        ),
        task("Perception", period_ms=33, deadline_ms=33, wcet_ms=5, priority=8),
        task("PathPlanning", period_ms=50, deadline_ms=50, wcet_ms=4.5, priority=7),
        task("Actuation", period_ms=10, deadline_ms=10, wcet_ms=1, priority=11),
    )


def results_by_id(certificate):
    return {result.task_id: result for result in certificate.results}


def test_hand_calculated_fixed_points_and_full_iteration_trace():
    certificate = TimingAnalyzer.analyze_task_set(default_degraded_critical_tasks())

    assert certificate.status is VerificationStatus.VERIFIED
    assert certificate.is_verified
    results = results_by_id(certificate)
    assert {name: result.response_time_us for name, result in results.items()} == {
        "Actuation": 1_000,
        "Sense": 2_500,
        "ObstacleDetection": 5_000,
        "Perception": 10_000,
        "PathPlanning": 15_500,
    }

    perception = results["Perception"]
    assert [step.response_us for step in perception.iterations] == [5_000, 10_000, 10_000]
    assert perception.higher_priority_task_ids == (
        "Actuation",
        "Sense",
        "ObstacleDetection",
    )
    final_contributions = {
        item.task_id: (item.releases, item.total_interference_us)
        for item in perception.iterations[-1].interference
    }
    assert final_contributions == {
        "Actuation": (1, 1_000),
        "Sense": (1, 1_500),
        "ObstacleDetection": (1, 2_500),
    }


def test_explicit_priority_not_period_determines_interference():
    higher_with_longer_period = task(
        "ExplicitHigh",
        period_ms=100,
        deadline_ms=100,
        wcet_ms=3,
        priority=10,
    )
    lower_with_shorter_period = task(
        "ExplicitLow",
        period_ms=10,
        deadline_ms=10,
        wcet_ms=2,
        priority=1,
    )

    certificate = TimingAnalyzer.analyze_task_set(
        (lower_with_shorter_period, higher_with_longer_period)
    )

    low = results_by_id(certificate)["ExplicitLow"]
    assert certificate.status is VerificationStatus.VERIFIED
    assert low.higher_priority_task_ids == ("ExplicitHigh",)
    assert low.response_time_us == 5_000


def test_unschedulable_task_set_stops_after_deadline_exceeded():
    certificate = TimingAnalyzer.analyze_task_set(
        (
            task("High", period_ms=5, deadline_ms=5, wcet_ms=4, priority=2),
            task("Low", period_ms=10, deadline_ms=10, wcet_ms=4, priority=1),
        )
    )

    low = results_by_id(certificate)["Low"]
    assert certificate.status is VerificationStatus.NOT_SCHEDULABLE
    assert not certificate.is_verified
    assert low.status is VerificationStatus.NOT_SCHEDULABLE
    assert [step.response_us for step in low.iterations] == [4_000, 8_000, 12_000]
    assert low.margin_us == -2_000


def test_jitter_blocking_and_overhead_are_charged_as_declared():
    higher = task(
        "High",
        period_ms=10,
        deadline_ms=10,
        wcet_ms=2,
        priority=2,
        jitter_ms=4,
        overhead_ms=0.5,
    )
    lower = task(
        "Low",
        period_ms=20,
        deadline_ms=20,
        wcet_ms=5,
        priority=1,
        blocking_ms=1,
        overhead_ms=1,
    )

    with_jitter = TimingAnalyzer.analyze_task_set((higher, lower))
    without_jitter = TimingAnalyzer.analyze_task_set(
        (replace(higher, jitter_us=0), lower)
    )

    low = results_by_id(with_jitter)["Low"]
    low_without_jitter = results_by_id(without_jitter)["Low"]
    assert low.iterations[0].base_cost_us == 7_000
    assert low.iterations[1].interference[0].releases == 2
    assert low.iterations[1].interference[0].cost_per_release_us == 2_500
    assert low.response_time_us == 12_000
    assert low_without_jitter.response_time_us == 9_500


def test_iteration_limit_is_inconclusive_never_verified():
    certificate = TimingAnalyzer.analyze_task_set(
        (
            task("High", period_ms=10, deadline_ms=10, wcet_ms=1, priority=2),
            task("Low", period_ms=33, deadline_ms=33, wcet_ms=5, priority=1),
        ),
        max_iterations=1,
    )

    low = results_by_id(certificate)["Low"]
    assert certificate.status is VerificationStatus.INCONCLUSIVE
    assert low.status is VerificationStatus.INCONCLUSIVE
    assert [step.response_us for step in low.iterations] == [5_000, 6_000]
    assert not low.converged


@pytest.mark.parametrize("analysis_type", ["EDF", "EDF_DBF", "GHOSTGUARD"])
def test_unsupported_scheduler_never_produces_results(analysis_type):
    certificate = TimingAnalyzer.analyze_task_set(
        default_degraded_critical_tasks(), analysis_type=analysis_type
    )

    assert certificate.status is VerificationStatus.UNSUPPORTED
    assert not certificate.results
    assert any("only FP_PREEMPTIVE" in message for message in certificate.diagnostics)


def test_multiprocessor_and_multiple_resource_models_are_unsupported():
    one_task = (task("Only", period_ms=10, deadline_ms=10, wcet_ms=1, priority=1),)
    multiprocessor = TimingAnalyzer.analyze_task_set(one_task, processor_count=2)
    mixed_resources = TimingAnalyzer.analyze_task_set(
        (
            one_task[0],
            task(
                "GpuTask",
                period_ms=20,
                deadline_ms=20,
                wcet_ms=2,
                priority=2,
                resource_id="gpu0",
            ),
        )
    )

    assert multiprocessor.status is VerificationStatus.UNSUPPORTED
    assert mixed_resources.status is VerificationStatus.UNSUPPORTED
    assert not multiprocessor.results
    assert not mixed_resources.results


def test_duplicate_priority_is_invalid_input():
    certificate = TimingAnalyzer.analyze_task_set(
        (
            task("A", period_ms=10, deadline_ms=10, wcet_ms=1, priority=1),
            task("B", period_ms=20, deadline_ms=20, wcet_ms=2, priority=1),
        )
    )

    assert certificate.status is VerificationStatus.INVALID_INPUT
    assert any("share priority" in message for message in certificate.diagnostics)


def test_hashes_are_stable_and_change_with_semantic_inputs():
    tasks = default_degraded_critical_tasks()
    binding = CertificateBinding(
        scenario_hash="scenario-a",
        scheduler_config_hash="scheduler-a",
        hardware_profile_hash="hardware-a",
        resource_partition_id="safety-cpu",
        fallback_mode_id="degraded-v1",
    )
    request = AnalysisRequest(tasks=tasks, binding=binding)
    first = TimingAnalyzer.analyze(
        request,
        provenance=AnalysisProvenance(
            code_revision="abc123", generated_at_utc="2026-09-20T10:00:00Z"
        ),
    )
    reordered = TimingAnalyzer.analyze(
        replace(request, tasks=tuple(reversed(tasks))),
        provenance=AnalysisProvenance(
            code_revision="abc123", generated_at_utc="2026-09-21T10:00:00Z"
        ),
    )
    changed_binding = TimingAnalyzer.analyze(
        replace(request, binding=replace(binding, scenario_hash="scenario-b")),
        provenance=AnalysisProvenance(code_revision="abc123"),
    )
    changed_task = TimingAnalyzer.analyze(
        replace(request, tasks=(replace(tasks[0], wcet_us=1_501), *tasks[1:])),
        provenance=AnalysisProvenance(code_revision="abc123"),
    )

    assert first.input_sha256 == reordered.input_sha256
    assert first.task_set_sha256 == reordered.task_set_sha256
    assert first.certificate_sha256 == reordered.certificate_sha256
    assert first.certificate_id == reordered.certificate_id

    assert changed_binding.input_sha256 != first.input_sha256
    assert changed_binding.task_set_sha256 == first.task_set_sha256
    assert changed_binding.certificate_sha256 != first.certificate_sha256

    assert changed_task.input_sha256 != first.input_sha256
    assert changed_task.task_set_sha256 != first.task_set_sha256
    assert changed_task.certificate_sha256 != first.certificate_sha256


def test_legacy_adapter_rejects_default_edf_and_requires_explicit_fp():
    default_result = TimingAnalyzer.verify_fallback_mode("Perception")
    fixed_priority_result = TimingAnalyzer.verify_fallback_mode(
        "Perception", scheduler_type="FP_PREEMPTIVE"
    )

    assert default_result.status is VerificationStatus.UNSUPPORTED
    assert not default_result.is_verified
    assert default_result.certificate is not None
    assert not default_result.certificate.results

    assert fixed_priority_result.status is VerificationStatus.VERIFIED
    assert fixed_priority_result.is_verified
    assert fixed_priority_result.worst_case_response_time_ms == 10.0
    assert fixed_priority_result.certificate is not None


def test_missing_legacy_task_is_invalid_input():
    result = TimingAnalyzer.verify_fallback_mode(
        "NonExistentTask", scheduler_type="FP_PREEMPTIVE"
    )

    assert result.status is VerificationStatus.INVALID_INPUT
    assert not result.is_verified
    assert result.certificate is None
