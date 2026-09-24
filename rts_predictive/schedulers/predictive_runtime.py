"""
PredictiveRuntime Three-Way Predictive Arbitration Scheduler.
Arbitrates between Local Execution, Cooperative Offloading, and Verified Fallback.
Actively monitors in-flight offloaded tasks to trigger fallback upon remote degradation.
"""

from typing import List, Optional, Dict, Any, Tuple
import time
from rts_predictive.simulator.device import DeviceNode
from rts_predictive.simulator.tasks import TaskInstance, TaskState
from rts_predictive.simulator.events import EventType, SimulationEvent
from rts_predictive.schedulers.base import BaseScheduler


class PredictiveRuntimeScheduler(BaseScheduler):
    """
    PredictiveRuntime Real-Time Systems Runtime Protection Engine.
    Implements 3-Way Arbitration: Local vs Offload vs Verified Fallback.
    """

    def __init__(
        self,
        risk_threshold: float = 0.60,
        reliability_threshold: float = 0.70,
        safety_margin_ms: float = 3.0,
        gnn_predictor: Optional[Any] = None,
        federated_model: Optional[Any] = None,
        enable_gnn: bool = False,
        enable_federated: bool = False,
        enable_offload: bool = True,
        enable_watchdog: bool = True,
        enable_fallback: bool = True,
        enable_reliability_filter: bool = True,
    ):
        super().__init__(name="PredictiveRuntime")
        self.risk_threshold = risk_threshold
        self.reliability_threshold = reliability_threshold if enable_reliability_filter else 0.0
        self.safety_margin_ms = safety_margin_ms

        self.enable_gnn = enable_gnn or (gnn_predictor is not None)
        self.enable_federated = enable_federated or (federated_model is not None)
        self.enable_offload = enable_offload
        self.enable_watchdog = enable_watchdog
        self.enable_fallback = enable_fallback
        self.enable_reliability_filter = enable_reliability_filter

        # Wire GNN Predictor
        if self.enable_gnn:
            if gnn_predictor is not None:
                self.gnn_predictor = gnn_predictor
            else:
                try:
                    from rts_predictive.gnn.model import load_pretrained_gnn
                    self.gnn_predictor = load_pretrained_gnn()
                except Exception:
                    self.gnn_predictor = None
            self.predictor_type = "gnn" if self.gnn_predictor is not None else "heuristic"
            if self.gnn_predictor is not None and hasattr(self.gnn_predictor, "decision_threshold"):
                self.risk_threshold = float(self.gnn_predictor.decision_threshold)
        else:
            self.gnn_predictor = None
            self.predictor_type = "heuristic"

        # Wire Federated Model
        if self.enable_federated:
            if federated_model is not None:
                self.federated_model = federated_model
            else:
                try:
                    from rts_predictive.federated.model import load_federated_model
                    self.federated_model = load_federated_model()
                except Exception:
                    self.federated_model = None
            self.estimator_type = "federated" if self.federated_model is not None else "static_spec"
        else:
            self.federated_model = None
            self.estimator_type = "static_spec"

        # Tracking telemetry
        self.active_in_flight_monitors: Dict[str, Dict[str, Any]] = {}
        self.aborted_offloads_recovered_by_fallback: int = 0
        self.offload_dispatches: int = 0
        self.fallbacks_invoked: int = 0
        self.gnn_inferences_count: int = 0
        self.heuristic_predictions_count: int = 0
        self.last_inference_latency_us: int = 0
        self.inference_latencies_us: List[int] = []
        self.candidate_evaluations: Dict[str, List[Dict[str, Any]]] = {}

    def _emit_decision(
        self,
        task: TaskInstance,
        dev: DeviceNode,
        risk: float,
        cause: str,
        action: str,
        target_id: Optional[str] = None,
    ) -> None:
        if self.simulator:
            self.simulator.log_event("RUNTIME_DECISION", dev.device_id, {
                "task_id": task.instance_id,
                "risk": risk,
                "cause": cause,
                "action": action,
                "target_id": target_id,
                "candidate_evaluations": self.candidate_evaluations.get(task.instance_id, []),
                "prediction_source": self.predictor_type,
                "inference_us": self.last_inference_latency_us,
                "evidence": "PREDICTED",
            })

    def _activate_fallback(
        self,
        task: TaskInstance,
        dev: DeviceNode,
        current_time_ms: float,
        reason: str,
    ) -> bool:
        rate = dev.resources.calculate_effective_speed(task.requires_gpu)
        higher_priority_work = sum(
            other.remaining_work_ms
            for other in list(dev.running_tasks) + list(dev.ready_queue)
            if other is not task
            and other.requires_gpu == task.requires_gpu
            and (other.priority > task.priority or other.deadline_ms < task.deadline_ms)
        )
        interference_ms = higher_priority_work / max(rate, 1e-9)
        return task.apply_degradation(
            current_time_ms,
            reason=reason,
            execution_rate=rate,
            interference_bound_ms=interference_ms,
        )

    def _record_prediction(
        self,
        task: TaskInstance,
        dev: DeviceNode,
        risk: float,
        ttv_seconds: float,
        cause: str,
        source: str,
        started_ns: int,
    ) -> None:
        latency_us = max(1, (time.perf_counter_ns() - started_ns) // 1000)
        self.last_inference_latency_us = latency_us
        self.inference_latencies_us.append(latency_us)
        if self.simulator:
            self.simulator.log_event("PREDICTION", dev.device_id, {
                "task_id": task.instance_id,
                "source": source,
                "miss_probability": risk,
                "ttv_ms": ttv_seconds * 1000.0,
                "dominant_cause": cause,
                "runtime_observed_inference_us": latency_us,
                "calibrated": bool(
                    source == "gnn" and getattr(self.gnn_predictor, "calibrated", False)
                ),
                "evidence": "PREDICTED",
            })

    def inference_latency_summary(self) -> Dict[str, Optional[float]]:
        if not self.inference_latencies_us:
            return {"count": 0, "p50_us": None, "p95_us": None, "max_us": None}
        ordered = sorted(self.inference_latencies_us)
        percentile = lambda q: ordered[min(len(ordered) - 1, int(q * (len(ordered) - 1)))]
        return {
            "count": len(ordered),
            "p50_us": percentile(0.50),
            "p95_us": percentile(0.95),
            "max_us": ordered[-1],
        }


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
        started_ns = time.perf_counter_ns()
        if self.gnn_predictor is not None:
            try:
                risk, ttv, cause = self.gnn_predictor.predict(task, dev, current_time_ms)
                self.gnn_inferences_count += 1
                self._record_prediction(task, dev, risk, ttv, cause, "gnn", started_ns)
                return risk, ttv, cause
            except Exception as e:
                self.last_predictor_exception = str(e)
                if self.simulator:
                    self.simulator.log_event("PREDICTOR_FALLBACK", dev.device_id, {
                        "task_id": task.instance_id,
                        "reason": f"GNN inference exception: {e}"
                    })

        self.heuristic_predictions_count += 1
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

        self._record_prediction(
            task, dev, risk, ttv_sec, dominant_cause, "heuristic", started_ns
        )
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
        if not self.enable_offload:
            return None

        best_candidate: Optional[str] = None
        min_total_time = float("inf")
        best_comm_delay = 0.0
        evaluations: List[Dict[str, Any]] = []

        for nid, neighbor in dev.neighbors.items():
            if not neighbor.is_reachable:
                evaluations.append({"device_id": nid, "accepted": False, "reason": "unreachable"})
                continue

            # Reliability constraint
            if self.enable_reliability_filter and neighbor.reliability_score < self.reliability_threshold:
                evaluations.append({"device_id": nid, "accepted": False, "reason": "reliability_threshold"})
                continue

            target_dev = self.simulator.devices.get(nid) if self.simulator else None
            if not target_dev:
                evaluations.append({"device_id": nid, "accepted": False, "reason": "missing_device"})
                continue

            # Candidate utilization
            target_cpu_u = target_dev.resources.get_effective_cpu_utilization()
            target_gpu_u = target_dev.resources.get_effective_gpu_utilization()
            if (task.requires_gpu and target_gpu_u > 0.80) or target_cpu_u > 0.85:
                evaluations.append({"device_id": nid, "accepted": False, "reason": "resource_saturation"})
                continue

            # Queue length throttling: do not overwhelm candidates that already have loaded queues
            if len(target_dev.ready_queue) >= 2 or len(target_dev.remotely_hosted_tasks) >= 2:
                evaluations.append({"device_id": nid, "accepted": False, "reason": "queue_limit"})
                continue

            # Estimate request and response as separate directed transfers,
            # including the current serialization backlog on each link.
            comm_delay = dev.resources.estimate_network_delay_ms(
                task.payload_kb, target_dev.hardware
            )
            response_kb = getattr(task, "response_payload_kb", task.payload_kb)
            response_delay = target_dev.resources.estimate_network_delay_ms(
                response_kb, dev.hardware
            )
            request_queue = max(0.0,
                self.simulator._link_available_ms.get((dev.device_id, nid), 0.0)
                - current_time_ms)
            # Estimate remote execution time using federated model or speed multiplier
            if self.federated_model:
                estimator = getattr(self.federated_model, "predict_q95_execution_time",
                                    self.federated_model.predict_execution_time)
                est_remote_exec = estimator(task, target_dev)
                if self.enable_reliability_filter and hasattr(self.federated_model, "predict_reliability"):
                    pred_rel = self.federated_model.predict_reliability(task, target_dev)
                    if pred_rel < self.reliability_threshold:
                        evaluations.append({
                            "device_id": nid, "accepted": False,
                            "reason": "predicted_reliability", "predicted_reliability": pred_rel,
                        })
                        continue
            else:
                remote_speed = target_dev.resources.calculate_effective_speed(task.requires_gpu)
                est_remote_exec = task.nominal_wcet_ms / max(0.2, remote_speed)

            # Response Time Analysis: account for candidate's existing queue backlog
            target_queue_work = sum(
                t.remaining_work_ms / max(0.2, target_dev.resources.calculate_effective_speed(t.requires_gpu))
                for t in target_dev.ready_queue
                if (t.is_critical or t.priority >= task.priority)
            )

            remote_finish = (current_time_ms + request_queue + comm_delay
                             + target_queue_work + est_remote_exec)
            response_queue = max(0.0,
                self.simulator._link_available_ms.get((nid, dev.device_id), 0.0)
                - remote_finish)
            est_total = (request_queue + comm_delay + target_queue_work
                         + est_remote_exec + response_queue + response_delay)

            # Predicted candidate feasibility, not an analytical certificate.
            if current_time_ms + est_total + self.safety_margin_ms <= task.deadline_ms:
                evaluations.append({
                    "device_id": nid, "accepted": True,
                    "estimated_total_ms": est_total,
                    "deadline_margin_ms": task.deadline_ms - current_time_ms - est_total,
                })
                if est_total < min_total_time:
                    min_total_time = est_total
                    best_candidate = nid
                    best_comm_delay = comm_delay
            else:
                evaluations.append({
                    "device_id": nid, "accepted": False,
                    "reason": "deadline_infeasible",
                    "estimated_total_ms": est_total,
                })

        self.candidate_evaluations[task.instance_id] = evaluations
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
        if not self.enable_watchdog or not self.enable_fallback:
            return

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
        request_timed_out = (
            not task.is_remote_execution
            and self.simulator.current_time_ms >= offload_info.get("request_arrival_ms", float("inf"))
        )

        # Check projected completion
        remaining_time = task.deadline_ms - self.simulator.current_time_ms

        if (is_target_stressed or is_unreliable or request_timed_out
                or remaining_time <= task.degraded_wcet_ms + 1.0):
            # PredictiveRuntime Safety Intervention: ABANDON REMOTE RELIANCE and activate local fallback
            self.simulator.log_event("OFFLOAD_ABANDONED_LOCAL_RECOVERY", origin_id, {
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
            wasted_remote_service_ms = max(
                0.0,
                task.executed_service_ms - offload_info.get("service_ms_at_dispatch", 0.0),
            )
            offload_info["wasted_remote_service_ms"] = wasted_remote_service_ms
            self.simulator.log_event("REMOTE_WORK_WASTED", origin_id, {
                "task_id": task.instance_id,
                "target_id": target_id,
                "wasted_remote_service_ms": wasted_remote_service_ms,
            })

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

            fallback_applied = self._activate_fallback(
                task,
                origin_dev,
                self.simulator.current_time_ms,
                "PredictiveRuntime Active Monitor Intercept",
            )
            task.state = TaskState.READY
            origin_dev.ready_queue.insert(0, task)  # High priority insertion
            if fallback_applied:
                origin_dev.total_fallbacks += 1
                self.aborted_offloads_recovered_by_fallback += 1
                self.fallbacks_invoked += 1
                self._emit_decision(
                    task, origin_dev, 1.0, "watchdog remote risk",
                    "OFFLOAD_ABORT_EARLY_EXIT", target_id,
                )
            else:
                self.simulator.log_event("EARLY_EXIT_UNAVAILABLE", origin_id, {
                    "task_id": task.instance_id,
                    "reason": "No structurally valid, reachable, deadline-feasible exit point",
                })

            # Re-schedule immediate dispatch
            self.schedule_device(origin_dev, self.simulator.current_time_ms)

    def schedule_device(self, dev: DeviceNode, current_time_ms: float):
        if not dev.ready_queue or not self.simulator:
            return

        is_node_stressed = (
            dev.resources.get_effective_cpu_utilization() > 0.80
            or dev.resources.get_effective_gpu_utilization() > 0.80
            or len(dev.ready_queue) > 3
        )

        for task in list(dev.ready_queue):
            # Only origin device manages PredictiveRuntime arbitration for its tasks
            if task.origin_device_id != dev.device_id:
                continue

            if task.is_degraded:
                continue

            # Mixed-criticality degradation: if node is stressed, degrade non-critical tasks to preserve safety
            if is_node_stressed and not task.is_critical:
                if self._activate_fallback(
                    task, dev, current_time_ms, "Mixed-Criticality Mode Change Under Stress"
                ):
                    dev.total_fallbacks += 1
                    self.fallbacks_invoked += 1
                    self.simulator.log_event("PREDICTIVE_RUNTIME_FALLBACK_ACTIVATED", dev.device_id, {
                        "task_id": task.instance_id,
                        "task_name": task.task_name,
                        "checkpoint_id": task.checkpoint_id,
                        "output_utility": task.output_utility,
                        "reason": "Mixed-criticality mode change under stress",
                    })
                    self._emit_decision(
                        task, dev, 1.0, "mixed-criticality stress", "EARLY_EXIT"
                    )
                continue

            # STEP 1: Evaluate predictive risk
            risk, ttv, cause = self.predict_task_risk(task, dev, current_time_ms)

            if (risk >= self.risk_threshold or is_node_stressed) and task.is_critical:
                dev.total_interventions += 1

                # STEP 2 & 3: Evaluate candidate neighbors
                candidate = None
                if task.is_offloadable:
                    candidate = self.evaluate_offload_candidates(task, dev, current_time_ms)

                if candidate:
                    target_id, comm_delay, est_total = candidate
                    est_completion = current_time_ms + est_total

                    dev.record_offload_dispatch(task, target_id, current_time_ms, est_completion)
                    self.offload_dispatches += 1
                    self._emit_decision(task, dev, risk, cause, "OFFLOAD", target_id)

                    self.simulator.log_event("PREDICTIVE_RUNTIME_OFFLOAD_DISPATCH", dev.device_id, {
                        "task_id": task.instance_id,
                        "task_name": task.task_name,
                        "target_id": target_id,
                        "risk_score": round(risk, 3),
                        "cause": cause,
                        "est_total_ms": round(est_total, 2),
                        "deadline_ms": task.deadline_ms
                    })

                    # Request transmission is serialized on the physical link.
                    # The return is scheduled only after actual remote execution.
                    self.simulator.schedule_offload_request(task, target_id)

                    # Schedule Active Monitoring Check midway before deadline
                    check_time = current_time_ms + comm_delay + (est_total - comm_delay) * 0.5
                    self.simulator.events.push(
                        timestamp_ms=check_time,
                        event_type=EventType.OFFLOAD_PROGRESS_CHECK,
                        device_id=dev.device_id,
                        task=task,
                        payload={"task_id": task.instance_id, "target_id": target_id}
                    )

                    if self.enable_watchdog:
                        timeout_ms = max(
                            current_time_ms,
                            task.deadline_ms - task.degraded_wcet_ms - self.safety_margin_ms,
                        )
                        self.simulator.events.push(
                            timestamp_ms=timeout_ms,
                            event_type=EventType.OFFLOAD_PROGRESS_CHECK,
                            device_id=dev.device_id,
                            task=task,
                            payload={"task_id": task.instance_id, "target_id": target_id},
                        )
                else:
                    if not self.enable_fallback:
                        self._emit_decision(task, dev, risk, cause, "LOCAL_NO_FALLBACK")
                        continue
                    # STEP 5: No safe candidate -> Activate configured local fallback.
                    if self._activate_fallback(
                        task,
                        dev,
                        current_time_ms,
                        f"Predicted {cause} (Risk {round(risk*100)}%)",
                    ):
                        dev.total_fallbacks += 1
                        self.fallbacks_invoked += 1
                        self._emit_decision(task, dev, risk, cause, "EARLY_EXIT")
                        self.simulator.log_event("PREDICTIVE_RUNTIME_FALLBACK_ACTIVATED", dev.device_id, {
                            "task_id": task.instance_id,
                            "task_name": task.task_name,
                            "risk_score": round(risk, 3),
                            "cause": cause,
                            "checkpoint_id": task.checkpoint_id,
                            "new_remaining_wcet_ms": task.degraded_wcet_ms,
                            "output_utility": task.output_utility,
                        })
                    else:
                        self._emit_decision(task, dev, risk, cause, "LOCAL_UNAVOIDABLE")
                        self.simulator.log_event("EARLY_EXIT_UNAVAILABLE", dev.device_id, {
                            "task_id": task.instance_id,
                            "reason": "No structurally valid, reachable, deadline-feasible exit point",
                        })
            else:
                self._emit_decision(task, dev, risk, cause, "LOCAL")

        super().schedule_device(dev, current_time_ms)

    def order_ready_queue(self, dev: DeviceNode, current_time_ms: float) -> List[TaskInstance]:
        # Local critical tasks first, followed by local non-critical, then remotely hosted guest tasks
        return sorted(dev.ready_queue, key=lambda t: (
            t.origin_device_id != dev.device_id,
            not t.is_critical,
            t.deadline_ms,
            -t.priority
        ))
