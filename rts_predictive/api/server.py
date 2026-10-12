"""
FastAPI REST API and Web Application Server for PredictiveRuntime.
Implements the Research API v1 specification from Implementation Plan.md Section 14
and provides backwards-compatible legacy endpoints for the web dashboard.
"""

import os
import sys
import uuid
import random
import threading
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.encoders import jsonable_encoder

# Ensure root directory is in sys.path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from rts_predictive.config import PredictiveRuntimeConfig, DEFAULT_TASK_PROFILES, HARDWARE_PROFILES, NODE_FLEET_DEFINITIONS
from rts_predictive.simulator.device import DeviceNode
from rts_predictive.dashboard.timeline_tracer import run_traced_simulation, run_dynamic_scenario
from rts_predictive.dashboard.frame_reducer import reduce_events_to_frames
from rts_predictive.dashboard.live_projection import live_statistics, resource_dependency_graph
from rts_predictive.simulator.engine import DiscreteEventSimulator
from rts_predictive.domain.specs import create_autonomous_ai_pipeline_spec
from rts_predictive.schedulers.predictive_runtime import PredictiveRuntimeScheduler
from rts_predictive.schedulers.edf import EDFScheduler
from rts_predictive.schedulers.rm import RMScheduler
from rts_predictive.schedulers.local_fifo import LocalFIFOScheduler
from rts_predictive.schedulers.reactive_fallback import ReactiveFallbackScheduler
from rts_predictive.schedulers.always_offload import AlwaysOffloadScheduler
from rts_predictive.schedulers.predictive_no_fallback import PredictiveNoFallbackScheduler
from rts_predictive.experiments.scenarios import (
    create_nominal_scenario,
    create_bursty_scenario,
    create_thermal_scenario,
    create_unreliable_neighbor_scenario,
)

