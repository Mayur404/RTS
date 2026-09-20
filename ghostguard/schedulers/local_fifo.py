"""
Local FIFO Scheduler (Baseline A).
Strictly local execution ordered by arrival / release timestamp.
"""

from typing import List
from ghostguard.simulator.device import DeviceNode
from ghostguard.simulator.tasks import TaskInstance
from ghostguard.schedulers.base import BaseScheduler


class LocalFIFOScheduler(BaseScheduler):
    def __init__(self):
        super().__init__(name="Local-FIFO")

    def order_ready_queue(self, dev: DeviceNode, current_time_ms: float) -> List[TaskInstance]:
        return sorted(dev.ready_queue, key=lambda t: t.release_time_ms)
