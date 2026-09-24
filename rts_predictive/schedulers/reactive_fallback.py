"""
Reactive Degradation Scheduler (Baseline D).
Runs EDF locally, but only degrades task execution AFTER resource stress or
a deadline miss is already observed.
"""

from typing import List
from rts_predictive.simulator.device import DeviceNode
from rts_predictive.simulator.tasks import TaskInstance
from rts_predictive.schedulers.base import BaseScheduler


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
                    rate = dev.resources.calculate_effective_speed(task.requires_gpu)
                    applied = task.apply_degradation(
                        current_time_ms,
                        reason="Reactive Stress Observed",
                        execution_rate=rate,
                    )
                    if applied:
                        dev.total_fallbacks += 1
                    if applied and self.simulator:
                        self.simulator.log_event("REACTIVE_FALLBACK_ACTIVATED", dev.device_id, {
                            "task_id": task.instance_id,
                            "task_name": task.task_name,
                            "checkpoint_id": task.checkpoint_id,
                            "output_utility": task.output_utility,
                        })
                    if applied:
                        break  # Degrade one task per scheduling pass

        return sorted(dev.ready_queue, key=lambda t: (t.deadline_ms, -t.priority))
