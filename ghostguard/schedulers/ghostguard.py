"""
GhostGuard Three-Way Predictive Arbitration Scheduler.
Arbitrates between Local Execution, Cooperative Offloading, and Verified Fallback.
Actively monitors in-flight offloaded tasks to trigger fallback upon remote degradation.
"""

from typing import List, Optional, Dict, Any, Tuple
from ghostguard.simulator.device import DeviceNode
from ghostguard.simulator.tasks import TaskInstance, TaskState
from ghostguard.simulator.events import EventType, SimulationEvent
from ghostguard.schedulers.base import BaseScheduler


class GhostGuardScheduler(BaseScheduler):
    """
    GhostGuard Real-Time Systems Runtime Protection Engine.
    Implements 3-Way Arbitration: Local vs Offload vs Verified Fallback.
    """

    def __init__(
        self,
        risk_threshold: float = 0.60,
        reliability_threshold: float = 0.70,
        safety_margin_ms: float = 3.0,
        gnn_predictor: Optional[Any] = None,
        federated_model: Optional[Any] = None
    ):
        super().__init__(name="GhostGuard")
        self.risk_threshold = risk_threshold
        self.reliability_threshold = reliability_threshold
        self.safety_margin_ms = safety_margin_ms
        self.gnn_predictor = gnn_predictor
        self.federated_model = federated_model

        # Tracking telemetry
        self.active_in_flight_monitors: Dict[str, Dict[str, Any]] = {}
        self.aborted_offloads_recovered_by_fallback: int = 0
        self.successful_offloads: int = 0
        self.verified_fallbacks_invoked: int = 0

    def predict_task_risk(
        self,
        task: TaskInstance,
        dev: DeviceNode,
        current_time_ms: float
    ) -> Tuple[float, float, str]:
        """
        Predicts:
        1. Deadline-miss risk [0.0 to 1.0]
        2. Predicted time-to-violation (seconds)
        3. Primary resource bottleneck attribution
        """
        if self.gnn_predictor is not None:
            try:
                return self.gnn_predictor.predict(task, dev, current_time_ms)
            except Exception:
                pass

        # High-fidelity analytical surrogate
        slack = task.slack_ms(current_time_ms)
        cpu_u = dev.resources.get_effective_cpu_utilization()
        gpu_u = dev.resources.get_effective_gpu_utilization()
        therm = dev.resources.get_thermal_throttling_factor()

        dominant_cause = "GPU contention" if (task.requires_gpu and gpu_u > 0.8) else \
                         ("CPU contention" if cpu_u > 0.8 else \
                         ("Thermal throttling" if therm < 0.9 else "Queue delay"))

        # Time to violation calculation
        ttv_sec = max(0.001, (task.deadline_ms - current_time_ms) / 1000.0)

        # Risk scoring
        if slack < 1.0:
            risk = 0.95
        elif slack < 5.0 or (task.requires_gpu and gpu_u > 0.85) or cpu_u > 0.90 or therm < 0.8:
            risk = 0.85
        elif slack < 10.0 or (task.requires_gpu and gpu_u > 0.70) or cpu_u > 0.75:
            risk = 0.65
        else:
            risk = 0.20

        return risk, ttv_sec, dominant_cause

    def evaluate_offload_candidates(
        self,
        task: TaskInstance,
        dev: DeviceNode,
        current_time_ms: float
    ) -> Optional[Tuple[str, float, float]]:
        """
        Queries neighboring devices via the federated execution and reliability model.
        Returns: (best_neighbor_id, est_comm_delay, est_total_time) if a safe candidate exists.
        """
        best_candidate: Optional[str] = None
        min_total_time = float("inf")
        best_comm_delay = 0.0

        for nid, neighbor in dev.neighbors.items():
            if not neighbor.is_reachable:
                continue

            # Reliability constraint
            if neighbor.reliability_score < self.reliability_threshold:
                continue

            target_dev = self.simulator.devices.get(nid) if self.simulator else None
            if not target_dev:
                continue

            # Candidate utilization
            target_cpu_u = target_dev.resources.get_effective_cpu_utilization()
            target_gpu_u = target_dev.resources.get_effective_gpu_utilization()
            if (task.requires_gpu and target_gpu_u > 0.80) or target_cpu_u > 0.85:
                continue

            # Estimate communication round-trip delay
            comm_delay = dev.resources.estimate_network_delay_ms(
                task.payload_kb, target_dev.hardware
            )
            # Estimate remote execution time using federated model or speed multiplier
            if self.federated_model:
                est_remote_exec = self.federated_model.predict_execution_time(
                    task, target_dev
                )
            else:
                remote_speed = target_dev.resources.calculate_effective_speed(task.requires_gpu)
                est_remote_exec = task.nominal_wcet_ms / max(0.2, remote_speed)

            # Round trip = send + exec + receive
            est_total = (comm_delay * 2.0) + est_remote_exec

            # Real-Time Safety Check
            if current_time_ms + est_total + self.safety_margin_ms <= task.deadline_ms:
                if est_total < min_total_time:
                    min_total_time = est_total
                    best_candidate = nid
                    best_comm_delay = comm_delay

        if best_candidate:
            return best_candidate, best_comm_delay, min_total_time
        return None

    def on_event(self, simulator: Any, event: SimulationEvent):
        """Monitors in-flight offloaded tasks and intercepts remote degradation."""
        if event.event_type == EventType.OFFLOAD_PROGRESS_CHECK:
            self._handle_progress_check(event)
        super().on_event(simulator, event)

    def _handle_progress_check(self, event: SimulationEvent):
        """Active monitoring callback for in-flight offloaded tasks."""
        task_id = event.payload.get("task_id")
        origin_id = event.device_id
        target_id = event.payload.get("target_id")

        origin_dev = self.simulator.devices.get(origin_id)
        target_dev = self.simulator.devices.get(target_id)
        task: Optional[TaskInstance] = event.task

        if not origin_dev or not task:
            return

        offload_info = origin_dev.offloaded_tasks.get(task.instance_id)
        if not offload_info or offload_info.get("status") != "IN_FLIGHT":
            return

        # Check if target device became degraded or unreliable
        is_target_stressed = False
        if target_dev:
            target_cpu = target_dev.resources.get_effective_cpu_utilization()
            target_gpu = target_dev.resources.get_effective_gpu_utilization()
            is_target_stressed = (task.requires_gpu and target_gpu > 0.90) or target_cpu > 0.95

        neighbor_record = origin_dev.neighbors.get(target_id)
        is_unreliable = neighbor_record and (neighbor_record.reliability_score < 0.60)

        # Check projected completion
        remaining_time = task.deadline_ms - self.simulator.current_time_ms

        if is_target_stressed or is_unreliable or remaining_time <= task.degraded_wcet_ms + 1.0:
            # GhostGuard Safety Intervention: ABANDON REMOTE RELIANCE and activate local fallback
            self.simulator.log_event("OFFLOAD_ABANDONED_SAFE_FALLBACK", origin_id, {
                "task_id": task.instance_id,
                "target_id": target_id,
                "reason": "Remote device degraded or deadline at risk",
                "remaining_time_ms": round(remaining_time, 2),
                "degraded_wcet_ms": task.degraded_wcet_ms
            })

            # Update neighbor reliability record
            if neighbor_record:
                neighbor_record.record_outcome(False)

            offload_info["status"] = "ABORTED"

            # Remove task from target device's queues so target device does not waste resources
            if target_dev:
                if task in target_dev.ready_queue:
                    target_dev.ready_queue.remove(task)
                if task in target_dev.running_tasks:
                    target_dev.preempt_task(task, self.simulator.current_time_ms)
                # preempt_task returns the task to the ready queue; an aborted
                # remote copy must not be dispatched again after local recovery.
                if task in target_dev.ready_queue:
                    target_dev.ready_queue.remove(task)
                if task in target_dev.remotely_hosted_tasks:
                    target_dev.remotely_hosted_tasks.remove(task)

            # Apply verified fallback locally
            task.apply_degradation(self.simulator.current_time_ms, reason="GhostGuard Active Monitor Intercept")
            task.state = TaskState.READY
            origin_dev.ready_queue.insert(0, task)  # High priority insertion
            origin_dev.total_fallbacks += 1
            self.aborted_offloads_recovered_by_fallback += 1
            self.verified_fallbacks_invoked += 1

            # Re-schedule immediate dispatch
            self.schedule_device(origin_dev, self.simulator.current_time_ms)

    def schedule_device(self, dev: DeviceNode, current_time_ms: float):
        if not dev.ready_queue or not self.simulator:
            return

        for task in list(dev.ready_queue):
            # Only origin device manages GhostGuard arbitration for its tasks
            if task.origin_device_id != dev.device_id:
                continue

            if task.is_degraded:
                continue

            # STEP 1: Evaluate predictive risk
            risk, ttv, cause = self.predict_task_risk(task, dev, current_time_ms)

            if risk >= self.risk_threshold and task.is_critical:
                dev.total_interventions += 1

                # STEP 2 & 3: Evaluate candidate neighbors
                candidate = None
                if task.is_offloadable:
                    candidate = self.evaluate_offload_candidates(task, dev, current_time_ms)

                if candidate:
                    target_id, comm_delay, est_total = candidate
                    est_completion = current_time_ms + est_total

                    dev.record_offload_dispatch(task, target_id, current_time_ms, est_completion)
                    self.successful_offloads += 1

                    self.simulator.log_event("GHOSTGUARD_OFFLOAD_DISPATCH", dev.device_id, {
                        "task_id": task.instance_id,
                        "task_name": task.task_name,
                        "target_id": target_id,
                        "risk_score": round(risk, 3),
                        "cause": cause,
                        "est_total_ms": round(est_total, 2),
                        "deadline_ms": task.deadline_ms
                    })

                    # Schedule arrival
                    self.simulator.events.push(
                        timestamp_ms=current_time_ms + comm_delay,
                        event_type=EventType.OFFLOAD_ARRIVE,
                        device_id=target_id,
                        task=task,
                        payload={"target_id": target_id, "comm_delay_ms": comm_delay}
                    )

                    # Schedule Active Monitoring Check midway before deadline
                    check_time = current_time_ms + comm_delay + (est_total - comm_delay) * 0.5
                    self.simulator.events.push(
                        timestamp_ms=check_time,
                        event_type=EventType.OFFLOAD_PROGRESS_CHECK,
                        device_id=dev.device_id,
                        task=task,
                        payload={"task_id": task.instance_id, "target_id": target_id}
                    )

                    # Schedule return event
                    self.simulator.events.push(
                        timestamp_ms=est_completion,
                        event_type=EventType.OFFLOAD_RETURN,
                        device_id=dev.device_id,
                        task=task,
                        payload={"success": True}
                    )
                else:
                    # STEP 5: No safe candidate -> Activate configured local fallback.
                    # A runtime verification certificate is not integrated yet.
                    task.apply_degradation(current_time_ms, reason=f"Predicted {cause} (Risk {round(risk*100)}%)")
                    dev.total_fallbacks += 1
                    self.verified_fallbacks_invoked += 1

                    self.simulator.log_event("GHOSTGUARD_FALLBACK_ACTIVATED", dev.device_id, {
                        "task_id": task.instance_id,
                        "task_name": task.task_name,
                        "risk_score": round(risk, 3),
                        "cause": cause,
                        "new_wcet_ms": task.degraded_wcet_ms,
                        "status": "Fallback configured; runtime certificate integration pending"
                    })

        super().schedule_device(dev, current_time_ms)

    def order_ready_queue(self, dev: DeviceNode, current_time_ms: float) -> List[TaskInstance]:
        # Critical tasks first, then earliest deadline
        return sorted(dev.ready_queue, key=lambda t: (not t.is_critical, t.deadline_ms, -t.priority))
