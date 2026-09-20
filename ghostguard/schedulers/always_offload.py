"""
Always-Offload Scheduler (Baseline E).
Blindly offloads any offloadable task to the first reachable neighbor without
evaluating deadline feasibility, predicted risk, or fallback safety.
"""

from typing import List
from ghostguard.simulator.device import DeviceNode
from ghostguard.simulator.tasks import TaskInstance
from ghostguard.simulator.events import EventType
from ghostguard.schedulers.base import BaseScheduler


class AlwaysOffloadScheduler(BaseScheduler):
    def __init__(self):
        super().__init__(name="Always-Offload")

    def schedule_device(self, dev: DeviceNode, current_time_ms: float):
        if not dev.ready_queue or not self.simulator:
            return

        # Attempt to offload any offloadable tasks to any reachable neighbor
        offload_candidates = [t for t in dev.ready_queue if t.is_offloadable]
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

                # Schedule arrival event at target
                self.simulator.events.push(
                    timestamp_ms=current_time_ms + comm_delay,
                    event_type=EventType.OFFLOAD_ARRIVE,
                    device_id=target.device_id,
                    task=task,
                    payload={"target_id": target.device_id, "comm_delay_ms": comm_delay}
                )
                # Schedule return event
                return_timestamp = current_time_ms + comm_delay + task.nominal_wcet_ms + comm_delay
                self.simulator.events.push(
                    timestamp_ms=return_timestamp,
                    event_type=EventType.OFFLOAD_RETURN,
                    device_id=dev.device_id,
                    task=task,
                    payload={"success": target.reliability_score > 0.4}
                )

        super().schedule_device(dev, current_time_ms)

    def order_ready_queue(self, dev: DeviceNode, current_time_ms: float) -> List[TaskInstance]:
        return sorted(dev.ready_queue, key=lambda t: (t.deadline_ms, -t.priority))
