"""
Base Scheduler Interface for Discrete-Event Simulation.
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from rts_predictive.simulator.device import DeviceNode
from rts_predictive.simulator.tasks import TaskInstance, TaskState
from rts_predictive.simulator.events import SimulationEvent, EventType


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
        Allows preemption if a higher priority or tighter-deadline task is ready on matching resource.
        """
        if not dev.ready_queue:
            return

        ordered = self.order_ready_queue(dev, current_time_ms)
        dev.ready_queue = ordered

        # Preemption check: Preempt remote guest tasks, non-critical, or lower priority / later deadline tasks on matching resource
        if dev.ready_queue and dev.running_tasks:
            cand = dev.ready_queue[0]
            matching_running = [t for t in dev.running_tasks if t.requires_gpu == cand.requires_gpu]
            if matching_running:
                target_running = min(matching_running, key=lambda t: (t.origin_device_id == dev.device_id, t.is_critical, -t.deadline_ms, t.priority))
                should_preempt = False
                # Local tasks always preempt remotely hosted guest tasks
                if cand.origin_device_id == dev.device_id and target_running.origin_device_id != dev.device_id:
                    should_preempt = True
                elif cand.is_critical and not target_running.is_critical:
                    should_preempt = True
                elif cand.is_critical == target_running.is_critical:
                    if cand.deadline_ms < target_running.deadline_ms - 2.0 or (
                        cand.priority > target_running.priority and cand.deadline_ms <= target_running.deadline_ms
                    ):
                        should_preempt = True
                if should_preempt:
                    dev.preempt_task(target_running, current_time_ms)
                    dev.ready_queue = self.order_ready_queue(dev, current_time_ms)

        # Maximum concurrent tasks per node (default 2: e.g. 1 CPU-bound, 1 GPU-bound)
        max_concurrent = 2

        # Heterogeneous non-blocking dispatch
        for candidate in list(dev.ready_queue):
            if len(dev.running_tasks) >= max_concurrent:
                break
            # Check resource compatibility (1 GPU task max, 1 CPU-only task max)
            if candidate.requires_gpu and any(t.requires_gpu for t in dev.running_tasks):
                continue
            if not candidate.requires_gpu and sum(1 for t in dev.running_tasks if not t.requires_gpu) >= 1:
                continue
            dev.start_running(candidate, current_time_ms)