app = FastAPI(
    title="PredictiveRuntime Real-Time Systems Research API",
    description="Predictive Runtime Protection for Distributed Real-Time AI Systems",
    version="2.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from rts_predictive.api.research import router as research_router
app.include_router(research_router)

@app.get("/health")
@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": "PredictiveRuntime", "version": "2.1.0"}

# In-memory store for runs and deterministic Section 12 cache
_SECTION_12_CACHE: Optional[Dict[str, Any]] = None
_RUNS_STORE: Dict[str, Dict[str, Any]] = {}
_VERIFICATION_STORE: Dict[str, Dict[str, Any]] = {}


def get_cached_section12() -> Dict[str, Any]:
    global _SECTION_12_CACHE
    if _SECTION_12_CACHE is None:
        _SECTION_12_CACHE = run_traced_simulation(duration_ms=100.0, step_ms=1.0)
    return _SECTION_12_CACHE


class SimulationRequest(BaseModel):
    contention: float = 0.90
    fault_time: float = 25.0
    jitter: float = 5.0
    fleet_size: int = 4
    target_node: str = "Node 1"


class RunCreateRequest(BaseModel):
    policy: str = Field(default="rts_predictive", description="Scheduling policy")
    scenario_type: str = Field(default="bursty", description="Scenario family")
    seed: int = Field(default=42, ge=0)
    duration_ms: float = Field(default=100.0, gt=0.0, le=2000.0)
    fleet_size: int = Field(default=4, ge=2, le=8)
    contention: float = Field(default=0.90, ge=0.0, le=1.0)
    fault_time_ms: float = Field(default=25.0, ge=0.0)
    jitter_ms: float = Field(default=5.0, ge=0.0)


class CompareRequest(BaseModel):
    run_ids: Optional[List[str]] = None
    policies: Optional[List[str]] = None
    scenario_type: str = "bursty"
    seed: int = 42
    duration_ms: float = 100.0


class VerificationTaskRequest(BaseModel):
    task_id: str
    period_us: int = Field(gt=0)
    deadline_us: int = Field(gt=0)
    wcet_us: int = Field(ge=0)
    priority: int
    jitter_us: int = Field(default=0, ge=0)
    blocking_us: int = Field(default=0, ge=0)
    overhead_us: int = Field(default=0, ge=0)
    resource_id: str = "cpu0"


class VerificationAnalyzeRequest(BaseModel):
    tasks: List[VerificationTaskRequest]
    scenario_hash: str
    scheduler_config_hash: str
    hardware_profile_hash: str
    resource_partition_id: str
    fallback_mode_id: str
    max_iterations: int = Field(default=1000, ge=1, le=1000)


def _build_scheduler(name: str):
    name_norm = name.lower().replace("-", "_").strip()
    if name_norm in ("rts_predictive", "predictiveruntime", "rts_predictive_gnn"):
        from rts_predictive.gnn.model import load_pretrained_gnn
        try:
            predictor = load_pretrained_gnn()
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return PredictiveRuntimeScheduler(
            gnn_predictor=predictor,
            enable_federated=(name_norm != "rts_predictive_gnn"),
        )
    elif name_norm == "edf":
        return EDFScheduler()
    elif name_norm == "rm":
        return RMScheduler()
    elif name_norm == "local_fifo":
        return LocalFIFOScheduler()
    elif name_norm == "reactive_fallback":
        return ReactiveFallbackScheduler()
    elif name_norm == "always_offload":
        return AlwaysOffloadScheduler()
    elif name_norm == "predictive_no_fallback":
        return PredictiveNoFallbackScheduler()
    else:
        raise HTTPException(status_code=400, detail=f"Unknown policy: {name}")


# -------------------------------------------------------------
# Continuous Live Simulation Manager & Endpoints
# -------------------------------------------------------------
NODE_METADATA = {
    "Device_1": {
        "name": "Node 1: Aerial Drone (Quadcopter)",
        "role": "Autonomous Aerial Perception",
        "node_type": "drone",
        "hardware": "Jetson-Orin-Nano",
        "color": "#3B82F6",
    },
    "Device_2": {
        "name": "Node 2: Edge Server (GPU Rack)",
        "role": "Edge AI GPU Cluster Candidate",
        "node_type": "server",
        "hardware": "Jetson-AGX-Orin",
        "color": "#10B981",
    },
    "Device_3": {
        "name": "Node 3: Ground Rover (UGV)",
        "role": "Mobile Obstacle Tracking Rover",
        "node_type": "rover",
        "hardware": "Raspberry-Pi-5",
        "color": "#8B5CF6",
    },
    "Device_4": {
        "name": "Node 4: Robotic Arm (Manipulator)",
        "role": "Motion Actuation & Feed-Forward",
        "node_type": "arm",
        "hardware": "Jetson-Orin-Nano",
        "color": "#EC4899",
    },
    "Device_5": {
        "name": "Node 5: Auxiliary Drone",
        "role": "Secondary Aerial Scout",
        "node_type": "drone",
        "hardware": "Jetson-Xavier-NX",
        "color": "#F59E0B",
    },
    "Device_6": {
        "name": "Node 6: Coral TPU Node",
        "role": "Quantized Edge TPU Filter",
        "node_type": "chip",
        "hardware": "Coral-Edge-TPU",
        "color": "#06B6D4",
    },
    "Device_7": {
        "name": "Node 7: Ground Station",
        "role": "Central Mesh Coordinator",
        "node_type": "server",
        "hardware": "Ground-Station",
        "color": "#6366F1",
    },
    "Device_8": {
        "name": "Node 8: Field Rover 2",
        "role": "Redundant Telemetry Worker",
        "node_type": "rover",
        "hardware": "Jetson-Nano",
        "color": "#14B8A6",
    },
}

# NODE_FLEET_DEFINITIONS stores diagram coordinates. The live network model
# interprets ten diagram units as one modeled meter; this is a scenario
# assumption, not a measured deployment geometry.
LIVE_METERS_PER_LAYOUT_UNIT = 0.1


class LiveStartRequest(BaseModel):
    fleet_size: int = Field(default=4, ge=2, le=8)
    seed: int = Field(default=42, ge=0)
    horizon_ms: float = Field(default=3000.0, gt=100.0)
    enable_contention: bool = Field(default=True)
    fault_time_ms: float = Field(default=25.0, ge=0.0)
    fault_duration_ms: float = Field(default=180.0, gt=0.0)
    contention_magnitude: float = Field(default=0.90, ge=0.0, le=1.0)
    target_node: str = Field(default="Device_1")
    risk_threshold: float = Field(default=0.60, ge=0.0, le=1.0)
    reliability_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    safety_margin_ms: float = Field(default=3.0, ge=0.0)
    network_delay_ms: float = Field(default=12.0, ge=0.0)
    period_ms: float = Field(default=50.0, ge=10.0, le=500.0)
    deadline_ms: float = Field(default=50.0, ge=10.0, le=500.0)


class LiveStepRequest(BaseModel):
    delta_ms: float = Field(default=10.0, gt=0.0, le=200.0)
    session_id: Optional[str] = None


class LiveFaultRequest(BaseModel):
    session_id: Optional[str] = None
    target_node: str = Field(default="Device_1")
    cpu_load: float = Field(default=0.95, ge=0.0, le=1.0)
    gpu_load: float = Field(default=0.95, ge=0.0, le=1.0)
    duration_ms: float = Field(default=180.0, gt=0.0)
    network_delay_ms: float = Field(default=15.0, ge=0.0)


class LiveSimulationSession:
    """Manages active live continuous simulation state for PredictiveRuntime and Baseline."""

    def __init__(
        self,
        fleet_size: int = 4,
        seed: int = 42,
        horizon_ms: float = 3000.0,
        enable_contention: bool = True,
        fault_time_ms: float = 25.0,
        fault_duration_ms: float = 180.0,
        contention_magnitude: float = 0.90,
        target_node: str = "Device_1",
        risk_threshold: float = 0.60,
        reliability_threshold: float = 0.70,
        safety_margin_ms: float = 3.0,
        network_delay_ms: float = 12.0,
        period_ms: float = 50.0,
        deadline_ms: float = 50.0,
    ):
        self.fleet_size = fleet_size
        self.session_id: Optional[str] = None
        self.lock = threading.RLock()
        self.seed = seed
        self.horizon_ms = horizon_ms
        self.target_node = target_node
        self.current_time_ms = 0.0
        self.step_size_ms = 10.0
        self.retention_window_ms = 5000.0

        config_gg = PredictiveRuntimeConfig(simulation_duration_ms=horizon_ms)
        config_edf = PredictiveRuntimeConfig(simulation_duration_ms=horizon_ms)

        custom_devs_gg = []
        custom_devs_edf = []
        for i in range(fleet_size):
            defn = NODE_FLEET_DEFINITIONS[i] if i < len(NODE_FLEET_DEFINITIONS) else {
                "id": f"Device_{i+1}",
                "role": f"Auxiliary Edge Worker {i+1}",
                "hardware_profile": "Jetson-Orin-Nano",
                "x": (i % 3) * 20.0,
                "y": (i // 3) * 20.0,
            }
            hw_name = defn.get("hardware_profile", "Jetson-Orin-Nano")
            hw = HARDWARE_PROFILES.get(hw_name, HARDWARE_PROFILES["Jetson-Orin-Nano"])
            pos = (
                defn.get("x", (i % 3) * 20.0) * LIVE_METERS_PER_LAYOUT_UNIT,
                defn.get("y", (i // 3) * 20.0) * LIVE_METERS_PER_LAYOUT_UNIT,
            )
            custom_devs_gg.append(DeviceNode(device_id=defn["id"], hardware=hw, position=pos, role=defn["role"]))
            custom_devs_edf.append(DeviceNode(device_id=defn["id"], hardware=hw, position=pos, role=defn["role"]))

        self.sim_gg = DiscreteEventSimulator(config=config_gg, custom_devices=custom_devs_gg, seed=seed, fleet_size=fleet_size)
        self.sim_edf = DiscreteEventSimulator(config=config_edf, custom_devices=custom_devs_edf, seed=seed, fleet_size=fleet_size)

        # Form mesh connections across fleet
        for sim in (self.sim_gg, self.sim_edf):
            for dev_id, dev in sim.devices.items():
                for other_id, other_dev in sim.devices.items():
                    if dev_id != other_id and other_id not in dev.neighbors:
                        dx = dev.position[0] - other_dev.position[0]
                        dy = dev.position[1] - other_dev.position[1]
                        dist = (dx**2 + dy**2)**0.5
                        if dist <= 45.0 or fleet_size <= 4:
                            dev.add_neighbor(other_id, distance_m=dist, reliability=0.96)

        self.pipeline_spec = create_autonomous_ai_pipeline_spec(
            period_us=int(period_ms * 1000),
            end_to_end_deadline_us=int(deadline_ms * 1000),
        )
        for dev_id in self.sim_gg.devices:
            self.sim_gg.schedule_periodic_pipeline(self.pipeline_spec, horizon_ms, device_id=dev_id)
            self.sim_edf.schedule_periodic_pipeline(self.pipeline_spec, horizon_ms, device_id=dev_id)
        period_ms = (self.pipeline_spec.period_us or 50_000) / 1000.0
        self._pipeline_period_ms = period_ms
        self._next_pipeline_release_ms = (
            int((horizon_ms + period_ms - 0.000001) // period_ms) * period_ms
        )

        self.enable_contention = enable_contention
        self.contention_magnitude = contention_magnitude
        self.network_delay_ms = network_delay_ms
        self.fault_duration_ms = fault_duration_ms
        self.rng = random.Random(seed)
        self._next_contention_time_ms = fault_time_ms if enable_contention else 1e9

        if enable_contention:
            self.sim_gg.schedule_contention_burst(
                target_device_id=target_node,
                start_time_ms=fault_time_ms,
                duration_ms=fault_duration_ms,
                cpu_load=contention_magnitude,
                gpu_load=min(1.0, contention_magnitude + 0.05),
                network_delay_ms=network_delay_ms,
            )
            self.sim_edf.schedule_contention_burst(
                target_device_id=target_node,
                start_time_ms=fault_time_ms,
                duration_ms=fault_duration_ms,
                cpu_load=contention_magnitude,
                gpu_load=min(1.0, contention_magnitude + 0.05),
                network_delay_ms=network_delay_ms,
            )
            sec_target = "Device_2" if fleet_size >= 2 else target_node
            self.sim_gg.schedule_contention_burst(
                target_device_id=sec_target,
                start_time_ms=fault_time_ms + 20.0,
                duration_ms=max(100.0, fault_duration_ms - 20.0),
                cpu_load=0.98,
                gpu_load=0.98,
                network_delay_ms=max(network_delay_ms, 15.0),
            )
            self.sim_edf.schedule_contention_burst(
                target_device_id=sec_target,
                start_time_ms=fault_time_ms + 20.0,
                duration_ms=max(100.0, fault_duration_ms - 20.0),
                cpu_load=0.98,
                gpu_load=0.98,
                network_delay_ms=max(network_delay_ms, 15.0),
            )
            self._next_contention_time_ms = fault_time_ms + fault_duration_ms + 120.0
            # Pre-schedule stochastic bursts across the simulation horizon
            self._schedule_stochastic_contention(through_ms=horizon_ms)

        from rts_predictive.gnn.model import load_pretrained_gnn
        from rts_predictive.federated.model import load_federated_model
        self.sched_gg = PredictiveRuntimeScheduler(
            risk_threshold=risk_threshold,
            reliability_threshold=reliability_threshold,
            safety_margin_ms=safety_margin_ms,
            gnn_predictor=load_pretrained_gnn(),
            federated_model=load_federated_model(),
        )
        self.sched_edf = EDFScheduler()

        self.sim_gg.attach_scheduler(self.sched_gg)
        self.sim_edf.attach_scheduler(self.sched_edf)
        # The explicit live setting overrides the bundle's validation default.
        self.sched_gg.risk_threshold = risk_threshold

        self._last_event_idx_gg = 0
        self._last_canonical_sequence = 0

    def _schedule_stochastic_contention(self, through_ms: float) -> None:
        """Schedules realistic stochastic resource contention bursts across fleet nodes."""
        if not self.enable_contention:
            return
        device_ids = list(self.sim_gg.devices.keys())
        while self._next_contention_time_ms < through_ms:
            t_start = self._next_contention_time_ms
            dur = self.rng.uniform(0.7 * self.fault_duration_ms, 1.25 * self.fault_duration_ms)
            cpu = min(0.99, self.rng.uniform(0.78, 0.96))
            gpu = min(1.0, cpu + self.rng.uniform(0.01, 0.05))
            delay = self.rng.uniform(0.8 * self.network_delay_ms, 1.4 * self.network_delay_ms)

            num_devs = 1 if len(device_ids) <= 2 else self.rng.choice([1, 2])
            targets = self.rng.sample(device_ids, k=num_devs)
            for dev_id in targets:
                self.sim_gg.schedule_contention_burst(
                    target_device_id=dev_id,
                    start_time_ms=t_start,
                    duration_ms=dur,
                    cpu_load=cpu,
                    gpu_load=gpu,
                    network_delay_ms=delay,
                )
                self.sim_edf.schedule_contention_burst(
                    target_device_id=dev_id,
                    start_time_ms=t_start,
                    duration_ms=dur,
                    cpu_load=cpu,
                    gpu_load=gpu,
                    network_delay_ms=delay,
                )
            interval = self.rng.uniform(140.0, 320.0)
            self._next_contention_time_ms = t_start + dur + interval

    def step(self, delta_ms: float = 10.0) -> Dict[str, Any]:
        cur_t = max(self.sim_gg.current_time_ms, self.sim_edf.current_time_ms, self.current_time_ms)
        next_t = cur_t + delta_ms
        self._extend_workload(next_t + max(250.0, self.horizon_ms))
        if next_t > self.sim_gg.current_time_ms:
            self.sim_gg.run(duration_ms=next_t)
        if next_t > self.sim_edf.current_time_ms:
            self.sim_edf.run(duration_ms=next_t)
        self.current_time_ms = max(self.sim_gg.current_time_ms, self.sim_edf.current_time_ms)
        snapshot = self.get_snapshot()
        self._prune_history()
        return snapshot

    def _extend_workload(self, through_ms: float) -> None:
        """Release paired future jobs and continuous stochastic bursts as the live clock advances."""
        while self._next_pipeline_release_ms < through_ms:
            for dev_id in self.sim_gg.devices:
                self.sim_gg.schedule_pipeline_job(
                    self.pipeline_spec, self._next_pipeline_release_ms, device_id=dev_id
                )
                self.sim_edf.schedule_pipeline_job(
                    self.pipeline_spec, self._next_pipeline_release_ms, device_id=dev_id
                )
            self._next_pipeline_release_ms += self._pipeline_period_ms
        self._schedule_stochastic_contention(through_ms)

    def _prune_history(self) -> None:
        """Bound live-only memory while retaining active state and recent outcomes."""
        cutoff = self.current_time_ms - self.retention_window_ms
        if cutoff <= 0:
            return
        for sim in (self.sim_gg, self.sim_edf):
            sim.all_tasks[:] = [
                task for task in sim.all_tasks
                if task.finish_time_ms is None or task.finish_time_ms >= cutoff
            ]
            sim.pipeline_jobs = {
                job_id: job for job_id, job in sim.pipeline_jobs.items()
                if job["release_time_ms"] >= cutoff or any(
                    task.state.value in {"RELEASED", "READY", "RUNNING", "OFFLOADED", "FALLBACK_ACTIVE"}
                    for task in job["tasks"].values()
                )
            }
            sim.canonical_events[:] = [
                event for event in sim.canonical_events
                if event["timestamp_us"] >= int(cutoff * 1000)
            ]
            for dev in sim.devices.values():
                dev.completed_tasks[:] = [
                    task for task in dev.completed_tasks
                    if task.finish_time_ms is None or task.finish_time_ms >= cutoff
                ]
                dev.deadline_missed_tasks[:] = [
                    task for task in dev.deadline_missed_tasks
                    if task.finish_time_ms is None or task.finish_time_ms >= cutoff
                ]
                dev.offloaded_tasks = {
                    task_id: info for task_id, info in dev.offloaded_tasks.items()
                    if info.get("status") == "IN_FLIGHT"
                    or info["task"].finish_time_ms is None
                    or info["task"].finish_time_ms >= cutoff
                }
        self.sim_gg.telemetry_log.clear()
        self.sim_edf.telemetry_log.clear()
        # Live latency summaries use bounded host observations; lifetime count
        # remains available separately. Experiment runs preserve all samples.
        self.sched_gg.inference_latencies_us[:] = self.sched_gg.inference_latencies_us[-4096:]
        self._last_event_idx_gg = 0

    def inject_fault(self, target_dev_id: str, cpu: float, gpu: float, duration_ms: float, delay_ms: float):
        self.sim_gg.schedule_contention_burst(
            target_device_id=target_dev_id,
            start_time_ms=self.current_time_ms,
            duration_ms=duration_ms,
            cpu_load=cpu,
            gpu_load=gpu,
            network_delay_ms=delay_ms,
        )
        self.sim_edf.schedule_contention_burst(
            target_device_id=target_dev_id,
            start_time_ms=self.current_time_ms,
            duration_ms=duration_ms,
            cpu_load=cpu,
            gpu_load=gpu,
            network_delay_ms=delay_ms,
        )

    def get_snapshot(self) -> Dict[str, Any]:
        latest_jobs = {}
        released_jobs: Dict[str, list[Dict[str, Any]]] = {}

        def job_view(job_id: str, job: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "job_id": job_id,
                "release_time_ms": job["release_time_ms"],
                "completed": job["completed"],
                "stages": {
                    task.task_id: (
                        {
                            "state": job["tasks"][task.task_id].state.value,
                            "deadline_ms": job["tasks"][task.task_id].deadline_ms,
                            "finish_time_ms": job["tasks"][task.task_id].finish_time_ms,
                            "remaining_work_ms": round(max(
                                0.0, job["tasks"][task.task_id].remaining_work_ms
                            ), 3),
                            "execution_device_id": (
                                job["tasks"][task.task_id].offload_target_id
                                if job["tasks"][task.task_id].is_remote_execution
                                else job["tasks"][task.task_id].device_id
                            ),
                            "is_degraded": job["tasks"][task.task_id].is_degraded,
                        }
                        if task.task_id in job["tasks"] else {"state": "WAITING"}
                    ) for task in self.pipeline_spec.tasks
                },
            }

        for job_id, job in self.sim_gg.pipeline_jobs.items():
            if job["release_time_ms"] > self.current_time_ms:
                continue
            device_id = job["device_id"]
            view = job_view(job_id, job)
            released_jobs.setdefault(device_id, []).append(view)
            previous = latest_jobs.get(device_id)
            if previous is None or job["release_time_ms"] > previous["release_time_ms"]:
                latest_jobs[device_id] = view

        # Follow one active job through its real lifecycle instead of switching
        # the DAG to every newly released, mostly-WAITING job.
        focus_jobs = {}
        for device_id, jobs in released_jobs.items():
            active = [job for job in jobs if not job["completed"] and any(
                stage["state"] in {"RELEASED", "READY", "RUNNING", "OFFLOADED", "FALLBACK_ACTIVE"}
                for stage in job["stages"].values()
            )]
            focus_jobs[device_id] = min(
                active, key=lambda item: item["release_time_ms"]
            ) if active else max(jobs, key=lambda item: item["release_time_ms"])
        nodes = {}
        for dev_id, dev in self.sim_gg.devices.items():
            cpu = round(dev.resources.get_effective_cpu_utilization() * 100.0, 1)
            gpu = round(dev.resources.get_effective_gpu_utilization() * 100.0, 1)
            temp_c = round(dev.resources.temperature_c, 1)
            meta = NODE_METADATA.get(dev_id, {
                "name": f"{dev_id}: Generic Node",
                "role": "Edge Worker",
                "node_type": "rover",
                "hardware": "Generic-ARM",
                "color": "#3B82F6",
            })

            running_names = [t.task_name for t in dev.running_tasks]
            queue_names = [t.task_name for t in dev.ready_queue]
            active_task = running_names[0] if running_names else (queue_names[0] if queue_names else "Idle")

            is_overloaded = (cpu > 80.0 or gpu > 85.0)
            fallback_active = any(t.is_degraded for t in list(dev.running_tasks) + list(dev.ready_queue))

            status_str = "FALLBACK_ACTIVE" if fallback_active else ("OVERLOADED" if is_overloaded else "NOMINAL")

            nodes[dev_id] = {
                "id": dev_id,
                "name": meta["name"],
                "role": meta["role"],
                "node_type": meta["node_type"],
                "hardware": meta["hardware"],
                "color": meta["color"],
                "cpu": cpu,
                "gpu": gpu,
                "temp_c": temp_c,
                "active_task": active_task,
                "running_tasks": running_names,
                "queue_len": len(dev.ready_queue),
                "queue_tasks": queue_names[:4],
                "total_fallbacks": dev.total_fallbacks,
                "total_offloads": dev.total_offloads,
                "is_overloaded": is_overloaded,
                "fallback_active": fallback_active,
                "status": status_str,
            }

        # Links and in-flight offloaded packets
        links = []
        active_offloads = []
        for dev_id, dev in self.sim_gg.devices.items():
            for nid, neighbor in dev.neighbors.items():
                if dev_id < nid:
                    target_dev = self.sim_gg.devices.get(nid)
                    quality = "green"
                    if neighbor.reliability_score < 0.70:
                        quality = "amber"
                    if target_dev and (target_dev.resources.get_effective_cpu_utilization() > 0.85 or target_dev.resources.get_effective_gpu_utilization() > 0.90):
                        quality = "red"
                    links.append({
                        "source": dev_id,
                        "target": nid,
                        "reliability": round(neighbor.reliability_score, 2),
                        "quality": quality,
                        "bandwidth_mbps": dev.resources.hw.bandwidth_mbps,
                    })

            for task_id, offload in dev.offloaded_tasks.items():
                status_val = offload.get("status", "IN_FLIGHT")
                if status_val == "IN_FLIGHT":
                    target_id = offload.get("target_id")
                    task = offload.get("task")
                    dispatch_ms = float(offload.get("dispatch_time_ms", self.current_time_ms))
                    arrival_ms = float(offload.get("request_arrival_ms", dispatch_ms))
                    expected_ms = max(
                        arrival_ms + 0.001,
                        float(offload.get("expected_completion_ms", arrival_ms + 0.001)),
                    )
                    if self.current_time_ms < arrival_ms:
                        phase = "REQUEST_TX"
                        progress = 30.0 * (self.current_time_ms - dispatch_ms) / max(
                            0.001, arrival_ms - dispatch_ms
                        )
                    elif task and task.state.value == "OFFLOADED" and task.is_remote_execution:
                        phase = "RESULT_TX"
                        progress = 88.0
                    else:
                        phase = "REMOTE_EXECUTION"
                        progress = 30.0 + 58.0 * (
                            self.current_time_ms - arrival_ms
                        ) / max(0.001, expected_ms - arrival_ms)
                    active_offloads.append({
                        "task_id": task_id,
                        "source": dev_id,
                        "target": target_id,
                        "progress_pct": round(max(0.0, min(96.0, progress)), 1),
                        "phase": phase,
                        "dispatch_time_ms": dispatch_ms,
                        "request_arrival_ms": arrival_ms,
                        "expected_completion_ms": expected_ms,
                        "task_name": task.task_name if task else None,
                        "payload_kb": task.payload_kb if task else None,
                        "status": "IN_FLIGHT"
                    })

        new_events = self.sim_gg.telemetry_log[self._last_event_idx_gg:]
        self._last_event_idx_gg = len(self.sim_gg.telemetry_log)
        new_canonical_events = [event for event in self.sim_gg.canonical_events
                                if event["sequence"] > self._last_canonical_sequence]
        if new_canonical_events:
            self._last_canonical_sequence = new_canonical_events[-1]["sequence"]

        cutoff_us = int(max(0, self.current_time_ms - self.retention_window_ms) * 1000)
        critical_names = {task.task_id for task in self.pipeline_spec.tasks if task.criticality.value == "high"}
        m_gg = live_statistics((e for e in self.sim_gg.canonical_events if e["timestamp_us"] >= cutoff_us), critical_names)
        m_edf = live_statistics((e for e in self.sim_edf.canonical_events if e["timestamp_us"] >= cutoff_us), critical_names)

        return {
            "session_id": self.session_id,
            "current_time_ms": round(self.current_time_ms, 3),
            "horizon_ms": self.horizon_ms,
            "retention_window_ms": self.retention_window_ms,
            "evidence": "LIVE_NON_EVIDENCE",
            "fleet_size": self.fleet_size,
            "nodes": nodes,
            "links": links,
            "active_offloads": active_offloads,
            "resource_graph": resource_dependency_graph(self.sim_gg),
            "model_status": {
                "predictor": self.sched_gg.predictor_type,
                "estimator": self.sched_gg.estimator_type,
                "risk_threshold": self.sched_gg.risk_threshold,
                "inferences": self.sched_gg.gnn_inferences_count,
                "inference_latency": self.sched_gg.inference_latency_summary(),
                "federated_mode": "pretrained_snapshot",
            },
            "pipeline": {
                "pipeline_id": self.pipeline_spec.pipeline_id,
                "period_ms": (self.pipeline_spec.period_us or self.pipeline_spec.end_to_end_deadline_us) / 1000,
                "deadline_ms": self.pipeline_spec.end_to_end_deadline_us / 1000,
                "stages": [{"id": task.task_id,
                            "relative_deadline_ms": task.relative_deadline_us / 1000,
                            "nominal_work_ms": task.wcet_distribution.wcet_us / 1000,
                            "degraded_work_ms": min((point.remaining_wcet_us for point in task.exit_points), default=task.wcet_distribution.wcet_us) / 1000,
                            "resources": [{"kind": demand.resource.value, "fraction": demand.utilization_fraction}
                                          for demand in task.resource_demands],
                            "criticality": task.criticality.value}
                           for task in self.pipeline_spec.tasks],
                "edges": [{"source": source, "target": target}
                          for source, target in self.pipeline_spec.dependency_edges],
                "latest_jobs": latest_jobs,
                "focus_jobs": focus_jobs,
            },
            "step_events": new_events,
            "step_canonical_events": new_canonical_events,
            "metrics_gg": m_gg,
            "metrics_edf": m_edf,
            "status": "RUNNING",
        }


_LIVE_SESSION: Optional[LiveSimulationSession] = None
_LIVE_SESSIONS: Dict[str, LiveSimulationSession] = {}


def _get_live_session(session_id: Optional[str]) -> LiveSimulationSession:
    global _LIVE_SESSION
    if session_id is not None:
        session = _LIVE_SESSIONS.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Live simulation session not found")
        return session
    if _LIVE_SESSION is None:
        _LIVE_SESSION = LiveSimulationSession()
    return _LIVE_SESSION


@app.post("/api/live/start")
def live_start(req: LiveStartRequest):
    """Initializes a new continuous live simulation session."""
    global _LIVE_SESSION
    _LIVE_SESSION = LiveSimulationSession(
        fleet_size=req.fleet_size,
        seed=req.seed,
        horizon_ms=req.horizon_ms,
        enable_contention=req.enable_contention,
        fault_time_ms=req.fault_time_ms,
        fault_duration_ms=req.fault_duration_ms,
        contention_magnitude=req.contention_magnitude,
        target_node=req.target_node,
        risk_threshold=req.risk_threshold,
        reliability_threshold=req.reliability_threshold,
        safety_margin_ms=req.safety_margin_ms,
        network_delay_ms=req.network_delay_ms,
        period_ms=req.period_ms,
        deadline_ms=req.deadline_ms,
    )
    _LIVE_SESSION.session_id = uuid.uuid4().hex
    _LIVE_SESSIONS[_LIVE_SESSION.session_id] = _LIVE_SESSION
    while len(_LIVE_SESSIONS) > 16:
        _LIVE_SESSIONS.pop(next(iter(_LIVE_SESSIONS)))
    return _LIVE_SESSION.get_snapshot()


@app.post("/api/live/step")
def live_step(req: LiveStepRequest):
    """Advances continuous live simulation by delta_ms and streams real-time updates."""
    session = _get_live_session(req.session_id)
    with session.lock:
        return session.step(req.delta_ms)


@app.post("/api/live/inject_fault")
def live_inject_fault(req: LiveFaultRequest):
    """Dynamically injects contention or network stress at current live simulation clock."""
    session = _get_live_session(req.session_id)
    with session.lock:
        session.inject_fault(
            target_dev_id=req.target_node,
            cpu=req.cpu_load,
            gpu=req.gpu_load,
            duration_ms=req.duration_ms,
            delay_ms=req.network_delay_ms,
        )
        injection_time_ms = session.current_time_ms
    return {
        "status": "injected",
        "target_node": req.target_node,
        "session_id": session.session_id,
        "current_time_ms": injection_time_ms,
        "cpu_load": req.cpu_load,
        "gpu_load": req.gpu_load,
    }


@app.post("/api/live/reset")
def live_reset(req: LiveStartRequest):
    """Resets live simulation back to t=0.0 ms."""
    return live_start(req)


@app.post("/api/v1/live/sessions", status_code=status.HTTP_201_CREATED)
def create_live_session(req: LiveStartRequest):
    """Create a live, rolling, non-evidence simulation session."""
    return live_start(req)


@app.get("/api/v1/live/sessions/{session_id}")
def get_live_session(session_id: str):
    session = _get_live_session(session_id)
    with session.lock:
        return session.get_snapshot()


@app.post("/api/v1/live/sessions/{session_id}/step")
def step_live_session(session_id: str, req: LiveStepRequest):
    session = _get_live_session(session_id)
    with session.lock:
        return session.step(req.delta_ms)


@app.get("/api/v1/live/sessions/{session_id}/events")
def get_live_session_events(session_id: str, after_sequence: int = Query(default=0, ge=0)):
    """Return retained canonical live events after a sequence cursor."""
    session = _get_live_session(session_id)
    with session.lock:
        events = [
            event for event in session.sim_gg.canonical_events
            if event["sequence"] > after_sequence
        ]
    return {
        "session_id": session_id,
        "evidence": "LIVE_NON_EVIDENCE",
        "events": events,
        "next_sequence": events[-1]["sequence"] if events else after_sequence,
    }


@app.delete("/api/v1/live/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_live_session(session_id: str):
    global _LIVE_SESSION
    session = _LIVE_SESSIONS.pop(session_id, None)
    if session is None:
        raise HTTPException(status_code=404, detail="Live simulation session not found")
    if _LIVE_SESSION is session:
        _LIVE_SESSION = None
    return None


# -------------------------------------------------------------
# Core Health and Legacy Endpoints
# -------------------------------------------------------------
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "rts_predictive-api",
        "version": "2.1.0",
        "protocol": "API-v1-Research",
    }


@app.get("/api/section12")
def get_section12_trace():
    """Returns the deterministic failure scenario demonstration benchmark trace."""
    return get_cached_section12()


@app.post("/api/simulate")
def run_simulation(req: SimulationRequest):
    """Executes a dynamic simulation under PredictiveRuntime and EDF."""
    try:
        trace = run_dynamic_scenario(
            fault_time_ms=req.fault_time,
            contention_magnitude=req.contention,
            channel_jitter_ms=req.jitter,
            target_node=req.target_node,
            duration_ms=100.0,
            step_ms=1.0,
            fleet_size=req.fleet_size
        )
        return trace
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------------------------------------
# API v1 Research Specification Endpoints (Implementation Plan Section 14)
# -------------------------------------------------------------
@app.post("/api/v1/runs", status_code=status.HTTP_202_ACCEPTED)
def create_run(req: RunCreateRequest):
    """Validates a scenario and executes a discrete-event simulation run."""
    from rts_predictive.artifacts.canonical import canonical_json_bytes, sha256_bytes
    from rts_predictive.artifacts.code_provenance import code_provenance
    run_id = f"PR-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"

    # Build scenario simulator
    if req.scenario_type == "nominal":
        sim = create_nominal_scenario(seed=req.seed, fleet_size=req.fleet_size, duration_ms=req.duration_ms)
    elif req.scenario_type == "thermal":
        sim = create_thermal_scenario(seed=req.seed, fleet_size=req.fleet_size, duration_ms=req.duration_ms)
    elif req.scenario_type == "unreliable":
        sim = create_unreliable_neighbor_scenario(seed=req.seed, fleet_size=req.fleet_size, duration_ms=req.duration_ms)
    elif req.scenario_type == "bursty":
        sim = create_bursty_scenario(seed=req.seed, fleet_size=req.fleet_size, duration_ms=req.duration_ms)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown scenario: {req.scenario_type}")

    sim.run_id = run_id
    sched = _build_scheduler(req.policy)
    sim.attach_scheduler(sched)

    # Run simulation
    metrics = sim.run(duration_ms=req.duration_ms)
    event_bytes = b"".join(canonical_json_bytes(event) + b"\n"
                           for event in sim.canonical_events)
    components = {
        "predictor": getattr(sched, "predictor_type", "none"),
        "remote_estimator": getattr(sched, "estimator_type", "none"),
    }
    if components["predictor"] == "gnn":
        from rts_predictive.artifacts.canonical import sha256_file
        components["weights_sha256"] = sha256_file("models/gnn_predictive_runtime.pt")
        components["model_evidence"] = (
            "SIMULATION_CALIBRATED"
            if getattr(sched.gnn_predictor, "calibrated", False)
            else "WEIGHTS_ONLY"
        )
        components["model_bundle_version"] = getattr(
            sched.gnn_predictor, "bundle_version", None
        )
    if components["remote_estimator"] == "federated":
        components["federated_model_evidence"] = "SIMULATION_EVALUATED"
        components["federated_bundle_version"] = getattr(
            sched.federated_model, "bundle_version", None
        )
    metrics["gnn_inferences"] = getattr(sched, "gnn_inferences_count", 0)
    metrics["heuristic_predictions"] = getattr(sched, "heuristic_predictions_count", 0)
    metrics["predictor_exception"] = getattr(sched, "last_predictor_exception", None)
    metrics["inference_latency"] = (
        sched.inference_latency_summary()
        if hasattr(sched, "inference_latency_summary") else None
    )

    # Produce server-reduced replay frames
    frames = reduce_events_to_frames(
        canonical_events=sim.canonical_events,
        duration_ms=req.duration_ms,
        step_ms=1.0,
        fleet_size=req.fleet_size,
    )

    run_record = {
        "run_id": run_id,
        "status": "completed",
        "policy": req.policy,
        "scenario_type": req.scenario_type,
        "seed": req.seed,
        "duration_ms": req.duration_ms,
        "fleet_size": req.fleet_size,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "metrics": {
            **metrics,
            "evidence": "SIMULATED",
            "units": {
                "deadline_miss_ratio": "ratio",
                "avg_response_time_ms": "ms",
                "worst_case_response_time_ms": "ms",
                "avg_utility": "unitless [0,1]",
            }
        },
        "canonical_events": sim.canonical_events,
        "frames": frames,
        "manifest": {
            "schema_version": "rts_predictive.run-manifest/1.0",
            "run_id": run_id,
            "policy": req.policy,
            "seed": req.seed,
            "rng": sim.random_streams.provenance(),
            "scenario": req.scenario_type,
            "status": "completed",
            "event_count": len(sim.canonical_events),
            "event_sha256": sha256_bytes(event_bytes),
            "components": components,
            **code_provenance(),
        }
    }

    _RUNS_STORE[run_id] = run_record

    return {
        "run_id": run_id,
        "status": "completed",
        "message": "Simulation run executed and recorded",
        "event_count": len(sim.canonical_events),
    }


@app.get("/api/v1/runs/{run_id}")
def get_run(run_id: str):
    """Returns run state, progress, and manifest summary."""
    run_entry = _RUNS_STORE.get(run_id)
    if not run_entry:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return {
        "run_id": run_id,
        "status": run_entry["status"],
        "policy": run_entry["policy"],
        "scenario": run_entry["scenario_type"],
        "seed": run_entry["seed"],
        "created_at_utc": run_entry["created_at_utc"],
        "manifest": run_entry["manifest"],
    }


@app.get("/api/v1/runs/{run_id}/events")
def get_run_events(
    run_id: str,
    from_us: Optional[int] = Query(None, description="Start timestamp in microseconds"),
    to_us: Optional[int] = Query(None, description="End timestamp in microseconds"),
    types: Optional[str] = Query(None, description="Comma-separated event types to filter"),
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
):
    """Returns paginated canonical event stream for an immutable run."""
    run_entry = _RUNS_STORE.get(run_id)
    if not run_entry:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    events = run_entry["canonical_events"]

    if isinstance(from_us, int):
        events = [e for e in events if e.get("timestamp_us", 0) >= from_us]
    if isinstance(to_us, int):
        events = [e for e in events if e.get("timestamp_us", 0) <= to_us]
    if isinstance(types, str):
        allowed = {t.strip() for t in types.split(",")}
        events = [e for e in events if e.get("event_type") in allowed]

    offset_val = offset if isinstance(offset, int) else 0
    limit_val = limit if isinstance(limit, int) else 200

    total = len(events)
    page = events[offset_val : offset_val + limit_val]

    return {
        "run_id": run_id,
        "total": total,
        "offset": offset_val,
        "limit": limit_val,
        "events": page,
    }


@app.get("/api/v1/runs/{run_id}/frames")
def get_run_frames(run_id: str):
    """Returns server-reduced replay frames for dashboard playback."""
    run_entry = _RUNS_STORE.get(run_id)
    if not run_entry:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return {
        "run_id": run_id,
        "frames": run_entry["frames"],
        "total_frames": len(run_entry["frames"]),
    }


@app.get("/api/v1/runs/{run_id}/metrics")
def get_run_metrics(run_id: str):
    """Returns final metrics with evidence type and units."""
    run_entry = _RUNS_STORE.get(run_id)
    if not run_entry:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return run_entry["metrics"]


@app.post("/api/v1/compare")
def compare_policies(req: CompareRequest):
    """Compares policies or runs on aligned seeds."""
    if req.run_ids:
        raise HTTPException(status_code=400, detail="Run-ID comparison is not implemented")
    scenarios = {
        "nominal": create_nominal_scenario,
        "bursty": create_bursty_scenario,
        "thermal": create_thermal_scenario,
        "unreliable": create_unreliable_neighbor_scenario,
    }
    scenario_factory = scenarios.get(req.scenario_type)
    if scenario_factory is None:
        raise HTTPException(status_code=400, detail=f"Unknown scenario: {req.scenario_type}")
    results = {}
    policies = req.policies or ["PredictiveRuntime", "EDF", "RM", "Local-FIFO"]

    for pol in policies:
        sim = scenario_factory(seed=req.seed, fleet_size=4, duration_ms=req.duration_ms)
        sched = _build_scheduler(pol)
        sim.attach_scheduler(sched)
        m = sim.run(duration_ms=req.duration_ms)
        results[pol] = {
            "deadline_miss_ratio": m["deadline_miss_ratio"],
            "critical_misses": m["critical_misses"],
            "avg_response_time_ms": m["avg_response_time_ms"],
            "worst_case_response_time_ms": m["worst_case_response_time_ms"],
            "total_offloads": m["total_offloads"],
            "total_fallbacks": m["total_fallbacks"],
            "avg_utility": m.get("avg_utility", 1.0),
            "evidence": "SIMULATED",
        }

    return {
        "scenario_type": req.scenario_type,
        "seed": req.seed,
        "duration_ms": req.duration_ms,
        "comparisons": results,
    }


@app.get("/api/v1/models")
def get_models():
    """Report model availability without inventing validation evidence."""
    from pathlib import Path
    import json
    from rts_predictive.gnn.model import PredictiveRuntimeGNN

    weights = Path("models/gnn_predictive_runtime.pt")
    bundle_path = Path("models/gnn_predictive_runtime.bundle.json")
    bundle = json.loads(bundle_path.read_text(encoding="utf-8")) if bundle_path.is_file() else None
    federated_bundle_path = Path("models/federated_remote_estimator.bundle.json")
    federated_bundle = (
        json.loads(federated_bundle_path.read_text(encoding="utf-8"))
        if federated_bundle_path.is_file() else None
    )
    predictor = PredictiveRuntimeGNN()
    return {
        "predictor": {
            "model_version": bundle["bundle_version"] if bundle else "weights-only",
            "architecture": "PredictiveRuntimeGNN (2-layer GraphSAGE/GCN)",
            "parameters": sum(p.numel() for p in predictor.parameters()),
            "weights_file": str(weights),
            "weights_available": weights.is_file(),
            "measured_inference_latency_ms": None,
            "calibrated": bundle is not None,
            "input_features": 9,
            "feature_schema": bundle.get("feature_schema") if bundle else None,
            "decision_threshold": bundle.get("decision_threshold") if bundle else None,
            "test_metrics": bundle.get("test_metrics") if bundle else None,
            "evidence": "SIMULATION_CALIBRATED" if bundle else "WEIGHTS_ONLY",
        },
        "federated": {
            "model_version": (
                federated_bundle["bundle_version"] if federated_bundle else "unavailable"
            ),
            "architecture": "DeviceExecutionReliabilityModel (MLP 24-12)",
            "rounds_evaluated": federated_bundle["training"]["rounds"] if federated_bundle else None,
            "non_iid_partitions": federated_bundle["training"]["clients"] if federated_bundle else None,
            "test_metrics": federated_bundle.get("test_metrics") if federated_bundle else None,
            "evidence": federated_bundle.get("evidence") if federated_bundle else "UNAVAILABLE",
        }
    }


@app.get("/api/v1/verification/{config_hash}")
def get_verification_certificate(config_hash: str):
    """Retrieve only a certificate that was actually analyzed in this process."""
    certificate = _VERIFICATION_STORE.get(config_hash)
    if certificate is None:
        raise HTTPException(
            status_code=404,
            detail=f"No verification certificate is stored for configuration {config_hash}",
        )
    return certificate


@app.post("/api/v1/verification/analyze")
def analyze_verification(req: VerificationAnalyzeRequest):
    from rts_predictive.artifacts.code_provenance import code_provenance
    from rts_predictive.verification import (
        AnalysisProvenance,
        AnalysisRequest,
        CertificateBinding,
        FixedPriorityTask,
        TimingAnalyzer,
    )

    tasks = tuple(FixedPriorityTask(**task.model_dump()) for task in req.tasks)
    binding = CertificateBinding(
        scenario_hash=req.scenario_hash,
        scheduler_config_hash=req.scheduler_config_hash,
        hardware_profile_hash=req.hardware_profile_hash,
        resource_partition_id=req.resource_partition_id,
        fallback_mode_id=req.fallback_mode_id,
    )
    provenance = code_provenance()
    certificate = TimingAnalyzer.analyze(
        AnalysisRequest(
            tasks=tasks,
            max_iterations=req.max_iterations,
            binding=binding,
        ),
        provenance=AnalysisProvenance(
            code_revision=provenance["code_revision"] or "UNKNOWN",
            generated_at_utc=datetime.now(timezone.utc).isoformat(),
            source_artifact_hashes=(provenance["source_sha256"],),
        ),
    )
    encoded = jsonable_encoder(certificate)
    _VERIFICATION_STORE[certificate.certificate_id] = encoded
    _VERIFICATION_STORE[certificate.input_sha256] = encoded
    return encoded


# Mount frontend static directory
frontend_dir = os.path.join(root_dir, "frontend")
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/")
    def serve_index():
        index_file = os.path.join(frontend_dir, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        return {"message": "Frontend index.html not found"}

