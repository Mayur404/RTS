"""
Discrete-Event Simulation Events and Priority Queue.
Ensures strictly deterministic execution order using heap-based scheduling
and tie-breaking counters.
"""

import heapq
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from ghostguard.simulator.tasks import TaskInstance


class EventType(Enum):
    TASK_RELEASE = "TASK_RELEASE"
    TASK_START = "TASK_START"
    TASK_COMPLETE = "TASK_COMPLETE"
    DEADLINE_EXPIRED = "DEADLINE_EXPIRED"
    CONTENTION_START = "CONTENTION_START"
    CONTENTION_END = "CONTENTION_END"
    OFFLOAD_DISPATCH = "OFFLOAD_DISPATCH"
    OFFLOAD_ARRIVE = "OFFLOAD_ARRIVE"
    OFFLOAD_REMOTE_COMPLETE = "OFFLOAD_REMOTE_COMPLETE"
    OFFLOAD_RETURN = "OFFLOAD_RETURN"
    OFFLOAD_PROGRESS_CHECK = "OFFLOAD_PROGRESS_CHECK"
    FALLBACK_TRIGGER = "FALLBACK_TRIGGER"
    NEIGHBOR_DEGRADE = "NEIGHBOR_DEGRADE"
    MONITORING_TICK = "MONITORING_TICK"


@dataclass(order=True)
class SimulationEvent:
    """A discrete simulation event scheduled at timestamp_ms."""
    timestamp_ms: float
    sequence_id: int
    event_type: EventType = field(compare=False)
    device_id: str = field(compare=False)
    task: Optional[TaskInstance] = field(default=None, compare=False)
    payload: Dict[str, Any] = field(default_factory=dict, compare=False)


class EventQueue:
    """Deterministic, seed-safe Priority Queue for Simulation Events."""

    def __init__(self):
        self._heap: List[SimulationEvent] = []
        self._counter: int = 0

    def push(
        self,
        timestamp_ms: float,
        event_type: EventType,
        device_id: str,
        task: Optional[TaskInstance] = None,
        payload: Optional[Dict[str, Any]] = None
    ) -> SimulationEvent:
        self._counter += 1
        event = SimulationEvent(
            timestamp_ms=round(timestamp_ms, 5),
            sequence_id=self._counter,
            event_type=event_type,
            device_id=device_id,
            task=task,
            payload=payload or {}
        )
        heapq.heappush(self._heap, event)
        return event

    def pop(self) -> Optional[SimulationEvent]:
        if not self._heap:
            return None
        return heapq.heappop(self._heap)

    def peek(self) -> Optional[SimulationEvent]:
        if not self._heap:
            return None
        return self._heap[0]

    def is_empty(self) -> bool:
        return len(self._heap) == 0

    def __len__(self) -> int:
        return len(self._heap)

    def clear(self):
        self._heap.clear()
        self._counter = 0
