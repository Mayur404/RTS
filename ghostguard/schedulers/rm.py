"""
Rate Monotonic (RM) Scheduler (Baseline C).
Classic fixed-priority static real-time scheduling algorithm.
Orders ready queue by task period (shorter period = higher priority).
"""

from typing import List
from ghostguard.simulator.device import DeviceNode
from ghostguard.simulator.tasks import TaskInstance
from ghostguard.schedulers.base import BaseScheduler


class RMScheduler(BaseScheduler):
    def __init__(self):
        super().__init__(name="RM-Local")

    def order_ready_queue(self, dev: DeviceNode, current_time_ms: float) -> List[TaskInstance]:
        # Shorter period = higher priority (Rate Monotonic)
        return sorted(dev.ready_queue, key=lambda t: (t.period_ms, -t.priority, t.release_time_ms))
