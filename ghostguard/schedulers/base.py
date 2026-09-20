"""
Base Scheduler Interface for Discrete-Event Simulation.
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from ghostguard.simulator.device import DeviceNode
from ghostguard.simulator.tasks import TaskInstance, TaskState
from ghostguard.simulator.events import SimulationEvent, EventType


class BaseScheduler(ABC):
    """Abstract base class for Real-Time Fleet Schedulers."""

    def __init__(self, name: str):
        self.name = name
        self.simulator: Optional[Any] = None

    def set_simulator(self, simulator: Any):
        self.simulator = simulator

    def on_event(self, simulator: Any, event: SimulationEvent):
        """Called whenever a discrete simulation event occurs."""
        if event.event_type in (
            EventType.TASK_RELEASE,
            EventType.TASK_COMPLETE,
            EventType.MONITORING_TICK,
            EventType.CONTENTION_START,
            EventType.CONTENTION_END,
            EventType.OFFLOAD_ARRIVE,
            EventType.OFFLOAD_RETURN
        ):
            self.schedule_all_devices(simulator)

    def schedule_all_devices(self, simulator: Any):
        """Iterates over all devices in the fleet to update execution assignments."""
        for dev in simulator.devices.values():
            self.schedule_device(dev, simulator.current_time_ms)

    @abstractmethod
    def order_ready_queue(self, dev: DeviceNode, current_time_ms: float) -> List[TaskInstance]:
        """Returns the ready queue sorted according to the scheduling policy."""
        pass

    def schedule_device(self, dev: DeviceNode, current_time_ms: float):
        """
        Dispatches tasks from ready queue to running state.
        Allows preemption if a higher priority critical task is ready.
        """
        if not dev.ready_queue:
            return

        ordered = self.order_ready_queue(dev, current_time_ms)
        dev.ready_queue = ordered

        # Preemption check: Preempt non-critical or lower priority tasks if critical task waiting
        if dev.ready_queue and dev.running_tasks:
            cand = dev.ready_queue[0]
            lowest_running = min(dev.running_tasks, key=lambda t: (t.is_critical, t.priority))
            if (cand.is_critical and not lowest_running.is_critical) or (cand.priority > lowest_running.priority and not lowest_running.is_critical):
                dev.preempt_task(lowest_running, current_time_ms)

        # Maximum concurrent tasks per node (default 2: e.g. 1 CPU-bound, 1 GPU-bound)
        max_concurrent = 2

        while dev.ready_queue and len(dev.running_tasks) < max_concurrent:
            candidate = dev.ready_queue[0]
            # Check resource compatibility
            if candidate.requires_gpu and any(t.requires_gpu for t in dev.running_tasks):
                # GPU is busy, wait unless candidate can preempt running GPU task
                break
            dev.start_running(candidate, current_time_ms)
