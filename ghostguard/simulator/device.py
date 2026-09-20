"""
Compute Node (Device) representation for autonomous edge agents.
Maintains local queues, neighbor knowledge, resource states, and telemetry.
"""

from typing import Dict, List, Optional, Any
from ghostguard.config import HardwareProfile
from ghostguard.simulator.resources import ResourceManager
from ghostguard.simulator.tasks import TaskInstance, TaskState


class NeighborRecord:
    """Historical reliability and link status for a neighbor device."""
    def __init__(self, device_id: str, distance_m: float = 15.0, initial_reliability: float = 0.95):
        self.device_id = device_id
        self.distance_m = distance_m
        self.reliability_score = initial_reliability  # Exponential moving average [0.0, 1.0]
        self.total_offload_attempts = 0
        self.successful_offloads = 0
        self.failed_offloads = 0
        self.is_reachable = True

    def record_outcome(self, success: bool, alpha: float = 0.2):
        self.total_offload_attempts += 1
        if success:
            self.successful_offloads += 1
            self.reliability_score = (1.0 - alpha) * self.reliability_score + alpha * 1.0
        else:
            self.failed_offloads += 1
            self.reliability_score = (1.0 - alpha) * self.reliability_score + alpha * 0.0


class DeviceNode:
    """A simulated autonomous robot/drone compute node."""

    def __init__(
        self,
        device_id: str,
        hardware: HardwareProfile,
        position: tuple = (0.0, 0.0),
        role: Optional[str] = None
    ):
        self.device_id = device_id
        self.hardware = hardware
        self.position = position
        self.role = role or device_id
        self.resources = ResourceManager(hardware)

        # Queues and Task State
        self.ready_queue: List[TaskInstance] = []
        self.running_tasks: List[TaskInstance] = []
        self.offloaded_tasks: Dict[str, Dict[str, Any]] = {}   # Tasks offloaded by this device
        self.remotely_hosted_tasks: List[TaskInstance] = []    # Tasks hosted for other devices
        self.completed_tasks: List[TaskInstance] = []
        self.deadline_missed_tasks: List[TaskInstance] = []

        # Neighbors
        self.neighbors: Dict[str, NeighborRecord] = {}

        # Schedulability and Safety counters
        self.total_interventions: int = 0
        self.total_fallbacks: int = 0
        self.total_offloads: int = 0

    def add_neighbor(self, neighbor_id: str, distance_m: float = 15.0, reliability: float = 0.95):
        self.neighbors[neighbor_id] = NeighborRecord(neighbor_id, distance_m, reliability)

    def admit_task(self, task: TaskInstance):
        task.state = TaskState.READY
        self.ready_queue.append(task)

    def start_running(self, task: TaskInstance, current_time_ms: float):
        if task in self.ready_queue:
            self.ready_queue.remove(task)
        task.state = TaskState.RUNNING
        if task.start_time_ms is None:
            task.start_time_ms = current_time_ms
        task.last_exec_timestamp_ms = current_time_ms
        self.running_tasks.append(task)

        # Apply load
        self.resources.active_cpu_load += task.cpu_util_fraction
        self.resources.active_gpu_load += task.gpu_util_fraction
        self.resources.active_memory_mb += task.memory_mb

    def preempt_task(self, task: TaskInstance, current_time_ms: float):
        if task in self.running_tasks:
            self.running_tasks.remove(task)
            self.resources.active_cpu_load = max(0.0, self.resources.active_cpu_load - task.cpu_util_fraction)
            self.resources.active_gpu_load = max(0.0, self.resources.active_gpu_load - task.gpu_util_fraction)
            self.resources.active_memory_mb = max(0.0, self.resources.active_memory_mb - task.memory_mb)
            task.state = TaskState.READY
            self.ready_queue.append(task)

    def finish_task(self, task: TaskInstance, current_time_ms: float) -> bool:
        if task in self.running_tasks:
            self.running_tasks.remove(task)
            self.resources.active_cpu_load = max(0.0, self.resources.active_cpu_load - task.cpu_util_fraction)
            self.resources.active_gpu_load = max(0.0, self.resources.active_gpu_load - task.gpu_util_fraction)
            self.resources.active_memory_mb = max(0.0, self.resources.active_memory_mb - task.memory_mb)

        task.finish_time_ms = current_time_ms
        task.remaining_work_ms = 0.0

        is_met = current_time_ms <= task.deadline_ms
        if is_met:
            task.state = TaskState.COMPLETED
            self.completed_tasks.append(task)
        else:
            task.state = TaskState.DEADLINE_MISSED
            self.deadline_missed_tasks.append(task)

        return is_met

    def mark_missed(self, task: TaskInstance, current_time_ms: float):
        if task in self.ready_queue:
            self.ready_queue.remove(task)
        if task in self.running_tasks:
            self.running_tasks.remove(task)
            self.resources.active_cpu_load = max(0.0, self.resources.active_cpu_load - task.cpu_util_fraction)
            self.resources.active_gpu_load = max(0.0, self.resources.active_gpu_load - task.gpu_util_fraction)
            self.resources.active_memory_mb = max(0.0, self.resources.active_memory_mb - task.memory_mb)

        task.finish_time_ms = current_time_ms
        task.state = TaskState.DEADLINE_MISSED
        if task not in self.deadline_missed_tasks:
            self.deadline_missed_tasks.append(task)

    def record_offload_dispatch(
        self,
        task: TaskInstance,
        target_id: str,
        dispatch_time_ms: float,
        expected_completion_ms: float
    ):
        if task in self.ready_queue:
            self.ready_queue.remove(task)
        task.state = TaskState.OFFLOADED
        task.offload_target_id = target_id
        task.offload_start_ms = dispatch_time_ms

        self.offloaded_tasks[task.instance_id] = {
            "task": task,
            "target_id": target_id,
            "dispatch_time_ms": dispatch_time_ms,
            "expected_completion_ms": expected_completion_ms,
            "status": "IN_FLIGHT"
        }
        self.total_offloads += 1

    def handle_offload_completion(self, task_id: str, current_time_ms: float, success: bool):
        if task_id in self.offloaded_tasks:
            info = self.offloaded_tasks[task_id]
            if info.get("status") == "ABORTED":
                return  # Ignored: task was safely aborted and handled locally via verified fallback

            task: TaskInstance = info["task"]
            target_id = info["target_id"]

            if target_id in self.neighbors:
                self.neighbors[target_id].record_outcome(success)

            info["status"] = "COMPLETED" if success else "FAILED"
            task.finish_time_ms = current_time_ms
            task.remaining_work_ms = 0.0

            if success and current_time_ms <= task.deadline_ms:
                task.state = TaskState.COMPLETED
                self.completed_tasks.append(task)
            else:
                task.state = TaskState.DEADLINE_MISSED
                self.deadline_missed_tasks.append(task)

    def execute_progress(self, delta_time_ms: float) -> List[TaskInstance]:
        """
        Advances execution on active running tasks based on current effective processing speed.
        Returns list of tasks that have finished their remaining execution work.
        """
        finished: List[TaskInstance] = []
        if not self.running_tasks:
            return finished

        # Share capacity if multiple tasks running
        gpu_speed = self.resources.calculate_effective_speed(requires_gpu=True)
        cpu_speed = self.resources.calculate_effective_speed(requires_gpu=False)

        for task in list(self.running_tasks):
            speed = gpu_speed if task.requires_gpu else cpu_speed
            effective_work_done = delta_time_ms * speed
            task.remaining_work_ms -= effective_work_done
            if task.remaining_work_ms <= 0.001:
                task.remaining_work_ms = 0.0
                finished.append(task)

        return finished

    def get_snapshot(self) -> Dict[str, Any]:
        res = self.resources.snapshot()
        return {
            "device_id": self.device_id,
            "hardware_name": self.hardware.name,
            "ready_queue_len": len(self.ready_queue),
            "running_count": len(self.running_tasks),
            "offloaded_count": len(self.offloaded_tasks),
            "completed_count": len(self.completed_tasks),
            "missed_count": len(self.deadline_missed_tasks),
            "cpu_util": res.cpu_utilization,
            "gpu_util": res.gpu_utilization,
            "memory_mb": res.memory_used_mb,
            "thermal_factor": res.thermal_throttling_factor,
            "temperature_c": res.temperature_celsius,
            "total_offloads": self.total_offloads,
            "total_fallbacks": self.total_fallbacks,
        }
