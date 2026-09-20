"""
Deterministic Discrete-Event Simulation Engine for Real-Time Fleet AI Operations.
Maintains global clock, event queue, multi-device state, and metric logging.
"""

import random
from typing import Dict, List, Optional, Any, Callable, Tuple
from ghostguard.config import GhostGuardConfig, DEFAULT_TASK_PROFILES, HARDWARE_PROFILES, HardwareProfile, NODE_FLEET_DEFINITIONS
from ghostguard.simulator.events import EventQueue, EventType, SimulationEvent
from ghostguard.simulator.tasks import TaskInstance, TaskState
from ghostguard.simulator.device import DeviceNode


class DiscreteEventSimulator:
    """Discrete-Event Simulator coordinating a fleet of autonomous AI edge devices."""

    def __init__(
        self,
        config: Optional[GhostGuardConfig] = None,
        seed: int = 42,
        fleet_size: int = 6,
        custom_devices: Optional[List[DeviceNode]] = None
    ):
        self.config = config or GhostGuardConfig()
        self.seed = seed
        self.fleet_size = fleet_size
        self.rng = random.Random(seed)

        self.current_time_ms: float = 0.0
        self.events = EventQueue()
        self.devices: Dict[str, DeviceNode] = {}
        self.telemetry_log: List[Dict[str, Any]] = []
        self.all_tasks: List[TaskInstance] = []
        self._monitoring_scheduled_until_ms: float = 0.0

        # Active scheduler hook
        self.scheduler: Optional[Any] = None

        if custom_devices:
            for dev in custom_devices:
                self.devices[dev.device_id] = dev
        else:
            self._setup_default_fleet()

    def _setup_default_fleet(self):
        """Initializes a heterogeneous fleet of edge devices with mesh topology."""
        hw_keys = list(HARDWARE_PROFILES.keys())[:4]
        for i in range(self.fleet_size):
            dev_id = f"Device_{i+1}"
            hw_key = hw_keys[i % len(hw_keys)]
            # Spread positions in a 2D mesh grid
            pos_x = (i % 3) * 20.0
            pos_y = (i // 3) * 20.0
            role = NODE_FLEET_DEFINITIONS[i]["role"] if i < len(NODE_FLEET_DEFINITIONS) else f"Auxiliary Edge Worker {i+1}"
            node = DeviceNode(
                device_id=dev_id,
                hardware=HARDWARE_PROFILES[hw_key],
                position=(pos_x, pos_y),
                role=role
            )
            self.devices[dev_id] = node

        # Form mesh connections
        for dev_id, dev in self.devices.items():
            for other_id, other_dev in self.devices.items():
                if dev_id != other_id:
                    dx = dev.position[0] - other_dev.position[0]
                    dy = dev.position[1] - other_dev.position[1]
                    dist = (dx**2 + dy**2)**0.5
                    # Connected if within communication range (<= 35m)
                    if dist <= 35.0:
                        dev.add_neighbor(other_id, distance_m=dist, reliability=0.96)

    def attach_scheduler(self, scheduler: Any):
        """Attaches a scheduling policy (e.g. EDF, GhostGuard) to the simulator."""
        self.scheduler = scheduler
        if hasattr(scheduler, "set_simulator"):
            scheduler.set_simulator(self)

    def schedule_periodic_tasks(self, duration_ms: float):
        """Schedules recurring releases of the AI pipeline tasks across devices."""
        task_id_counter = 0
        for dev_id in self.devices.keys():
            for task_name, profile in DEFAULT_TASK_PROFILES.items():
                curr_t = 0.0
                while curr_t < duration_ms:
                    task_id_counter += 1
                    inst_id = f"{dev_id}_{task_name}_{task_id_counter}"
                    # Small random jitter (0 to 1.5 ms)
                    jitter = self.rng.uniform(0.0, 1.2)
                    task = TaskInstance.from_profile(
                        profile=profile,
                        instance_id=inst_id,
                        device_id=dev_id,
                        release_time_ms=curr_t,
                        jitter_ms=jitter
                    )
                    self.all_tasks.append(task)
                    self.events.push(
                        timestamp_ms=task.release_time_ms,
                        event_type=EventType.TASK_RELEASE,
                        device_id=dev_id,
                        task=task
                    )
                    # Schedule deadline check
                    self.events.push(
                        timestamp_ms=task.deadline_ms,
                        event_type=EventType.DEADLINE_EXPIRED,
                        device_id=dev_id,
                        task=task
                    )
                    curr_t += profile.period_ms

    def schedule_contention_burst(
        self,
        target_device_id: str,
        start_time_ms: float,
        duration_ms: float,
        cpu_load: float = 0.8,
        gpu_load: float = 0.9,
        network_delay_ms: float = 12.0
    ):
        """Injects dynamic resource contention spike on a target node."""
        self.events.push(
            timestamp_ms=start_time_ms,
            event_type=EventType.CONTENTION_START,
            device_id=target_device_id,
            payload={
                "cpu_load": cpu_load,
                "gpu_load": gpu_load,
                "network_delay_ms": network_delay_ms
            }
        )
        self.events.push(
            timestamp_ms=start_time_ms + duration_ms,
            event_type=EventType.CONTENTION_END,
            device_id=target_device_id,
            payload={}
        )

    def log_event(self, event_name: str, device_id: str, details: Dict[str, Any]):
        self.telemetry_log.append({
            "timestamp_ms": round(self.current_time_ms, 3),
            "event": event_name,
            "device_id": device_id,
            **details
        })

    def run(self, duration_ms: Optional[float] = None) -> Dict[str, Any]:
        """Advance monotonically to an absolute simulation horizon.

        Future events remain queued, so repeated calls are equivalent to a single call
        to the final horizon for the same already-scheduled workload.
        """
        max_duration = duration_ms or self.config.simulation_duration_ms
        if max_duration < self.current_time_ms:
            raise ValueError(
                f"Cannot run backwards from {self.current_time_ms} ms to {max_duration} ms"
            )

        # Schedule each monitoring tick at most once across incremental run calls.
        tick_interval_ms = self.config.tick_step_ms
        next_tick = max(
            tick_interval_ms,
            self._monitoring_scheduled_until_ms + tick_interval_ms,
        )
        while next_tick <= max_duration:
            self.events.push(
                timestamp_ms=next_tick,
                event_type=EventType.MONITORING_TICK,
                device_id="GLOBAL",
                payload={}
            )
            self._monitoring_scheduled_until_ms = next_tick
            next_tick += tick_interval_ms

        while not self.events.is_empty():
            next_event = self.events.peek()
            if next_event is None or next_event.timestamp_ms > max_duration:
                break
            event = self.events.pop()
            if event is None:
                break
            if event.timestamp_ms < self.current_time_ms:
                raise RuntimeError(
                    f"Event time moved backwards: {event.timestamp_ms} < {self.current_time_ms}"
                )

            # Advance time and compute work done during delta
            delta_ms = event.timestamp_ms - self.current_time_ms
            if delta_ms > 0.0:
                # Completion timestamps are never recorded before the interval end.
                self.current_time_ms = event.timestamp_ms
                self._advance_progress(delta_ms)
            else:
                self.current_time_ms = event.timestamp_ms

            # Dispatch discrete event
            self._handle_event(event)

            # Invoke scheduler decision hook
            if self.scheduler:
                self.scheduler.on_event(self, event)

        # Final progress check up to max_duration
        if max_duration > self.current_time_ms:
            delta_ms = max_duration - self.current_time_ms
            self.current_time_ms = max_duration
            self._advance_progress(delta_ms)

        return self.compute_metrics()

    def _advance_progress(self, delta_ms: float):
        """Advances thermal states and active work across all nodes."""
        for dev in self.devices.values():
            dev.resources.update_thermal_state(delta_ms)
            finished_tasks = dev.execute_progress(delta_ms)
            for task in finished_tasks:
                if task.state != TaskState.COMPLETED and task.state != TaskState.DEADLINE_MISSED:
                    dev.finish_task(task, self.current_time_ms)
                    self.log_event("TASK_COMPLETED", dev.device_id, {
                        "task_id": task.instance_id,
                        "task_name": task.task_name,
                        "response_time_ms": task.response_time_ms,
                        "deadline_met": task.deadline_met,
                        "is_degraded": task.is_degraded
                    })

    def _handle_event(self, event: SimulationEvent):
        """Processes individual discrete events."""
        dev = self.devices.get(event.device_id)

        if event.event_type == EventType.TASK_RELEASE:
            if dev and event.task:
                dev.admit_task(event.task)
                self.log_event("TASK_RELEASED", dev.device_id, {
                    "task_id": event.task.instance_id,
                    "task_name": event.task.task_name,
                    "deadline_ms": event.task.deadline_ms,
                    "priority": event.task.priority
                })

        elif event.event_type == EventType.DEADLINE_EXPIRED:
            task = event.task
            if task and task.finish_time_ms is None:
                origin_dev = self.devices.get(task.origin_device_id)
                if origin_dev:
                    origin_dev.mark_missed(task, self.current_time_ms)
                self.log_event("DEADLINE_MISSED", task.origin_device_id, {
                    "task_id": task.instance_id,
                    "task_name": task.task_name,
                    "lateness_ms": round(self.current_time_ms - task.deadline_ms, 2)
                })

        elif event.event_type == EventType.CONTENTION_START:
            if dev:
                dev.resources.inject_stress(
                    cpu_load=event.payload.get("cpu_load", 0.8),
                    gpu_load=event.payload.get("gpu_load", 0.9),
                    network_delay_ms=event.payload.get("network_delay_ms", 10.0)
                )
                self.log_event("CONTENTION_STARTED", dev.device_id, event.payload)

        elif event.event_type == EventType.CONTENTION_END:
            if dev:
                dev.resources.clear_stress()
                self.log_event("CONTENTION_ENDED", dev.device_id, {})

        elif event.event_type == EventType.OFFLOAD_ARRIVE:
            # Task arrives at remote device
            target_dev = self.devices.get(event.payload.get("target_id", ""))
            task = event.task
            if target_dev and task:
                task.is_remote_execution = True
                target_dev.admit_task(task)
                target_dev.remotely_hosted_tasks.append(task)
                self.log_event("OFFLOAD_ARRIVED", target_dev.device_id, {
                    "task_id": task.instance_id,
                    "from_device": task.origin_device_id
                })

        elif event.event_type == EventType.OFFLOAD_RETURN:
            # Result arrives back at origin device
            task = event.task
            origin_dev = self.devices.get(event.device_id)
            success = event.payload.get("success", True)
            if origin_dev and task:
                origin_dev.handle_offload_completion(task.instance_id, self.current_time_ms, success)
                self.log_event("OFFLOAD_RETURNED", origin_dev.device_id, {
                    "task_id": task.instance_id,
                    "success": success,
                    "deadline_met": task.deadline_met
                })

        elif event.event_type == EventType.NEIGHBOR_DEGRADE:
            target_id = event.payload.get("target_id")
            if dev and target_id in dev.neighbors:
                dev.neighbors[target_id].record_outcome(False)
                self.log_event("NEIGHBOR_DEGRADED", dev.device_id, {
                    "target_id": target_id,
                    "new_reliability": dev.neighbors[target_id].reliability_score
                })

    def compute_metrics(self) -> Dict[str, Any]:
        """Calculates comprehensive Real-Time Systems metrics."""
        released = [t for t in self.all_tasks if t.release_time_ms <= self.current_time_ms]
        completed = [t for t in released if t.state == TaskState.COMPLETED]
        missed = [
            t for t in released
            if t.state == TaskState.DEADLINE_MISSED
            or (t.finish_time_ms is None and self.current_time_ms >= t.deadline_ms)
        ]
        met = [t for t in completed if t.deadline_met is True]
        eligible = [t for t in released if t in completed or t in missed]
        censored = [t for t in released if t not in eligible]

        response_times = [t.response_time_ms for t in completed if t.response_time_ms is not None]
        lateness_vals = [t.lateness_ms for t in completed if t.lateness_ms is not None]
        critical_misses = [t for t in missed if t.is_critical]

        avg_rt = sum(response_times) / len(response_times) if response_times else 0.0
        wc_rt = max(response_times) if response_times else 0.0
        avg_lateness = sum(lateness_vals) / len(lateness_vals) if lateness_vals else 0.0

        # Jitter calculation (std dev of response times for periodic tasks)
        jitter = 0.0
        if len(response_times) > 1:
            mean = avg_rt
            var = sum((x - mean)**2 for x in response_times) / len(response_times)
            jitter = var**0.5

        total_offloads = sum(dev.total_offloads for dev in self.devices.values())
        total_fallbacks = sum(dev.total_fallbacks for dev in self.devices.values())

        return {
            "total_released_tasks": len(released),
            "eligible_task_count": len(eligible),
            "censored_task_count": len(censored),
            "completed_tasks": len(completed),
            "deadline_met_count": len(met),
            "deadline_missed_count": len(missed),
            "critical_misses": len(critical_misses),
            "deadline_miss_ratio": round(len(missed) / max(1, len(eligible)), 4),
            "avg_response_time_ms": round(avg_rt, 2),
            "worst_case_response_time_ms": round(wc_rt, 2),
            "avg_lateness_ms": round(avg_lateness, 2),
            "jitter_ms": round(jitter, 2),
            "total_offloads": total_offloads,
            "total_fallbacks": total_fallbacks,
        }
