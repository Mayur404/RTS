"""
Task and Pipeline Job representations for Real-Time Systems simulation.
Models periods, deadlines, WCETs, slack, degraded states, and offloading metadata.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any
from ghostguard.config import TaskProfile


class TaskState(Enum):
    RELEASED = "RELEASED"
    READY = "READY"
    RUNNING = "RUNNING"
    OFFLOADED = "OFFLOADED"
    FALLBACK_ACTIVE = "FALLBACK_ACTIVE"
    COMPLETED = "COMPLETED"
    DEADLINE_MISSED = "DEADLINE_MISSED"
    ABANDONED = "ABANDONED"


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

    # Dynamic execution state
    state: TaskState = TaskState.RELEASED
    is_degraded: bool = False
    remaining_work_ms: float = 0.0     # Remaining execution work in ms
    start_time_ms: Optional[float] = None
    finish_time_ms: Optional[float] = None
    last_exec_timestamp_ms: Optional[float] = None

    # Offload metadata
    offload_target_id: Optional[str] = None
    offload_start_ms: Optional[float] = None
    offload_comm_delay_ms: float = 0.0
    is_remote_execution: bool = False
    origin_device_id: Optional[str] = None

    # Fallback metadata
    fallback_activated_ms: Optional[float] = None
    fallback_reason: Optional[str] = None

    def __post_init__(self):
        if self.remaining_work_ms <= 0.0:
            self.remaining_work_ms = self.nominal_wcet_ms
        if self.origin_device_id is None:
            self.origin_device_id = self.device_id

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
        if self.finish_time_ms is not None:
            return self.finish_time_ms <= self.deadline_ms
        return None

    def apply_degradation(self, current_time_ms: float, reason: str = "GhostGuard Safety Intervention"):
        """Degrades task parameters to the analytically bounded fallback mode."""
        if not self.is_degraded:
            self.is_degraded = True
            self.state = TaskState.FALLBACK_ACTIVE
            self.fallback_activated_ms = current_time_ms
            self.fallback_reason = reason
            # Scale remaining work proportionally or clamp to degraded WCET
            progress_ratio = 1.0 - (self.remaining_work_ms / max(self.nominal_wcet_ms, 0.001))
            progress_ratio = max(0.0, min(1.0, progress_ratio))
            self.remaining_work_ms = max(0.1, self.degraded_wcet_ms * (1.0 - progress_ratio))

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
            priority=profile.priority,
            remaining_work_ms=profile.wcet_ms,
            origin_device_id=device_id
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
