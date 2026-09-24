"""
Earliest Deadline First (EDF) Scheduler (Baseline B).
Optimal uniprocessor dynamic priority algorithm.
Orders ready queue by absolute deadline (earliest first).
"""

from typing import List
from rts_predictive.simulator.device import DeviceNode
from rts_predictive.simulator.tasks import TaskInstance
from rts_predictive.schedulers.base import BaseScheduler


class EDFScheduler(BaseScheduler):
    def __init__(self):
        super().__init__(name="EDF-Local")

    def order_ready_queue(self, dev: DeviceNode, current_time_ms: float) -> List[TaskInstance]:
        # Sort by earliest absolute deadline, break ties with priority
        return sorted(dev.ready_queue, key=lambda t: (t.deadline_ms, -t.priority))
