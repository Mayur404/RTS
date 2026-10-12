"""Conditional fixed-priority response-time analysis.

This module implements exact fixed-point RTA for one constrained-deadline,
fully preemptive, fixed-priority processor partition. It intentionally rejects
EDF, the current PredictiveRuntime dynamic scheduler, multiple processors/resources,
and self-suspending task models instead of issuing an inapplicable certificate.

The recurrence, in integer microseconds, is::

    R_i(0)   = C_i + B_i + O_i
    R_i(k+1) = C_i + B_i + O_i
                 + sum(ceil((R_i(k) + J_j) / T_j) * (C_j + O_j))

where a larger integer priority denotes a higher-priority task.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from enum import Enum
import hashlib
import json
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from rts_predictive.config import DEFAULT_TASK_PROFILES, TaskProfile
from rts_predictive.verification.models import (
    AnalysisAssumptions,
    AnalysisProvenance,
    AnalysisRequest,
    AnalysisType,
    CertificateBinding,
    FixedPriorityTask,
    InterferenceContribution,
    IterationStep,
    TaskAnalysisResult,
    VerificationCertificate,
    VerificationStatus,
)


CERTIFICATE_SCHEMA_VERSION = "rts_predictive.rta-certificate/v1"
ANALYZER_NAME = "rts_predictive-fp-rta"
ANALYZER_VERSION = "1.0.1"


def _ceil_div(numerator: int, denominator: int) -> int:
    return (numerator + denominator - 1) // denominator


def _to_primitive(value: Any, *, omit_generated_at: bool = False) -> Any:
    """Convert certificate values into a canonical JSON-compatible form."""

    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        result = {}
        for item in fields(value):
            if omit_generated_at and item.name == "generated_at_utc":
                continue
            result[item.name] = _to_primitive(
                getattr(value, item.name), omit_generated_at=omit_generated_at
            )
        return result
    if isinstance(value, Mapping):
        return {
            str(key): _to_primitive(item, omit_generated_at=omit_generated_at)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [
            _to_primitive(item, omit_generated_at=omit_generated_at)
            for item in value
        ]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return {
        "unsupported_python_type": type(value).__qualname__,
        "representation": repr(value),
    }


def _sha256(payload: Any) -> str:
    encoded = json.dumps(
        _to_primitive(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalized_analysis_type(value: Any) -> str:
    if isinstance(value, AnalysisType):
        return value.value
    return str(value).strip().upper()


def _task_priority_sort_key(task: Any) -> Tuple[Any, ...]:
    if isinstance(task, FixedPriorityTask):
        return (0, -task.priority, task.task_id)
    return (1, type(task).__qualname__, repr(task))


def _task_id_sort_key(task: Any) -> Tuple[Any, ...]:
    if isinstance(task, FixedPriorityTask):
        return (0, task.task_id)
    return (1, type(task).__qualname__, repr(task))


def _sorted_tasks(tasks: Iterable[FixedPriorityTask]) -> Tuple[FixedPriorityTask, ...]:
    return tuple(sorted(tasks, key=_task_priority_sort_key))


def _request_payload(request: AnalysisRequest) -> Dict[str, Any]:
    """Semantic request payload; input task ordering does not affect its hash."""

    return {
        "schema_version": CERTIFICATE_SCHEMA_VERSION,
        "analysis_type": _normalized_analysis_type(request.analysis_type),
        "processor_count": request.processor_count,
        "max_iterations": request.max_iterations,
        "has_self_suspensions": request.has_self_suspensions,
        "binding": request.binding,
        "assumptions": request.assumptions,
        "tasks": _sorted_tasks(request.tasks),
    }


def _task_set_payload(tasks: Iterable[FixedPriorityTask]) -> Dict[str, Any]:
    return {
        "schema_version": CERTIFICATE_SCHEMA_VERSION,
        "tasks": tuple(sorted(tasks, key=_task_id_sort_key)),
    }


def _certificate_digest_payload(
    *,
    input_sha256: str,
    task_set_sha256: str,
    status: VerificationStatus,
    analysis_type: str,
    binding: CertificateBinding,
    assumptions: AnalysisAssumptions,
    provenance: AnalysisProvenance,
    tasks: Tuple[FixedPriorityTask, ...],
    results: Tuple[TaskAnalysisResult, ...],
    diagnostics: Tuple[str, ...],
) -> Dict[str, Any]:
    return {
        "schema_version": CERTIFICATE_SCHEMA_VERSION,
        "input_sha256": input_sha256,
        "task_set_sha256": task_set_sha256,
        "status": status,
        "analysis_type": analysis_type,
        "binding": binding,
        "assumptions": assumptions,
        # Audit timestamps do not change the mathematical certificate identity.
        "provenance": _to_primitive(provenance, omit_generated_at=True),
        "tasks": tasks,
        "results": results,
        "diagnostics": diagnostics,
    }


def _make_certificate(
    *,
    request: AnalysisRequest,
    provenance: AnalysisProvenance,
    status: VerificationStatus,
    results: Sequence[TaskAnalysisResult] = (),
    diagnostics: Sequence[str] = (),
) -> VerificationCertificate:
    analysis_type = _normalized_analysis_type(request.analysis_type)
    tasks = _sorted_tasks(request.tasks)
    result_tuple = tuple(results)
    diagnostic_tuple = tuple(diagnostics)
    input_sha256 = _sha256(_request_payload(request))
    task_set_sha256 = _sha256(_task_set_payload(tasks))
    digest_payload = _certificate_digest_payload(
        input_sha256=input_sha256,
        task_set_sha256=task_set_sha256,
        status=status,
        analysis_type=analysis_type,
        binding=request.binding,
        assumptions=request.assumptions,
        provenance=provenance,
        tasks=tasks,
        results=result_tuple,
        diagnostics=diagnostic_tuple,
    )
    certificate_sha256 = _sha256(digest_payload)
    return VerificationCertificate(
        schema_version=CERTIFICATE_SCHEMA_VERSION,
        certificate_id=f"fp-rta-{certificate_sha256[:16]}",
        certificate_sha256=certificate_sha256,
        input_sha256=input_sha256,
        task_set_sha256=task_set_sha256,
        status=status,
        analysis_type=analysis_type,
        binding=request.binding,
        assumptions=request.assumptions,
        provenance=provenance,
        tasks=tasks,
        results=result_tuple,
        diagnostics=diagnostic_tuple,
    )


def _validate_integer(name: str, value: Any, *, minimum: int) -> Optional[str]:
    if isinstance(value, bool) or not isinstance(value, int):
        return f"{name} must be an integer number of microseconds"
    if value < minimum:
        return f"{name} must be >= {minimum}"
    return None


def _validate_request(request: AnalysisRequest) -> Tuple[VerificationStatus, Tuple[str, ...]]:
    invalid: List[str] = []
    unsupported: List[str] = []
    analysis_type = _normalized_analysis_type(request.analysis_type)

    if analysis_type != AnalysisType.FP_PREEMPTIVE.value:
        unsupported.append(
            f"analysis type {analysis_type!r} is unsupported; only FP_PREEMPTIVE is implemented"
        )

    processor_error = _validate_integer("processor_count", request.processor_count, minimum=1)
    if processor_error:
        invalid.append(processor_error)
    elif request.processor_count != 1:
        unsupported.append("FP_PREEMPTIVE v1 supports exactly one processor")

    iteration_error = _validate_integer("max_iterations", request.max_iterations, minimum=1)
    if iteration_error:
        invalid.append(iteration_error)
    elif request.max_iterations > 1000:
        invalid.append("max_iterations must be <= 1000")

    if not isinstance(request.binding, CertificateBinding):
        invalid.append("binding must be a CertificateBinding")
    if not isinstance(request.assumptions, AnalysisAssumptions):
        invalid.append("assumptions must be AnalysisAssumptions")
    else:
        for field_name in ("independent_sporadic_tasks", "constrained_deadlines", "fully_preemptive",
                           "single_processor", "no_self_suspension"):
            if type(getattr(request.assumptions, field_name)) is not bool:
                invalid.append(f"assumptions.{field_name} must be boolean")
        for field_name, supported_model in (
            ("jitter_model", "bounded_higher_priority_release_jitter"),
            ("blocking_model", "one_bounded_blocking_term_per_analyzed_job"),
            ("overhead_model", "own_once_and_each_interfering_release"),
        ):
            if getattr(request.assumptions, field_name) != supported_model:
                unsupported.append(f"assumptions.{field_name} supports only {supported_model!r}")
        if request.has_self_suspensions or not request.assumptions.no_self_suspension:
            unsupported.append("self-suspending tasks are outside this analysis")
        if not request.assumptions.fully_preemptive:
            unsupported.append("non-preemptive scheduling is outside FP_PREEMPTIVE")
        if not request.assumptions.single_processor:
            unsupported.append("the assumptions do not declare a single processor")
        if not request.assumptions.independent_sporadic_tasks:
            unsupported.append("dependent tasks require a separately justified analysis")
        if not request.assumptions.constrained_deadlines:
            unsupported.append("only constrained-deadline task sets are supported")
        if request.assumptions.deadline_reference != "actual_release":
            unsupported.append("only deadlines relative to actual release are supported")
        if request.assumptions.priority_rule != "higher_integer_is_higher_priority":
            unsupported.append("only higher-integer static priority ordering is supported")

    if not isinstance(request.tasks, (tuple, list)) or not request.tasks:
        invalid.append("at least one task is required")
        tasks: Tuple[Any, ...] = ()
    else:
        tasks = tuple(request.tasks)

    seen_ids: set[str] = set()
    if type(request.has_self_suspensions) is not bool:
        invalid.append("has_self_suspensions must be boolean")
    active_priorities: Dict[int, str] = {}
    active_resources: set[str] = set()
    for index, task in enumerate(tasks):
        prefix = f"tasks[{index}]"
        if not isinstance(task, FixedPriorityTask):
            invalid.append(f"{prefix} must be a FixedPriorityTask")
            continue
        if type(task.suspended) is not bool:
            invalid.append(f"{prefix}.suspended must be boolean")
        if not isinstance(task.task_id, str) or not task.task_id.strip():
            invalid.append(f"{prefix}.task_id must be a non-empty string")
        elif task.task_id in seen_ids:
            invalid.append(f"duplicate task_id {task.task_id!r}")
        else:
            seen_ids.add(task.task_id)

        for field_name, minimum in (
            ("period_us", 1),
            ("deadline_us", 1),
            ("wcet_us", 0),
            ("jitter_us", 0),
            ("blocking_us", 0),
            ("overhead_us", 0),
        ):
            error = _validate_integer(
                f"{prefix}.{field_name}", getattr(task, field_name), minimum=minimum
            )
            if error:
                invalid.append(error)
        if isinstance(task.priority, bool) or not isinstance(task.priority, int):
            invalid.append(f"{prefix}.priority must be an integer")
        if not isinstance(task.resource_id, str) or not task.resource_id.strip():
            invalid.append(f"{prefix}.resource_id must be a non-empty string")

        if (
            isinstance(task.deadline_us, int)
            and isinstance(task.period_us, int)
            and task.deadline_us > task.period_us
        ):
            unsupported.append(
                f"task {task.task_id!r} has D > T; arbitrary-deadline RTA is not implemented"
            )

        if not task.suspended and isinstance(task.priority, int):
            previous = active_priorities.get(task.priority)
            if previous is not None:
                invalid.append(
                    f"tasks {previous!r} and {task.task_id!r} share priority {task.priority}; "
                    "a unique static priority order is required"
                )
            else:
                active_priorities[task.priority] = task.task_id
            if isinstance(task.resource_id, str) and task.resource_id:
                active_resources.add(task.resource_id)

    if not any(isinstance(task, FixedPriorityTask) and not task.suspended for task in tasks):
        invalid.append("at least one non-suspended task is required")
    if len(active_resources) > 1:
        unsupported.append(
            "multiple resource partitions cannot be combined in one uniprocessor certificate"
        )

    if invalid:
        return VerificationStatus.INVALID_INPUT, tuple(invalid + unsupported)
    if unsupported:
        return VerificationStatus.UNSUPPORTED, tuple(unsupported)
    return VerificationStatus.VERIFIED, ()


def _analyze_task(
    task: FixedPriorityTask,
    higher_priority: Tuple[FixedPriorityTask, ...],
    max_iterations: int,
) -> TaskAnalysisResult:
    base_cost = task.wcet_us + task.blocking_us + task.overhead_us
    steps: List[IterationStep] = [
        IterationStep(
            iteration=0,
            previous_response_us=None,
            base_cost_us=base_cost,
            interference=(),
            response_us=base_cost,
        )
    ]

    if base_cost > task.deadline_us:
        return TaskAnalysisResult(
            task_id=task.task_id,
            priority=task.priority,
            higher_priority_task_ids=tuple(item.task_id for item in higher_priority),
            status=VerificationStatus.NOT_SCHEDULABLE,
            iterations=tuple(steps),
            response_time_us=base_cost,
            deadline_us=task.deadline_us,
            margin_us=task.deadline_us - base_cost,
            converged=False,
        )

    previous = base_cost
    for iteration in range(1, max_iterations + 1):
        contributions: List[InterferenceContribution] = []
        interference_total = 0
        for interferer in higher_priority:
            releases = _ceil_div(
                previous + interferer.jitter_us, interferer.period_us
            )
            release_cost = interferer.wcet_us + interferer.overhead_us
            total = releases * release_cost
            contributions.append(
                InterferenceContribution(
                    task_id=interferer.task_id,
                    releases=releases,
                    jitter_us=interferer.jitter_us,
                    cost_per_release_us=release_cost,
                    total_interference_us=total,
                )
            )
            interference_total += total

        response = base_cost + interference_total
        steps.append(
            IterationStep(
                iteration=iteration,
                previous_response_us=previous,
                base_cost_us=base_cost,
                interference=tuple(contributions),
                response_us=response,
            )
        )

        if response > task.deadline_us:
            return TaskAnalysisResult(
                task_id=task.task_id,
                priority=task.priority,
                higher_priority_task_ids=tuple(item.task_id for item in higher_priority),
                status=VerificationStatus.NOT_SCHEDULABLE,
                iterations=tuple(steps),
                response_time_us=response,
                deadline_us=task.deadline_us,
                margin_us=task.deadline_us - response,
                converged=False,
            )
        if response == previous:
            return TaskAnalysisResult(
                task_id=task.task_id,
                priority=task.priority,
                higher_priority_task_ids=tuple(item.task_id for item in higher_priority),
                status=VerificationStatus.VERIFIED,
                iterations=tuple(steps),
                response_time_us=response,
                deadline_us=task.deadline_us,
                margin_us=task.deadline_us - response,
                converged=True,
            )
        previous = response

    return TaskAnalysisResult(
        task_id=task.task_id,
        priority=task.priority,
        higher_priority_task_ids=tuple(item.task_id for item in higher_priority),
        status=VerificationStatus.INCONCLUSIVE,
        iterations=tuple(steps),
        response_time_us=previous,
        deadline_us=task.deadline_us,
        margin_us=task.deadline_us - previous,
        converged=False,
    )


@dataclass(frozen=True)
class VerificationResult:
    """Legacy projection retained for existing callers.

    Callers that need auditable evidence should consume ``certificate``. The
    adapter only performs analysis when ``scheduler_type='FP_PREEMPTIVE'`` is
    explicitly requested; the historical EDF default is now unsupported.
    """

    is_verified: bool
    status: VerificationStatus
    status_statement: str
    nominal_utilization: float
    degraded_utilization: float
    interference_bound_ms: float
    worst_case_response_time_ms: float
    critical_deadline_ms: float
    assumptions: List[str]
    certificate: Optional[VerificationCertificate] = None


class TimingAnalyzer:
    """Exact analyzer for the deliberately narrow FP_PREEMPTIVE model."""

    @classmethod
    def analyze(
        cls,
        request: AnalysisRequest,
        *,
        provenance: Optional[AnalysisProvenance] = None,
    ) -> VerificationCertificate:
        if not isinstance(request, AnalysisRequest):
            fallback_request = AnalysisRequest(tasks=())
            return _make_certificate(
                request=fallback_request,
                provenance=provenance or AnalysisProvenance(),
                status=VerificationStatus.INVALID_INPUT,
                diagnostics=("request must be an AnalysisRequest",),
            )

        effective_provenance = provenance or AnalysisProvenance(
            analyzer_name=ANALYZER_NAME,
            analyzer_version=ANALYZER_VERSION,
        )
        validation_status, diagnostics = _validate_request(request)
        if validation_status is not VerificationStatus.VERIFIED:
            return _make_certificate(
                request=request,
                provenance=effective_provenance,
                status=validation_status,
                diagnostics=diagnostics,
            )

        active_tasks = tuple(task for task in _sorted_tasks(request.tasks) if not task.suspended)
        results: List[TaskAnalysisResult] = []
        for index, task in enumerate(active_tasks):
            results.append(
                _analyze_task(task, active_tasks[:index], request.max_iterations)
            )

        if any(result.status is VerificationStatus.NOT_SCHEDULABLE for result in results):
            overall_status = VerificationStatus.NOT_SCHEDULABLE
        elif any(result.status is VerificationStatus.INCONCLUSIVE for result in results):
            overall_status = VerificationStatus.INCONCLUSIVE
        else:
            overall_status = VerificationStatus.VERIFIED

        return _make_certificate(
            request=request,
            provenance=effective_provenance,
            status=overall_status,
            results=results,
        )

    @classmethod
    def analyze_task_set(
        cls,
        tasks: Sequence[FixedPriorityTask],
        *,
        analysis_type: Any = AnalysisType.FP_PREEMPTIVE,
        processor_count: int = 1,
        max_iterations: int = 1000,
        has_self_suspensions: bool = False,
        binding: Optional[CertificateBinding] = None,
        assumptions: Optional[AnalysisAssumptions] = None,
        provenance: Optional[AnalysisProvenance] = None,
    ) -> VerificationCertificate:
        return cls.analyze(
            AnalysisRequest(
                tasks=tuple(tasks),
                analysis_type=analysis_type,
                processor_count=processor_count,
                max_iterations=max_iterations,
                has_self_suspensions=has_self_suspensions,
                binding=binding or CertificateBinding(),
                assumptions=assumptions or AnalysisAssumptions(),
            ),
            provenance=provenance,
        )

    @classmethod
    def verify_fallback_mode(
        cls,
        critical_task_name: str,
        task_profiles: Optional[Dict[str, TaskProfile]] = None,
        scheduler_type: str = "EDF",
        *,
        jitter_ms: Optional[Mapping[str, float]] = None,
        blocking_ms: Optional[Mapping[str, float]] = None,
        overhead_ms: Optional[Mapping[str, float]] = None,
        max_iterations: int = 1000,
        binding: Optional[CertificateBinding] = None,
    ) -> VerificationResult:
        """Compatibility adapter for legacy task profiles.

        The adapter models all non-suspended tasks on one synthetic fallback
        partition. It is not a certificate for the heterogeneous simulator.
        Callers must explicitly request ``FP_PREEMPTIVE``; EDF, RM, and
        PredictiveRuntime are rejected because their runtime semantics do not match.
        """

        profiles = DEFAULT_TASK_PROFILES if task_profiles is None else task_profiles
        profile = profiles.get(critical_task_name)
        nominal_utilization = sum(
            item.wcet_ms / item.period_ms
            for item in profiles.values()
            if item.period_ms > 0
        )
        if profile is None:
            return VerificationResult(
                is_verified=False,
                status=VerificationStatus.INVALID_INPUT,
                status_statement=f"Task profile {critical_task_name!r} was not found",
                nominal_utilization=round(nominal_utilization, 6),
                degraded_utilization=0.0,
                interference_bound_ms=0.0,
                worst_case_response_time_ms=0.0,
                critical_deadline_ms=0.0,
                assumptions=[],
            )

        normalized_scheduler = str(scheduler_type).strip().upper()
        task_specs: List[FixedPriorityTask] = []
        effective_costs: Dict[str, float] = {}
        for name, item in profiles.items():
            suspended = name == "BackgroundLogging"
            effective_ms = (
                item.degraded_wcet_ms
                if item.is_critical or name == critical_task_name
                else item.wcet_ms
            )
            effective_costs[name] = effective_ms
            task_specs.append(
                FixedPriorityTask(
                    task_id=name,
                    period_us=_ms_to_us(item.period_ms, cost=False),
                    deadline_us=_ms_to_us(item.deadline_ms, cost=False),
                    wcet_us=0 if suspended else _ms_to_us(effective_ms, cost=True),
                    priority=item.priority,
                    jitter_us=_ms_to_us((jitter_ms or {}).get(name, 0.0), cost=True),
                    blocking_us=_ms_to_us((blocking_ms or {}).get(name, 0.0), cost=True),
                    overhead_us=_ms_to_us((overhead_ms or {}).get(name, 0.0), cost=True),
                    resource_id="legacy-fallback-partition",
                    suspended=suspended,
                    wcet_evidence="legacy TaskProfile configuration",
                )
            )

        request_type: Any = (
            AnalysisType.FP_PREEMPTIVE
            if normalized_scheduler == AnalysisType.FP_PREEMPTIVE.value
            else normalized_scheduler
        )
        certificate = cls.analyze_task_set(
            task_specs,
            analysis_type=request_type,
            max_iterations=max_iterations,
            binding=binding
            or CertificateBinding(resource_partition_id="legacy-fallback-partition"),
        )
        task_result = next(
            (item for item in certificate.results if item.task_id == critical_task_name),
            None,
        )
        degraded_utilization = sum(
            effective_costs[name] / item.period_ms
            for name, item in profiles.items()
            if name != "BackgroundLogging" and item.period_ms > 0
        )

        if task_result is None:
            response_ms = 0.0
            interference_ms = 0.0
        else:
            response_ms = task_result.response_time_us / 1000.0
            own = next(task for task in task_specs if task.task_id == critical_task_name)
            base_us = own.wcet_us + own.blocking_us + own.overhead_us
            interference_ms = max(0, task_result.response_time_us - base_us) / 1000.0

        statements = {
            VerificationStatus.VERIFIED: (
                "Schedulable under the matching FP_PREEMPTIVE certificate assumptions"
            ),
            VerificationStatus.NOT_SCHEDULABLE: (
                "Not schedulable under the requested FP_PREEMPTIVE assumptions"
            ),
            VerificationStatus.INCONCLUSIVE: (
                "Analysis did not converge within the configured iteration limit"
            ),
            VerificationStatus.UNSUPPORTED: (
                "Unsupported scheduler or task model; no schedulability claim issued"
            ),
            VerificationStatus.INVALID_INPUT: (
                "Invalid verification input; no schedulability claim issued"
            ),
        }
        assumption_text = [
            "Single fully preemptive fixed-priority processor partition",
            "Independent constrained-deadline periodic/sporadic tasks",
            "Deadlines are relative to actual release",
            "Higher integer values denote higher static priorities",
            "Configured WCET, jitter, blocking, and overhead bounds hold",
        ]
        assumption_text.extend(certificate.diagnostics)
        return VerificationResult(
            is_verified=certificate.is_verified and task_result is not None,
            status=certificate.status,
            status_statement=statements[certificate.status],
            nominal_utilization=round(nominal_utilization, 6),
            degraded_utilization=round(degraded_utilization, 6),
            interference_bound_ms=round(interference_ms, 6),
            worst_case_response_time_ms=round(response_ms, 6),
            critical_deadline_ms=profile.deadline_ms,
            assumptions=assumption_text,
            certificate=certificate,
        )


def _ms_to_us(value: float, *, cost: bool) -> int:
    """Conservatively project legacy millisecond floats into microseconds."""

    microseconds = Decimal(str(value)) * Decimal(1000)
    rounding = ROUND_CEILING if cost else ROUND_FLOOR
    return int(microseconds.to_integral_value(rounding=rounding))
