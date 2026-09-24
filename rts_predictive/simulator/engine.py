"""
Deterministic Discrete-Event Simulation Engine for Real-Time Fleet AI Operations.
Maintains global clock, event queue, multi-device state, and metric logging.
"""

import math
from typing import Dict, List, Optional, Any, Callable, Tuple
from rts_predictive.config import PredictiveRuntimeConfig, DEFAULT_TASK_PROFILES, HARDWARE_PROFILES, HardwareProfile, NODE_FLEET_DEFINITIONS
from rts_predictive.simulator.events import EventQueue, EventType, SimulationEvent
from rts_predictive.simulator.tasks import TaskInstance, TaskState
from rts_predictive.simulator.device import DeviceNode
from rts_predictive.simulator.rng import NamedRandomStreams


class DiscreteEventSimulator:
    """Discrete-Event Simulator coordinating a fleet of autonomous AI edge devices."""

    def __init__(
        self,
        config: Optional[PredictiveRuntimeConfig] = None,
        seed: int = 42,
        fleet_size: int = 6,
        custom_devices: Optional[List[DeviceNode]] = None,
        run_id: str = "run-sim",
    ):
        self.config = config or PredictiveRuntimeConfig()
        self.seed = seed
        self.fleet_size = fleet_size
        self.random_streams = NamedRandomStreams(seed)
        # Kept as a narrow compatibility alias. New stochastic mechanisms must
        # request a named stream so adding a draw cannot perturb other domains.
        self.rng = self.random_streams.stream("legacy")
        self.run_id = run_id

        self.current_time_ms: float = 0.0
        self.events = EventQueue()
        self.devices: Dict[str, DeviceNode] = {}
        self.telemetry_log: List[Dict[str, Any]] = []
        self.all_tasks: List[TaskInstance] = []
        self._monitoring_scheduled_until_ms: float = 0.0
        self.pipeline_jobs: Dict[str, Any] = {}
        self.canonical_events: List[Dict[str, Any]] = []
        self._canonical_seq: int = 0
        self._link_available_ms: Dict[Tuple[str, str], float] = {}

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
        """Attaches a scheduling policy (e.g. EDF, PredictiveRuntime) to the simulator."""
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
                    jitter = self.random_streams.stream("release_jitter").uniform(0.0, 1.2)
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

    def emit_canonical_event(
        self,
        event_type: str,
        device_id: Optional[str] = None,
        job_id: Optional[str] = None,
        task_id: Optional[str] = None,
        attempt_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ):
        from rts_predictive.artifacts import EVENT_SCHEMA_VERSION
        from rts_predictive.artifacts.events import EVENT_RESERVED_FIELDS

        payload = {key: value for key, value in (payload or {}).items()
                   if key not in EVENT_RESERVED_FIELDS}
        self._canonical_seq += 1
        record = {
            "schema_version": EVENT_SCHEMA_VERSION,
            "run_id": getattr(self, "run_id", "run-sim"),
            "sequence": self._canonical_seq,
            "timestamp_us": int(round(self.current_time_ms * 1000.0)),
            "event_type": event_type,
            "device_id": device_id,
            "job_id": job_id,
            "task_id": task_id,
            "attempt_id": attempt_id,
            "payload": payload,
        }
        self.canonical_events.append(record)

    def log_event(self, event_name: str, device_id: str, details: Dict[str, Any]):
        self.telemetry_log.append({
            "timestamp_ms": round(self.current_time_ms, 3),
            "event": event_name,
            "device_id": device_id,
            **details
        })
        canonical_map = {
            "TASK_RELEASED": "TASK_READY",
            "TASK_COMPLETED": "TASK_COMMIT",
            "DEADLINE_MISSED": "DEADLINE",
            "CONTENTION_STARTED": "FAULT_START",
            "CONTENTION_ENDED": "FAULT_END",
            "OFFLOAD_ARRIVED": "REMOTE_EXECUTION_START",
            "OFFLOAD_RETURNED": "RESULT_TX_END",
            "LATE_RESULT_DISCARDED": "LATE_RESULT_DISCARDED",
            "PREDICTIVE_RUNTIME_OFFLOAD_DISPATCH": "OFFLOAD_DISPATCH",
            "OFFLOAD_DISPATCHED": "OFFLOAD_DISPATCH",
            "PREDICTIVE_RUNTIME_FALLBACK_ACTIVATED": "FALLBACK_TRIGGER",
            "REACTIVE_FALLBACK_ACTIVATED": "FALLBACK_TRIGGER",
            "OFFLOAD_ABANDONED_LOCAL_RECOVERY": "OFFLOAD_ABORT",
            "EARLY_EXIT_UNAVAILABLE": "EARLY_EXIT_UNAVAILABLE",
            "PREDICTOR_FALLBACK": "PREDICTOR_FALLBACK",
            "PREDICTION": "PREDICTION",
            "RUNTIME_DECISION": "RUNTIME_DECISION",
            "REMOTE_WORK_WASTED": "REMOTE_WORK_WASTED",
            "REQUEST_TX_START": "REQUEST_TX_START",
            "RESULT_TX_START": "RESULT_TX_START",
            "REMOTE_EXECUTION_COMPLETE": "REMOTE_EXECUTION_COMPLETE",
            "REQUEST_PACKET_DROPPED": "PACKET_DROP",
            "RESULT_PACKET_DROPPED": "PACKET_DROP",
        }
        if event_name in canonical_map:
            task_id = details.get("task_id")
            task_record = next(
                (task for task in reversed(self.all_tasks) if task.instance_id == task_id),
                None,
            ) if task_id else None
            self.emit_canonical_event(
                canonical_map[event_name],
                device_id=device_id,
                job_id=(task_record.pipeline_job_id if task_record else details.get("job_id")),
                task_id=task_id,
                attempt_id=(task_record.attempt_id if task_record else details.get("attempt_id")),
                payload=details,
            )

    def schedule_pipeline_job(
        self,
        pipeline_spec: Any,
        release_time_ms: float,
        device_id: str = "Device_1"
    ) -> str:
        """Schedules a DAG pipeline job with causal dependencies and per-stage deadlines."""
        from rts_predictive.domain.lifecycle import PipelineJob as DomainPipelineJob
        if release_time_ms < self.current_time_ms:
            raise ValueError("pipeline release cannot precede current simulation time")
        job_counter = len(self.pipeline_jobs) + 1
        job_id = f"job-{job_counter}"
        release_us = int(round(release_time_ms * 1000.0))
        domain_job = DomainPipelineJob.from_spec(job_id, pipeline_spec, release_us)
        self.pipeline_jobs[job_id] = {
            "domain_job": domain_job,
            "device_id": device_id,
            "tasks": {},
            "spec": pipeline_spec,
            "release_time_ms": release_time_ms,
            "end_to_end_deadline_ms": release_time_ms + (pipeline_spec.end_to_end_deadline_us / 1000.0),
            "completed": False,
        }
        self.events.push(
            timestamp_ms=release_time_ms,
            event_type=EventType.PIPELINE_RELEASE,
            device_id=device_id,
            payload={"job_id": job_id, "pipeline_id": pipeline_spec.pipeline_id},
        )
        # Release source tasks with indegree 0
        for task_id, task_inst in domain_job.tasks.items():
            if not task_inst.predecessor_ids:
                sim_task = TaskInstance.from_task_spec(
                    task_inst.spec,
                    instance_id=task_inst.instance_id,
                    device_id=device_id,
                    release_time_ms=release_time_ms,
                    pipeline_job_id=job_id,
                    predecessor_ids=task_inst.predecessor_ids,
                )
                sim_task.deadline_ms = task_inst.absolute_deadline_us / 1000.0
                sim_task.attempt_id = f"att-{sim_task.instance_id}"
                self.all_tasks.append(sim_task)
                self.pipeline_jobs[job_id]["tasks"][task_id] = sim_task
                self.events.push(
                    timestamp_ms=sim_task.release_time_ms,
                    event_type=EventType.TASK_RELEASE,
                    device_id=device_id,
                    task=sim_task,
                )
                self.events.push(
                    timestamp_ms=sim_task.deadline_ms,
                    event_type=EventType.DEADLINE_EXPIRED,
                    device_id=device_id,
                    task=sim_task,
                )
        return job_id

    def schedule_periodic_pipeline(
        self,
        pipeline_spec: Any,
        duration_ms: float,
        device_id: str = "Device_1"
    ):
        """Schedules recurring DAG pipeline job releases across the simulation duration."""
        period_ms = (pipeline_spec.period_us or 50_000) / 1000.0
        t = 0.0
        while t < duration_ms:
            self.schedule_pipeline_job(pipeline_spec, t, device_id=device_id)
            t += period_ms


    def run(self, duration_ms: Optional[float] = None) -> Dict[str, Any]:
        """Advance monotonically to an absolute simulation horizon.

        Future events remain queued, so repeated calls are equivalent to a single call
        to the final horizon for the same already-scheduled workload.
        """
        max_duration = (self.config.simulation_duration_ms
                        if duration_ms is None else duration_ms)
        max_duration = int(round(max_duration * 1000.0)) / 1000.0
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

        while True:
            next_event = self.events.peek()
            event_ms = (next_event.timestamp_ms if next_event and
                        next_event.timestamp_ms <= max_duration else None)
            completion_ms = self._next_completion_ms()
            boundary = min(
                (time for time in (event_ms, completion_ms, max_duration)
                 if time is not None),
            )
            if boundary < self.current_time_ms:
                raise RuntimeError("simulation time moved backwards")
            if boundary > self.current_time_ms:
                delta_ms = boundary - self.current_time_ms
                self.current_time_ms = boundary
                self._advance_progress(delta_ms)

            if completion_ms is not None and boundary == completion_ms and (
                event_ms is None or completion_ms < event_ms
            ):
                if self.scheduler:
                    self.scheduler.schedule_all_devices(self)
                continue

            if event_ms is not None and boundary == event_ms:
                event = self.events.pop()
                self._handle_event(event)
                if self.scheduler:
                    self.scheduler.on_event(self, event)
                continue
            break

        return self.compute_metrics()

    def _next_completion_ms(self) -> Optional[float]:
        """Find the next actual compute completion on the microsecond grid."""
        earliest = None
        for dev in self.devices.values():
            for task in dev.running_tasks:
                speed = dev.resources.calculate_effective_speed(task.requires_gpu)
                if speed <= 0:
                    continue
                remaining_us = max(1, math.ceil(task.remaining_work_ms * 1000 / speed))
                candidate = (int(round(self.current_time_ms * 1000.0)) + remaining_us) / 1000.0
                earliest = candidate if earliest is None else min(earliest, candidate)
        return earliest

    def schedule_offload_request(self, task: TaskInstance, target_id: str) -> None:
        """Serialize the request packet on the directed origin-to-target link."""
        origin = self.devices[task.origin_device_id]
        target = self.devices[target_id]
        delay = origin.resources.estimate_network_delay_ms(task.payload_kb, target.hardware)
        link = (origin.device_id, target_id)
        start = max(self.current_time_ms, self._link_available_ms.get(link, 0.0))
        self._link_available_ms[link] = start + delay
        origin.offloaded_tasks[task.instance_id]["request_arrival_ms"] = start + delay
        if self.random_streams.stream("network_loss").random() < origin.resources.injected_network_drop_prob:
            self.log_event("REQUEST_PACKET_DROPPED", origin.device_id,
                           {"task_id": task.instance_id, "target_id": target_id})
        else:
            self.events.push(start + delay, EventType.OFFLOAD_ARRIVE, target_id, task,
                             {"target_id": target_id})
        self.log_event("REQUEST_TX_START", origin.device_id,
                       {"task_id": task.instance_id, "target_id": target_id})

    def _schedule_result_return(self, task: TaskInstance, remote_id: str) -> None:
        remote = self.devices[remote_id]
        origin = self.devices[task.origin_device_id]
        # A response is a separate packet; its configured payload is explicit.
        response_kb = getattr(task, "response_payload_kb", task.payload_kb)
        delay = remote.resources.estimate_network_delay_ms(response_kb, origin.hardware)
        link = (remote_id, origin.device_id)
        start = max(self.current_time_ms, self._link_available_ms.get(link, 0.0))
        self._link_available_ms[link] = start + delay
        if self.random_streams.stream("network_loss").random() < remote.resources.injected_network_drop_prob:
            self.log_event("RESULT_PACKET_DROPPED", remote_id,
                           {"task_id": task.instance_id, "origin_id": origin.device_id})
        else:
            self.events.push(start + delay, EventType.OFFLOAD_RETURN, origin.device_id, task,
                             {"success": True, "remote_completed_at_ms": self.current_time_ms})
        self.log_event("RESULT_TX_START", remote_id,
                       {"task_id": task.instance_id, "origin_id": origin.device_id})

    def _advance_progress(self, delta_ms: float):
        """Advances thermal states and active work across all nodes."""
        for dev in self.devices.values():
            dev.resources.update_thermal_state(delta_ms)
            finished_tasks = dev.execute_progress(delta_ms)
            for task in finished_tasks:
                if task.state != TaskState.COMPLETED and task.state != TaskState.DEADLINE_MISSED:
                    if task.is_remote_execution:
                        # Remote computation only produces a packet. The job
                        # commits after the result physically reaches origin.
                        dev.preempt_task(task, self.current_time_ms)
                        if task in dev.ready_queue:
                            dev.ready_queue.remove(task)
                        if task in dev.remotely_hosted_tasks:
                            dev.remotely_hosted_tasks.remove(task)
                        task.state = TaskState.OFFLOADED
                        origin = self.devices[task.origin_device_id]
                        info = origin.offloaded_tasks.get(task.instance_id)
                        if info and info.get("status") == "IN_FLIGHT":
                            self.log_event("REMOTE_EXECUTION_COMPLETE", dev.device_id,
                                           {"task_id": task.instance_id})
                            self._schedule_result_return(task, dev.device_id)
                        continue
                    dev.finish_task(task, self.current_time_ms)
                    self.log_event("TASK_COMPLETED", dev.device_id, {
                        "task_id": task.instance_id,
                        "task_name": task.task_name,
                        "response_time_ms": task.response_time_ms,
                        "deadline_met": task.deadline_met,
                        "is_degraded": task.is_degraded,
                        "output_utility": getattr(task, "output_utility", 1.0),
                    })
                    if task.state == TaskState.COMPLETED:
                        self._commit_pipeline_stage(task, dev.device_id)

    def _commit_pipeline_stage(self, task: TaskInstance, execution_device_id: str) -> None:
        """Commit one successful stage and release successors at the commit time."""
        job_info = self.pipeline_jobs.get(task.pipeline_job_id)
        if job_info is None:
            return
        domain_job = job_info["domain_job"]
        domain_task = domain_job.tasks[task.task_name]
        attempt_id = task.attempt_id or f"att-{task.instance_id}"
        cur_us = int(round(self.current_time_ms * 1000.0))
        if attempt_id not in domain_task.attempts:
            from rts_predictive.domain.lifecycle import AttemptKind
            kind = AttemptKind.REMOTE if task.is_remote_execution else AttemptKind.LOCAL
            domain_task.create_attempt(attempt_id, kind, execution_device_id, cur_us)
            domain_task.dispatch_attempt(attempt_id)
            domain_task.start_attempt(attempt_id, cur_us)
        domain_task.complete_attempt(attempt_id, cur_us)
        newly_ready = domain_job.commit_attempt(task.task_name, attempt_id, cur_us)
        for succ_id in newly_ready:
            successor = domain_job.tasks[succ_id]
            sim_task = TaskInstance.from_task_spec(
                successor.spec,
                instance_id=successor.instance_id,
                device_id=job_info["device_id"],
                release_time_ms=self.current_time_ms,
                pipeline_job_id=task.pipeline_job_id,
                predecessor_ids=successor.predecessor_ids,
            )
            sim_task.deadline_ms = successor.absolute_deadline_us / 1000.0
            sim_task.attempt_id = f"att-{sim_task.instance_id}"
            self.all_tasks.append(sim_task)
            job_info["tasks"][succ_id] = sim_task
            self.events.push(self.current_time_ms, EventType.TASK_RELEASE,
                             job_info["device_id"], sim_task)
            self.events.push(max(self.current_time_ms, sim_task.deadline_ms), EventType.DEADLINE_EXPIRED,
                             job_info["device_id"], sim_task)
        if task.task_name == job_info["spec"].sink_task_id and not job_info["completed"]:
            job_info["completed"] = True
            self.emit_canonical_event(
                "PIPELINE_COMPLETE", device_id=job_info["device_id"],
                job_id=task.pipeline_job_id,
                payload={"latency_ms": round(self.current_time_ms - job_info["release_time_ms"], 2)},
            )

    def _handle_event(self, event: SimulationEvent):
        """Processes individual discrete events."""
        dev = self.devices.get(event.device_id)

        if event.event_type == EventType.PIPELINE_RELEASE:
            self.emit_canonical_event(
                "PIPELINE_RELEASE", device_id=event.device_id,
                job_id=event.payload["job_id"],
                payload={"pipeline_id": event.payload["pipeline_id"]},
            )

        elif event.event_type == EventType.TASK_RELEASE:
            if dev and event.task:
                event.task.sample_execution_work(
                    self.random_streams.stream("execution_time")
                )
                dev.admit_task(event.task)
                self.log_event("TASK_RELEASED", dev.device_id, {
                    "task_id": event.task.instance_id,
                    "task_name": event.task.task_name,
                    "deadline_ms": event.task.deadline_ms,
                    "priority": event.task.priority,
                    "is_critical": event.task.is_critical,
                })

        elif event.event_type == EventType.DEADLINE_EXPIRED:
            task = event.task
            if task and task.finish_time_ms is None:
                origin_dev = self.devices.get(task.origin_device_id)
                if any(
                    queued.event_type == EventType.OFFLOAD_RETURN
                    and queued.task is task
                    and queued.timestamp_ms == self.current_time_ms
                    for queued in self.events._heap
                ):
                    return
                if origin_dev:
                    offload_info = origin_dev.offloaded_tasks.get(task.instance_id)
                    if offload_info and offload_info.get("status") == "IN_FLIGHT":
                        offload_info["status"] = "EXPIRED"
                    # One TaskInstance is shared by origin and remote queues.
                    # Remove every active copy before marking it terminal.
                    for host in self.devices.values():
                        if host is origin_dev:
                            continue
                        if task in host.running_tasks:
                            host.preempt_task(task, self.current_time_ms)
                        if task in host.ready_queue:
                            host.ready_queue.remove(task)
                        if task in host.remotely_hosted_tasks:
                            host.remotely_hosted_tasks.remove(task)
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
            origin = self.devices.get(task.origin_device_id) if task else None
            info = origin.offloaded_tasks.get(task.instance_id) if origin and task else None
            if target_dev and task and info and info.get("status") == "IN_FLIGHT":
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
                offload_info = origin_dev.offloaded_tasks.get(task.instance_id)
                if not offload_info or offload_info.get("status") != "IN_FLIGHT":
                    # Single-commit semantics: offload was aborted, late result is discarded
                    self.log_event("LATE_RESULT_DISCARDED", origin_dev.device_id, {
                        "task_id": task.instance_id,
                        "reason": "Remote attempt is no longer active"
                    })
                    return

                origin_dev.handle_offload_completion(task.instance_id, self.current_time_ms, success)
                self.log_event("OFFLOAD_RETURNED", origin_dev.device_id, {
                    "task_id": task.instance_id,
                    "success": success,
                    "deadline_met": task.deadline_met
                })
                if task.state == TaskState.COMPLETED:
                    self.log_event("TASK_COMPLETED", origin_dev.device_id, {
                        "task_id": task.instance_id,
                        "task_name": task.task_name,
                        "response_time_ms": task.response_time_ms,
                        "deadline_met": task.deadline_met,
                        "is_degraded": task.is_degraded,
                        "output_utility": task.output_utility,
                    })
                    self._commit_pipeline_stage(task, offload_info["target_id"])


        elif event.event_type == EventType.NEIGHBOR_DEGRADE:
            target_id = event.payload.get("target_id")
            if dev and target_id in dev.neighbors:
                dev.neighbors[target_id].record_outcome(False)
                self.log_event("NEIGHBOR_DEGRADED", dev.device_id, {
                    "target_id": target_id,
                    "new_reliability": dev.neighbors[target_id].reliability_score
                })

        elif event.event_type == EventType.MONITORING_TICK:
            for sampled_device in self.devices.values():
                snapshot = sampled_device.resources.snapshot()
                self.emit_canonical_event(
                    "RESOURCE_SAMPLE",
                    device_id=sampled_device.device_id,
                    payload={
                        "cpu_utilization": snapshot.cpu_utilization,
                        "gpu_utilization": snapshot.gpu_utilization,
                        "memory_mb": snapshot.memory_used_mb,
                        "temperature_c": snapshot.temperature_celsius,
                        "thermal_factor": snapshot.thermal_throttling_factor,
                        "ready_queue_len": len(sampled_device.ready_queue),
                        "running_tasks": [
                            task.task_name for task in sampled_device.running_tasks
                        ],
                    },
                )

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
        completed_ids = {t.instance_id for t in completed}
        missed_ids = {t.instance_id for t in missed}
        eligible_ids = completed_ids | missed_ids
        eligible = [t for t in released if t.instance_id in eligible_ids]
        censored = [t for t in released if t.instance_id not in eligible_ids]

        response_times = [t.response_time_ms for t in completed if t.response_time_ms is not None]
        lateness_vals = [t.lateness_ms for t in completed if t.lateness_ms is not None]
        critical_misses = [t for t in missed if t.is_critical]

        avg_rt = sum(response_times) / len(response_times) if response_times else 0.0
        wc_rt = max(response_times) if response_times else 0.0
        avg_lateness = sum(lateness_vals) / len(lateness_vals) if lateness_vals else 0.0

        # Response-time jitter is defined per task, then reported as the
        # largest observed task jitter. Mixing unrelated task types changes
        # the quantity being measured.
        responses_by_task: Dict[str, List[float]] = {}
        for task in completed:
            if task.response_time_ms is not None:
                responses_by_task.setdefault(task.task_name, []).append(task.response_time_ms)
        jitter = max(
            (max(values) - min(values) for values in responses_by_task.values()),
            default=0.0,
        )

        total_offloads = sum(dev.total_offloads for dev in self.devices.values())
        total_fallbacks = sum(dev.total_fallbacks for dev in self.devices.values())
        wasted_remote_service_ms = sum(
            info.get("wasted_remote_service_ms", 0.0)
            for dev in self.devices.values()
            for info in dev.offloaded_tasks.values()
        )

        utilities = [getattr(t, "output_utility", 1.0) for t in completed]
        avg_utility = sum(utilities) / len(utilities) if utilities else 1.0

        return {
            "total_released_tasks": len(released),
            "eligible_task_count": len(eligible),
            "censored_task_count": len(censored),
            "completed_tasks": len(completed),
            "deadline_met_count": len(met),
            "deadline_missed_count": len(missed),
            "critical_misses": len(critical_misses),
            "deadline_miss_ratio": round(len(missed) / len(released), 4) if released else 0.0,
            "critical_deadline_miss_ratio": (
                round(len(critical_misses) / sum(t.is_critical for t in released), 4)
                if any(t.is_critical for t in released) else 0.0
            ),
            "avg_response_time_ms": round(avg_rt, 2),
            "worst_case_response_time_ms": round(wc_rt, 2),
            "avg_lateness_ms": round(avg_lateness, 2),
            "jitter_ms": round(jitter, 2),
            "total_offloads": total_offloads,
            "total_fallbacks": total_fallbacks,
            "wasted_remote_service_ms": round(wasted_remote_service_ms, 3),
            "avg_utility": round(avg_utility, 3),
        }
