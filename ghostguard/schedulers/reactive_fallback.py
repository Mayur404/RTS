"""
Reactive Degradation Scheduler (Baseline D).
Runs EDF locally, but only degrades task execution AFTER resource stress or
a deadline miss is already observed.
"""

from typing import List
from ghostguard.simulator.device import DeviceNode
from ghostguard.simulator.tasks import TaskInstance
from ghostguard.schedulers.base import BaseScheduler


class ReactiveFallbackScheduler(BaseScheduler):
    def __init__(self, stress_threshold: float = 0.85):
        super().__init__(name="Reactive-Degradation")
        self.stress_threshold = stress_threshold

    def order_ready_queue(self, dev: DeviceNode, current_time_ms: float) -> List[TaskInstance]:
        # Check if device is under heavy observed stress
        cpu_u = dev.resources.get_effective_cpu_utilization()
        gpu_u = dev.resources.get_effective_gpu_utilization()
        is_stressed = (cpu_u >= self.stress_threshold) or (gpu_u >= self.stress_threshold) or (len(dev.deadline_missed_tasks) > 0)

        if is_stressed:
            # Reactively degrade non-critical or longest task in ready queue
            for task in dev.ready_queue:
                if not task.is_degraded:
                    task.apply_degradation(current_time_ms, reason="Reactive Stress Observed")
                    dev.total_fallbacks += 1
                    break  # Degrade one task per scheduling pass

        return sorted(dev.ready_queue, key=lambda t: (t.deadline_ms, -t.priority))
