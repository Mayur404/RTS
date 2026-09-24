"""
Always-Offload Scheduler (Baseline E).
Blindly offloads any offloadable task to the first reachable neighbor without
evaluating deadline feasibility, predicted risk, or fallback safety.
"""

from typing import List
from rts_predictive.simulator.device import DeviceNode
from rts_predictive.simulator.tasks import TaskInstance
from rts_predictive.simulator.events import EventType
from rts_predictive.schedulers.base import BaseScheduler


class AlwaysOffloadScheduler(BaseScheduler):
    def __init__(self):
        super().__init__(name="Always-Offload")

    def schedule_device(self, dev: DeviceNode, current_time_ms: float):
        if not dev.ready_queue or not self.simulator:
            return

        # Attempt to offload any offloadable tasks to any reachable neighbor
        # Only the task's origin may make its offload decision. Without this
        # guard, a remotely arrived task is re-offloaded by its host and can
        # ping-pong through the mesh on later scheduler callbacks.
        offload_candidates = [
            t for t in dev.ready_queue
            if t.is_offloadable and t.origin_device_id == dev.device_id
        ]
        reachable_neighbors = [n for n in dev.neighbors.values() if n.is_reachable]

        if reachable_neighbors and offload_candidates:
            target = reachable_neighbors[0]
            target_dev = self.simulator.devices.get(target.device_id)

            for task in list(offload_candidates):
                comm_delay = dev.resources.estimate_network_delay_ms(
                    task.payload_kb, target_dev.hardware if target_dev else None
                )
                est_completion = current_time_ms + comm_delay + task.nominal_wcet_ms + comm_delay

                dev.record_offload_dispatch(task, target.device_id, current_time_ms, est_completion)

                self.simulator.log_event("OFFLOAD_DISPATCHED", dev.device_id, {
                    "task_id": task.instance_id, "target_id": target.device_id
                })
                self.simulator.schedule_offload_request(task, target.device_id)

        super().schedule_device(dev, current_time_ms)

    def order_ready_queue(self, dev: DeviceNode, current_time_ms: float) -> List[TaskInstance]:
        return sorted(dev.ready_queue, key=lambda t: (t.deadline_ms, -t.priority))
