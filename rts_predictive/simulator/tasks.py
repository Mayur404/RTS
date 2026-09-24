"""
Task and Pipeline Job representations for Real-Time Systems simulation.
Models periods, deadlines, WCETs, slack, degraded states, and offloading metadata.
"""

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Optional, Dict, Any
import random
from rts_predictive.config import TaskProfile


class TaskState(Enum):
    RELEASED = "RELEASED"
    READY = "READY"
    RUNNING = "RUNNING"
    OFFLOADED = "OFFLOADED"
    FALLBACK_ACTIVE = "FALLBACK_ACTIVE"
    COMPLETED = "COMPLETED"
    DEADLINE_MISSED = "DEADLINE_MISSED"
    ABANDONED = "ABANDONED"


@dataclass(frozen=True)
class RuntimeExitPoint:
    """Executable projection of a configured early-exit checkpoint."""

    checkpoint_id: str
    elapsed_work_start_ms: float
    elapsed_work_end_ms: float
    checkpoint_overhead_ms: float
    remaining_wcet_ms: float
    output_utility: float
    structurally_valid: bool = True


@dataclass
class TaskInstance:
    """An individual job instance of a real-time task released at runtime."""
    instance_id: str
    task_name: str
    device_id: str
    release_time_ms: float
    deadline_ms: float                # Absolute deadline timestamp
    period_ms: float
    nominal_wcet_ms: float
    degraded_wcet_ms: float
    is_critical: bool
    is_offloadable: bool
    requires_gpu: bool
    cpu_util_fraction: float
    gpu_util_fraction: float
    memory_mb: float
    payload_kb: float
    priority: int
    response_payload_kb: float = 0.0

    # Dynamic execution state
    state: TaskState = TaskState.RELEASED
    is_degraded: bool = False
    remaining_work_ms: float = 0.0     # Remaining execution work in ms
    initial_execution_work_ms: float = 0.0
    execution_distribution_kind: str = "fixed"
    execution_bcet_ms: float = 0.0
    execution_wcet_ms: float = 0.0
    execution_sampled: bool = False
    start_time_ms: Optional[float] = None
    finish_time_ms: Optional[float] = None
    last_exec_timestamp_ms: Optional[float] = None
    executed_service_ms: float = 0.0
    execution_start_cpu_util: Optional[float] = None
    execution_start_gpu_util: Optional[float] = None
    output_utility: float = 1.0

    # DAG Precedence & Attempt Tracking
    pipeline_job_id: Optional[str] = None
    predecessor_ids: tuple[str, ...] = ()
    successor_ids: tuple[str, ...] = ()
    attempt_id: Optional[str] = None
    is_cancelled: bool = False

    # Offload metadata
    offload_target_id: Optional[str] = None
    offload_start_ms: Optional[float] = None
    offload_comm_delay_ms: float = 0.0
    is_remote_execution: bool = False
    origin_device_id: Optional[str] = None

    # Fallback metadata
    fallback_activated_ms: Optional[float] = None
    fallback_reason: Optional[str] = None
    checkpoint_id: Optional[str] = None
    exit_points: tuple[RuntimeExitPoint, ...] = ()


    def __post_init__(self):
        # Event timestamps are integer microseconds. Keep task release and
        # deadline comparisons on the same grid as the event queue.
        self.release_time_ms = self._quantize_ms(self.release_time_ms)
        self.deadline_ms = self._quantize_ms(self.deadline_ms)
        if self.deadline_ms <= self.release_time_ms:
            raise ValueError("task deadline must follow its release")
        if self.remaining_work_ms <= 0.0:
            self.remaining_work_ms = self.nominal_wcet_ms
        if self.initial_execution_work_ms <= 0.0:
            self.initial_execution_work_ms = self.remaining_work_ms
        if self.execution_bcet_ms <= 0.0:
            self.execution_bcet_ms = self.nominal_wcet_ms
        if self.execution_wcet_ms <= 0.0:
            self.execution_wcet_ms = self.nominal_wcet_ms
        if self.origin_device_id is None:
            self.origin_device_id = self.device_id

    @staticmethod
    def _quantize_ms(value: float) -> float:
        us = int((Decimal(str(value)) * 1000).to_integral_value(rounding=ROUND_HALF_UP))
        if us < 0:
            raise ValueError("task time must be non-negative")
        return us / 1000.0

    @property
    def current_wcet(self) -> float:
        return self.degraded_wcet_ms if self.is_degraded else self.nominal_wcet_ms

    def slack_ms(self, current_time_ms: float) -> float:
        """Current dynamic slack: S(t) = deadline - current_time - remaining_work."""
        return self.deadline_ms - current_time_ms - self.remaining_work_ms

    @property
    def response_time_ms(self) -> Optional[float]:
        """R_i = finish_time - release_time."""
        if self.finish_time_ms is not None:
            return self.finish_time_ms - self.release_time_ms
        return None

    @property
    def lateness_ms(self) -> Optional[float]:
        """L_i = finish_time - deadline."""
        if self.finish_time_ms is not None:
            return self.finish_time_ms - self.deadline_ms
        return None

    @property
    def deadline_met(self) -> Optional[bool]:
        if self.state == TaskState.DEADLINE_MISSED:
            return False
        if self.finish_time_ms is not None:
            return self.finish_time_ms <= self.deadline_ms
        return None

    def apply_degradation(
        self,
        current_time_ms: float,
        reason: str = "PredictiveRuntime Safety Intervention",
        execution_rate: float = 1.0,
        interference_bound_ms: float = 0.0,
    ) -> bool:
        """Activate the best valid, reachable, deadline-feasible exit point.

        Remaining execution is taken directly from the task specification. It is
        never inferred by scaling nominal WCET from observed progress.
        """
        if self.is_degraded:
            return True

        elapsed_work_ms = max(0.0, self.initial_execution_work_ms - self.remaining_work_ms)
        if execution_rate <= 0 or interference_bound_ms < 0:
            raise ValueError("fallback feasibility requires positive rate and non-negative interference")
        eligible = [
            point
            for point in self.exit_points
            if point.structurally_valid
            and point.elapsed_work_start_ms <= elapsed_work_ms <= point.elapsed_work_end_ms
            and current_time_ms
            + (point.checkpoint_overhead_ms + point.remaining_wcet_ms) / execution_rate
            + interference_bound_ms
            <= self.deadline_ms
        ]
        if not eligible:
            return False

        # Preserve the most useful output; break ties by the smallest recovery
        # cost and then checkpoint ID so replay is deterministic.
        selected = sorted(
            eligible,
            key=lambda point: (
                -point.output_utility,
                point.checkpoint_overhead_ms + point.remaining_wcet_ms,
                point.checkpoint_id,
            ),
        )[0]
        self.is_degraded = True
        self.state = TaskState.FALLBACK_ACTIVE
        self.fallback_activated_ms = self._quantize_ms(current_time_ms)
        self.fallback_reason = reason
        self.checkpoint_id = selected.checkpoint_id
        self.output_utility = min(self.output_utility, selected.output_utility)
        self.degraded_wcet_ms = selected.remaining_wcet_ms
        self.remaining_work_ms = self._quantize_ms(
            selected.checkpoint_overhead_ms + selected.remaining_wcet_ms
        )
        return True

    def sample_execution_work(self, rng: random.Random) -> float:
        """Sample this attempt exactly once from its configured bounded model."""
        if self.execution_sampled:
            return self.initial_execution_work_ms
        kind = self.execution_distribution_kind.lower()
        if kind in ("constant", "fixed"):
            sampled = self.nominal_wcet_ms
        elif kind == "bounded_uniform":
            sampled = rng.uniform(self.execution_bcet_ms, self.execution_wcet_ms)
        elif kind == "triangular":
            sampled = rng.triangular(
                self.execution_bcet_ms,
                self.execution_wcet_ms,
                self.nominal_wcet_ms,
            )
        else:
            raise ValueError(f"unsupported execution distribution: {self.execution_distribution_kind}")
        sampled = self._quantize_ms(sampled)
        self.initial_execution_work_ms = sampled
        self.remaining_work_ms = sampled
        self.execution_sampled = True
        return sampled

    @classmethod
    def from_task_spec(
        cls,
        spec: Any,
        instance_id: str,
        device_id: str,
        release_time_ms: float,
        pipeline_job_id: Optional[str] = None,
        predecessor_ids: tuple = (),
        successor_ids: tuple = (),
    ) -> "TaskInstance":
        from rts_predictive.domain.specs import ResourceKind, Criticality
        cpu_u = 0.2
        gpu_u = 0.0
        requires_gpu = False
        mem_mb = 128.0
        for demand in getattr(spec, "resource_demands", ()):
            if demand.resource == ResourceKind.CPU:
                cpu_u = demand.utilization_fraction
            elif demand.resource == ResourceKind.GPU:
                gpu_u = demand.utilization_fraction
                requires_gpu = True
            if demand.memory_bytes > 0:
                mem_mb = demand.memory_bytes / (1024 * 1024)

        nominal_ms = getattr(spec.wcet_distribution, "nominal_us", 10_000) / 1000.0
        degraded_ms = nominal_ms * 0.5
        configured_exit_points = tuple(
            RuntimeExitPoint(
                checkpoint_id=point.checkpoint_id,
                elapsed_work_start_ms=point.elapsed_work_interval_us[0] / 1000.0,
                elapsed_work_end_ms=point.elapsed_work_interval_us[1] / 1000.0,
                checkpoint_overhead_ms=point.checkpoint_overhead_us / 1000.0,
                remaining_wcet_ms=point.remaining_wcet_us / 1000.0,
                output_utility=point.output_utility,
                structurally_valid=point.structurally_valid,
            )
            for point in getattr(spec, "exit_points", ())
        )
        if configured_exit_points:
            degraded_ms = min(point.remaining_wcet_ms for point in configured_exit_points)

        period_ms = (getattr(spec, "period_us", 50_000) or 50_000) / 1000.0
        rel_dl = getattr(spec, "relative_deadline_us", int(period_ms * 1000)) / 1000.0
        deadline_ms = release_time_ms + rel_dl

        return cls(
            instance_id=instance_id,
            task_name=spec.task_id,
            device_id=device_id,
            release_time_ms=release_time_ms,
            deadline_ms=deadline_ms,
            period_ms=period_ms,
            nominal_wcet_ms=nominal_ms,
            degraded_wcet_ms=degraded_ms,
            is_critical=(getattr(spec, "criticality", Criticality.HIGH) == Criticality.HIGH),
            is_offloadable=getattr(spec, "offloadable", False),
            requires_gpu=requires_gpu,
            cpu_util_fraction=cpu_u,
            gpu_util_fraction=gpu_u,
            memory_mb=mem_mb,
            payload_kb=getattr(spec, "request_payload_bytes", 0) / 1024.0,
            response_payload_kb=getattr(spec, "result_payload_bytes", 0) / 1024.0,
            priority=getattr(spec, "priority", 1),
            remaining_work_ms=nominal_ms,
            execution_distribution_kind=getattr(spec.wcet_distribution, "kind", "constant"),
            execution_bcet_ms=getattr(spec.wcet_distribution, "bcet_us", int(nominal_ms * 1000)) / 1000.0,
            execution_wcet_ms=getattr(spec.wcet_distribution, "wcet_us", int(nominal_ms * 1000)) / 1000.0,
            origin_device_id=device_id,
            pipeline_job_id=pipeline_job_id,
            predecessor_ids=tuple(predecessor_ids),
            successor_ids=tuple(successor_ids),
            exit_points=configured_exit_points,
            output_utility=getattr(spec, "output_utility", 1.0),
        )

    @classmethod
    def from_profile(
        cls,
        profile: TaskProfile,
        instance_id: str,
        device_id: str,
        release_time_ms: float,
        sporadic: bool = False,
        jitter_ms: float = 0.0
    ) -> "TaskInstance":
        actual_release = release_time_ms + jitter_ms
        deadline = actual_release + profile.deadline_ms
        # TaskProfile predates canonical ExitPointSpec. Its degraded WCET is
        # represented as an explicit compatibility checkpoint so every runtime
        # transition still selects a concrete exit rather than scaling progress.
        compatibility_exit = RuntimeExitPoint(
            checkpoint_id=f"{profile.name}_configured_degraded_mode",
            elapsed_work_start_ms=0.0,
            elapsed_work_end_ms=profile.wcet_ms,
            checkpoint_overhead_ms=0.0,
            remaining_wcet_ms=profile.degraded_wcet_ms,
            output_utility=0.8,
        )
        return cls(
            instance_id=instance_id,
            task_name=profile.name,
            device_id=device_id,
            release_time_ms=actual_release,
            deadline_ms=deadline,
            period_ms=profile.period_ms,
            nominal_wcet_ms=profile.wcet_ms,
            degraded_wcet_ms=profile.degraded_wcet_ms,
            is_critical=profile.is_critical,
            is_offloadable=profile.is_offloadable,
            requires_gpu=profile.requires_gpu,
            cpu_util_fraction=profile.cpu_util_fraction,
            gpu_util_fraction=profile.gpu_util_fraction,
            memory_mb=profile.memory_mb,
            payload_kb=profile.data_payload_kb,
            response_payload_kb=profile.data_payload_kb,
            priority=profile.priority,
            remaining_work_ms=profile.wcet_ms,
            execution_sampled=True,
            origin_device_id=device_id,
            exit_points=(compatibility_exit,),
        )



@dataclass
class PipelineJob:
    """Represents an end-to-end mission pipeline iteration for an autonomous agent."""
    job_id: str
    device_id: str
    release_time_ms: float
    tasks: Dict[str, TaskInstance] = field(default_factory=dict)
    is_completed: bool = False
    pipeline_deadline_ms: float = 0.0
