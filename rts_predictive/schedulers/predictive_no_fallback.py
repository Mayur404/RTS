"""
Predictive Offload without Fallback Scheduler (Baseline F).
Uses predictive risk to trigger offload, but does NOT monitor in-flight tasks
and provides no verified fallback if the neighbor fails or slows down.
"""

from typing import List, Optional
from rts_predictive.simulator.device import DeviceNode
from rts_predictive.simulator.tasks import TaskInstance
from rts_predictive.simulator.events import EventType
from rts_predictive.schedulers.base import BaseScheduler


class PredictiveNoFallbackScheduler(BaseScheduler):
    def __init__(self, risk_threshold: float = 0.60):
        super().__init__(name="Predictive-NoFallback")
        self.risk_threshold = risk_threshold

    def _compute_heuristic_risk(self, task: TaskInstance, dev: DeviceNode, current_time_ms: float) -> float:
        """Estimates impending deadline violation risk based on queue state and slack."""
        slack = task.slack_ms(current_time_ms)
        cpu_u = dev.resources.get_effective_cpu_utilization()
        gpu_u = dev.resources.get_effective_gpu_utilization()
        load_factor = (gpu_u if task.requires_gpu else cpu_u)

        if slack <= 0.0:
            return 1.0
        elif slack < 4.0 or load_factor > 0.85:
            return 0.85
        elif slack < 8.0 or load_factor > 0.70:
            return 0.65
        return 0.20

    def schedule_device(self, dev: DeviceNode, current_time_ms: float):
        if not dev.ready_queue or not self.simulator:
            return

        for task in list(dev.ready_queue):
            if not task.is_offloadable or task.origin_device_id != dev.device_id:
                continue

            risk = self._compute_heuristic_risk(task, dev, current_time_ms)
            if risk >= self.risk_threshold:
                # Find available neighbor with lowest load
                candidates = [
                    (nid, n) for nid, n in dev.neighbors.items()
                    if n.is_reachable and self.simulator.devices.get(nid)
                ]
                if candidates:
                    # Pick best neighbor by reported reliability
                    best_nid, best_n = max(candidates, key=lambda pair: pair[1].reliability_score)
                    target_dev = self.simulator.devices[best_nid]

                    comm_delay = dev.resources.estimate_network_delay_ms(
                        task.payload_kb, target_dev.hardware
                    )
                    est_remote_exec = task.nominal_wcet_ms / max(0.2, target_dev.resources.calculate_effective_speed(task.requires_gpu))
                    est_completion = current_time_ms + comm_delay + est_remote_exec + comm_delay

                    # Offload even if close to deadline (no fallback mechanism available)
                    dev.record_offload_dispatch(task, best_nid, current_time_ms, est_completion)

                    self.simulator.log_event("OFFLOAD_DISPATCHED", dev.device_id, {
                        "task_id": task.instance_id, "target_id": best_nid
                    })
                    self.simulator.schedule_offload_request(task, best_nid)
                    break

        super().schedule_device(dev, current_time_ms)

    def order_ready_queue(self, dev: DeviceNode, current_time_ms: float) -> List[TaskInstance]:
        return sorted(dev.ready_queue, key=lambda t: (t.deadline_ms, -t.priority))
