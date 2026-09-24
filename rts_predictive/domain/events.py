"""Canonical event record and deterministic ordering contract."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from functools import total_ordering
from typing import Any, Mapping

from .serialization import canonical_json, canonical_sha256, freeze_mapping, to_canonical_data
from .specs import SCHEMA_VERSION, _identifier, _int_us


class EventType(str, Enum):
    PIPELINE_RELEASE = "PIPELINE_RELEASE"
    TASK_READY = "TASK_READY"
    DISPATCH_DECISION_START = "DISPATCH_DECISION_START"
    DISPATCH_DECISION_END = "DISPATCH_DECISION_END"
    EXECUTION_START = "EXECUTION_START"
    EXECUTION_QUANTUM_END = "EXECUTION_QUANTUM_END"
    PREEMPT = "PREEMPT"
    CHECKPOINT_REACHED = "CHECKPOINT_REACHED"
    REQUEST_TX_START = "REQUEST_TX_START"
    REQUEST_TX_END = "REQUEST_TX_END"
    REMOTE_EXECUTION_START = "REMOTE_EXECUTION_START"
    RESULT_TX_START = "RESULT_TX_START"
    RESULT_TX_END = "RESULT_TX_END"
    WATCHDOG_TICK = "WATCHDOG_TICK"
    CANCEL_REQUEST = "CANCEL_REQUEST"
    CANCEL_ACK = "CANCEL_ACK"
    LATE_RESULT_DISCARDED = "LATE_RESULT_DISCARDED"
    DEADLINE = "DEADLINE"
    TASK_COMMIT = "TASK_COMMIT"
    PIPELINE_COMPLETE = "PIPELINE_COMPLETE"
    PIPELINE_DROP = "PIPELINE_DROP"
    FAULT_START = "FAULT_START"
    FAULT_END = "FAULT_END"
    THERMAL_UPDATE = "THERMAL_UPDATE"
    LINK_STATE_CHANGE = "LINK_STATE_CHANGE"
    FL_LOCAL_TRAIN_START = "FL_LOCAL_TRAIN_START"
    FL_LOCAL_TRAIN_END = "FL_LOCAL_TRAIN_END"
    FL_UPLOAD_START = "FL_UPLOAD_START"
    FL_UPLOAD_END = "FL_UPLOAD_END"
    FL_AGGREGATE = "FL_AGGREGATE"
    MODEL_PUBLISH = "MODEL_PUBLISH"


_RESERVED_PAYLOAD_FIELDS = frozenset(
    {
        "schema_version",
        "event_id",
        "run_id",
        "timestamp_us",
        "priority",
        "sequence",
        "event_type",
        "device_id",
        "pipeline_id",
        "job_id",
        "task_id",
        "attempt_id",
    }
)


@total_ordering
@dataclass(frozen=True)
class Event:
    """An immutable event ordered solely by simulation queue coordinates."""

    timestamp_us: int
    priority: int
    sequence: int
    event_type: EventType
    event_id: str
    run_id: str
    schema_version: str = SCHEMA_VERSION
    device_id: str | None = None
    pipeline_id: str | None = None
    job_id: str | None = None
    task_id: str | None = None
    attempt_id: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        _int_us(self.timestamp_us, "timestamp_us")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise TypeError("priority must be an integer")
        _int_us(self.sequence, "sequence")
        if not isinstance(self.event_type, EventType):
            object.__setattr__(self, "event_type", EventType(self.event_type))
        for name in ("event_id", "run_id", "schema_version"):
            _identifier(getattr(self, name), name)
        for name in ("device_id", "pipeline_id", "job_id", "task_id", "attempt_id"):
            value = getattr(self, name)
            if value is not None:
                _identifier(value, name)
        overlap = _RESERVED_PAYLOAD_FIELDS.intersection(self.payload)
        if overlap:
            raise ValueError(f"payload cannot shadow reserved event fields: {sorted(overlap)}")
        object.__setattr__(self, "payload", freeze_mapping(self.payload))
        to_canonical_data(self.payload)

    @property
    def queue_key(self) -> tuple[int, int, int]:
        return self.timestamp_us, self.priority, self.sequence

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Event):
            return NotImplemented
        return self.queue_key < other.queue_key

    def to_dict(self) -> dict[str, Any]:
        return to_canonical_data(self)

    def to_json(self) -> str:
        return canonical_json(self)

    @property
    def event_hash(self) -> str:
        return canonical_sha256(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Event":
        return cls(**dict(data))

    @classmethod
    def from_json(cls, value: str) -> "Event":
        decoded = json.loads(value)
        if not isinstance(decoded, dict):
            raise ValueError("event JSON must contain an object")
        return cls.from_dict(decoded)


CanonicalEvent = Event
