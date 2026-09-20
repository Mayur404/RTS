"""Typed inputs and outputs for conditional fixed-priority verification.

All analysis time values are integer microseconds.  The models deliberately
describe a narrow analyzable system rather than attempting to infer scheduler
semantics from the simulator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple, Union


class VerificationStatus(str, Enum):
    """Outcome of a verification request or one task's analysis."""

    VERIFIED = "VERIFIED"
    NOT_SCHEDULABLE = "NOT_SCHEDULABLE"
    INCONCLUSIVE = "INCONCLUSIVE"
    UNSUPPORTED = "UNSUPPORTED"
    INVALID_INPUT = "INVALID_INPUT"


class AnalysisType(str, Enum):
    """Analyses recognized by the certificate schema.

    Only ``FP_PREEMPTIVE`` is implemented in the first verification slice.
    The other names exist so unsupported requests receive a typed result.
    """

    FP_PREEMPTIVE = "FP_PREEMPTIVE"
    FP_WITH_BLOCKING = "FP_WITH_BLOCKING"
    EDF_DBF = "EDF_DBF"
    SIMULATION_ONLY = "SIMULATION_ONLY"


@dataclass(frozen=True)
class FixedPriorityTask:
    """One periodic/sporadic task assigned to a fixed-priority partition.

    A larger integer is a higher priority. ``overhead_us`` is charged once for
    the task under analysis and once for every interfering release of this task.
    ``blocking_us`` is a validated external bound, charged once to this task.
    """

    task_id: str
    period_us: int
    deadline_us: int
    wcet_us: int
    priority: int
    jitter_us: int = 0
    blocking_us: int = 0
    overhead_us: int = 0
    resource_id: str = "cpu0"
    suspended: bool = False
    blocking_sources: Tuple[str, ...] = field(default_factory=tuple)
    wcet_evidence: Optional[str] = None


@dataclass(frozen=True)
class CertificateBinding:
    """Configuration identifiers to which a certificate may be bound."""

    scenario_hash: str = "UNBOUND"
    scheduler_config_hash: str = "UNBOUND"
    hardware_profile_hash: str = "UNBOUND"
    resource_partition_id: str = "UNBOUND"
    fallback_mode_id: str = "UNBOUND"


@dataclass(frozen=True)
class AnalysisAssumptions:
    """Structured assumptions required by the implemented recurrence."""

    independent_sporadic_tasks: bool = True
    constrained_deadlines: bool = True
    fully_preemptive: bool = True
    single_processor: bool = True
    no_self_suspension: bool = True
    deadline_reference: str = "actual_release"
    priority_rule: str = "higher_integer_is_higher_priority"
    jitter_model: str = "bounded_higher_priority_release_jitter"
    blocking_model: str = "one_bounded_blocking_term_per_analyzed_job"
    overhead_model: str = "own_once_and_each_interfering_release"
    additional: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AnalysisProvenance:
    """Origin of an analysis.

    ``generated_at_utc`` is audit metadata and is intentionally excluded from
    the deterministic certificate digest.
    """

    analyzer_name: str = "ghostguard-fp-rta"
    analyzer_version: str = "1.0.0"
    code_revision: str = "UNKNOWN"
    generated_at_utc: Optional[str] = None
    source_artifact_hashes: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AnalysisRequest:
    """Complete input to fixed-priority response-time analysis."""

    tasks: Tuple[FixedPriorityTask, ...]
    analysis_type: Union[AnalysisType, str] = AnalysisType.FP_PREEMPTIVE
    processor_count: int = 1
    max_iterations: int = 1000
    has_self_suspensions: bool = False
    binding: CertificateBinding = field(default_factory=CertificateBinding)
    assumptions: AnalysisAssumptions = field(default_factory=AnalysisAssumptions)


@dataclass(frozen=True)
class InterferenceContribution:
    """One higher-priority task's contribution to an iteration."""

    task_id: str
    releases: int
    jitter_us: int
    cost_per_release_us: int
    total_interference_us: int


@dataclass(frozen=True)
class IterationStep:
    """One auditable fixed-point step, including initialization at step zero."""

    iteration: int
    previous_response_us: Optional[int]
    base_cost_us: int
    interference: Tuple[InterferenceContribution, ...]
    response_us: int


@dataclass(frozen=True)
class TaskAnalysisResult:
    """Fixed-point result for one task."""

    task_id: str
    priority: int
    higher_priority_task_ids: Tuple[str, ...]
    status: VerificationStatus
    iterations: Tuple[IterationStep, ...]
    response_time_us: int
    deadline_us: int
    margin_us: int
    converged: bool


@dataclass(frozen=True)
class VerificationCertificate:
    """Deterministically identified conditional schedulability certificate."""

    schema_version: str
    certificate_id: str
    certificate_sha256: str
    input_sha256: str
    task_set_sha256: str
    status: VerificationStatus
    analysis_type: str
    binding: CertificateBinding
    assumptions: AnalysisAssumptions
    provenance: AnalysisProvenance
    tasks: Tuple[FixedPriorityTask, ...]
    results: Tuple[TaskAnalysisResult, ...]
    diagnostics: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_verified(self) -> bool:
        return self.status is VerificationStatus.VERIFIED
