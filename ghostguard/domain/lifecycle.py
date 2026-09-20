"""Runtime job, task, and attempt lifecycle with single-commit semantics."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .specs import PipelineSpec, TaskSpec, _identifier, _int_us


class TaskInstanceState(str, Enum):
    BLOCKED = "BLOCKED"
    READY = "READY"
    DISPATCHED = "DISPATCHED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    COMMITTED = "COMMITTED"
    DEADLINE_MISSED = "DEADLINE_MISSED"


class AttemptState(str, Enum):
    CREATED = "CREATED"
    DISPATCHED = "DISPATCHED"
    RUNNING = "RUNNING"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    COMMITTED = "COMMITTED"
    LATE_RESULT_DISCARDED = "LATE_RESULT_DISCARDED"
    FAILED = "FAILED"


class AttemptKind(str, Enum):
    LOCAL = "local"
    REMOTE = "remote"
    DEGRADED = "degraded"


@dataclass
class ExecutionAttempt:
    attempt_id: str
    task_instance_id: str
    kind: AttemptKind
    target_device_id: str
    state: AttemptState = AttemptState.CREATED
    created_at_us: int = 0
    started_at_us: int | None = None
    completed_at_us: int | None = None
    cancelled_at_us: int | None = None
    service_received_us: int = 0
    network_bytes: int = 0

    def __post_init__(self) -> None:
        for name in ("attempt_id", "task_instance_id", "target_device_id"):
            _identifier(getattr(self, name), name)
        if not isinstance(self.kind, AttemptKind):
            self.kind = AttemptKind(self.kind)
        if not isinstance(self.state, AttemptState):
            self.state = AttemptState(self.state)
        _int_us(self.created_at_us, "created_at_us")
        _int_us(self.service_received_us, "service_received_us")
        _int_us(self.network_bytes, "network_bytes")

    def dispatch(self) -> None:
        self._require(AttemptState.CREATED)
        self.state = AttemptState.DISPATCHED

    def start(self, timestamp_us: int) -> None:
        _int_us(timestamp_us, "timestamp_us")
        if self.state not in (AttemptState.CREATED, AttemptState.DISPATCHED):
            raise ValueError(f"cannot start attempt in {self.state.value}")
        if timestamp_us < self.created_at_us:
            raise ValueError("attempt cannot start before it is created")
        self.started_at_us = timestamp_us
        self.state = AttemptState.RUNNING

    def charge(self, *, service_us: int = 0, network_bytes: int = 0) -> None:
        _int_us(service_us, "service_us")
        _int_us(network_bytes, "network_bytes")
        self.service_received_us += service_us
        self.network_bytes += network_bytes

    def request_cancel(self) -> None:
        if self.state in (AttemptState.CANCEL_REQUESTED, AttemptState.CANCELLED):
            return
        if self.state not in (AttemptState.CREATED, AttemptState.DISPATCHED, AttemptState.RUNNING):
            raise ValueError(f"cannot request cancellation in {self.state.value}")
        self.state = AttemptState.CANCEL_REQUESTED

    def acknowledge_cancel(self, timestamp_us: int) -> None:
        _int_us(timestamp_us, "timestamp_us")
        if self.state is AttemptState.CANCELLED:
            return
        self._require(AttemptState.CANCEL_REQUESTED)
        self.cancelled_at_us = timestamp_us
        self.state = AttemptState.CANCELLED

    def complete(self, timestamp_us: int) -> bool:
        """Record completion; return false and mark a result late after cancellation."""

        _int_us(timestamp_us, "timestamp_us")
        if self.state in (AttemptState.CANCEL_REQUESTED, AttemptState.CANCELLED):
            self.completed_at_us = timestamp_us
            self.state = AttemptState.LATE_RESULT_DISCARDED
            return False
        if self.state is AttemptState.COMPLETED:
            return True
        if self.state in (AttemptState.COMMITTED, AttemptState.LATE_RESULT_DISCARDED):
            return self.state is AttemptState.COMMITTED
        if self.state not in (AttemptState.DISPATCHED, AttemptState.RUNNING):
            raise ValueError(f"cannot complete attempt in {self.state.value}")
        if self.started_at_us is not None and timestamp_us < self.started_at_us:
            raise ValueError("attempt cannot complete before it starts")
        self.completed_at_us = timestamp_us
        self.state = AttemptState.COMPLETED
        return True

    def discard_late_result(self, timestamp_us: int) -> None:
        _int_us(timestamp_us, "timestamp_us")
        self.completed_at_us = timestamp_us
        self.state = AttemptState.LATE_RESULT_DISCARDED

    def _require(self, expected: AttemptState) -> None:
        if self.state is not expected:
            raise ValueError(f"expected {expected.value}, found {self.state.value}")


@dataclass
class TaskInstance:
    instance_id: str
    job_id: str
    spec: TaskSpec
    release_time_us: int
    absolute_deadline_us: int
    predecessor_ids: tuple[str, ...] = ()
    state: TaskInstanceState = TaskInstanceState.BLOCKED
    attempts: dict[str, ExecutionAttempt] = field(default_factory=dict)
    committed_attempt_id: str | None = None
    committed_at_us: int | None = None

    def __post_init__(self) -> None:
        _identifier(self.instance_id, "instance_id")
        _identifier(self.job_id, "job_id")
        _int_us(self.release_time_us, "release_time_us")
        _int_us(self.absolute_deadline_us, "absolute_deadline_us", positive=True)
        if self.absolute_deadline_us <= self.release_time_us:
            raise ValueError("absolute deadline must follow release time")
        self.predecessor_ids = tuple(self.predecessor_ids)
        if not self.predecessor_ids and self.state is TaskInstanceState.BLOCKED:
            self.state = TaskInstanceState.READY

    def add_attempt(self, attempt: ExecutionAttempt) -> None:
        if attempt.task_instance_id != self.instance_id:
            raise ValueError("attempt belongs to another task instance")
        if attempt.attempt_id in self.attempts:
            raise ValueError(f"duplicate attempt ID: {attempt.attempt_id}")
        if self.committed_attempt_id is not None:
            raise ValueError("cannot add an attempt after the task result is committed")
        self.attempts[attempt.attempt_id] = attempt

    def create_attempt(
        self,
        attempt_id: str,
        kind: AttemptKind,
        target_device_id: str,
        created_at_us: int,
    ) -> ExecutionAttempt:
        attempt = ExecutionAttempt(
            attempt_id=attempt_id,
            task_instance_id=self.instance_id,
            kind=kind,
            target_device_id=target_device_id,
            created_at_us=created_at_us,
        )
        self.add_attempt(attempt)
        return attempt

    def dispatch_attempt(self, attempt_id: str) -> None:
        if self.state not in (TaskInstanceState.READY, TaskInstanceState.DISPATCHED, TaskInstanceState.RUNNING):
            raise ValueError(f"cannot dispatch an attempt while task is {self.state.value}")
        self.attempts[attempt_id].dispatch()
        if self.state is TaskInstanceState.READY:
            self.state = TaskInstanceState.DISPATCHED

    def start_attempt(self, attempt_id: str, timestamp_us: int) -> None:
        if self.committed_attempt_id is not None:
            raise ValueError("cannot start an attempt after the task result is committed")
        self.attempts[attempt_id].start(timestamp_us)
        self.state = TaskInstanceState.RUNNING

    def complete_attempt(self, attempt_id: str, timestamp_us: int) -> bool:
        attempt = self.attempts[attempt_id]
        if self.committed_attempt_id is not None and self.committed_attempt_id != attempt_id:
            attempt.discard_late_result(timestamp_us)
            return False
        completed = attempt.complete(timestamp_us)
        if completed and self.committed_attempt_id is None:
            self.state = TaskInstanceState.COMPLETED
        return completed

    def request_attempt_cancel(self, attempt_id: str) -> None:
        self.attempts[attempt_id].request_cancel()

    def acknowledge_attempt_cancel(self, attempt_id: str, timestamp_us: int) -> None:
        self.attempts[attempt_id].acknowledge_cancel(timestamp_us)

    def mark_ready(self) -> None:
        if self.state is TaskInstanceState.READY:
            return
        if self.state is not TaskInstanceState.BLOCKED:
            raise ValueError(f"cannot make task ready from {self.state.value}")
        self.state = TaskInstanceState.READY

    def commit_attempt(self, attempt_id: str, timestamp_us: int) -> bool:
        """Commit one result; repeat delivery is idempotent and rivals are discarded."""

        _int_us(timestamp_us, "timestamp_us")
        attempt = self.attempts.get(attempt_id)
        if attempt is None:
            raise KeyError(f"unknown attempt ID: {attempt_id}")
        if self.committed_attempt_id == attempt_id:
            return False
        if self.committed_attempt_id is not None:
            attempt.discard_late_result(timestamp_us)
            return False
        if attempt.state is not AttemptState.COMPLETED:
            if attempt.state in (
                AttemptState.CANCEL_REQUESTED,
                AttemptState.CANCELLED,
                AttemptState.LATE_RESULT_DISCARDED,
            ):
                attempt.discard_late_result(timestamp_us)
                return False
            raise ValueError("only a completed attempt can commit")
        self.committed_attempt_id = attempt_id
        self.committed_at_us = timestamp_us
        self.state = TaskInstanceState.COMMITTED
        attempt.state = AttemptState.COMMITTED
        return True

    @property
    def committed_attempt(self) -> ExecutionAttempt | None:
        if self.committed_attempt_id is None:
            return None
        return self.attempts[self.committed_attempt_id]


@dataclass
class PipelineJob:
    job_id: str
    pipeline_spec: PipelineSpec
    release_time_us: int
    absolute_deadline_us: int
    tasks: dict[str, TaskInstance]
    completed_at_us: int | None = None
    dropped_at_us: int | None = None

    @classmethod
    def from_spec(cls, job_id: str, spec: PipelineSpec, release_time_us: int) -> "PipelineJob":
        _identifier(job_id, "job_id")
        _int_us(release_time_us, "release_time_us")
        predecessors: dict[str, list[str]] = {task.task_id: [] for task in spec.tasks}
        for source, target in spec.dependency_edges:
            predecessors[target].append(source)
        tasks = {
            task_spec.task_id: TaskInstance(
                instance_id=f"{job_id}:{task_spec.task_id}",
                job_id=job_id,
                spec=task_spec,
                release_time_us=release_time_us,
                absolute_deadline_us=min(
                    release_time_us + task_spec.relative_deadline_us,
                    release_time_us + spec.end_to_end_deadline_us,
                ),
                predecessor_ids=tuple(sorted(predecessors[task_spec.task_id])),
            )
            for task_spec in spec.tasks
        }
        return cls(
            job_id=job_id,
            pipeline_spec=spec,
            release_time_us=release_time_us,
            absolute_deadline_us=release_time_us + spec.end_to_end_deadline_us,
            tasks=tasks,
        )

    def commit_attempt(self, task_id: str, attempt_id: str, timestamp_us: int) -> tuple[str, ...]:
        """Commit a task result and return newly ready successor task IDs."""

        task = self.tasks[task_id]
        changed = task.commit_attempt(attempt_id, timestamp_us)
        if not changed:
            return ()
        newly_ready: list[str] = []
        for candidate_id, candidate in self.tasks.items():
            if candidate.state is not TaskInstanceState.BLOCKED:
                continue
            if all(self.tasks[pred].state is TaskInstanceState.COMMITTED for pred in candidate.predecessor_ids):
                candidate.mark_ready()
                newly_ready.append(candidate_id)
        sink = self.tasks[self.pipeline_spec.sink_task_id]
        if sink.state is TaskInstanceState.COMMITTED:
            self.completed_at_us = timestamp_us
        return tuple(sorted(newly_ready))

    @property
    def is_complete(self) -> bool:
        return self.completed_at_us is not None
