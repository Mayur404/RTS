"""
Simulation Timeline Tracer for the PredictiveRuntime Interactive Dashboard.
Runs deterministic comparative scenarios and records fine-grained temporal snapshots
(1 ms granularity) of device loads, active tasks, packet transmissions, watchdog triggers,
and scheduler decisions under the Section 12 deterministic benchmark.
"""

from typing import Dict, List, Any, Tuple, Optional
import math
from rts_predictive.config import PredictiveRuntimeConfig, NODE_FLEET_DEFINITIONS
from rts_predictive.simulator.engine import DiscreteEventSimulator
from rts_predictive.experiments.scenarios import create_deterministic_failure_demo_scenario
from rts_predictive.schedulers.predictive_runtime import PredictiveRuntimeScheduler
from rts_predictive.schedulers.edf import EDFScheduler


def build_fleet_nodes_and_links(
    fleet_size: int,
    t: float,
    stage_id: int,
    dev1_cpu: float,
    dev1_gpu: float,
    dev1_status: str,
    dev1_active: str,
    dev2_cpu: float,
    dev2_gpu: float,
    dev2_status: str,
    dev2_active: str,
    channel_jitter_ms: float = 5.0,
    active_offload: Optional[Dict[str, Any]] = None,
    target_node: str = "Node 1"
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
    """Constructs real-time states for all fleet nodes and interconnected mesh links."""
    dev1_overloaded = dev1_cpu > 75.0 or dev1_status == "CONTENDED"
    dev1_fallback = stage_id >= 5 or dev1_status == "FALLBACK_ACTIVE"
    nodes = {
        "Device_1": {
            "id": "Device_1",
            "name": "Node 1: Jetson Orin Nano",
            "role": "Primary Origin / Ingress",
            "hardware": "Jetson-Orin-Nano",
            "cpu": round(dev1_cpu, 1),
            "gpu": round(dev1_gpu, 1),
            "temp_c": round(35.0 + (dev1_cpu / 100.0) * 38.0, 1),
            "active_task": dev1_active,
            "status": dev1_status,
            "queue_len": max(0, int(dev1_cpu / 18)),
            "is_overloaded": dev1_overloaded,
            "fallback_active": dev1_fallback,
            "color": "#10B981" if dev1_fallback else ("#EF4444" if dev1_overloaded else "#3B82F6"),
            "x": 200,
            "y": 210,
        },
        "Device_2": {
            "id": "Device_2",
            "name": "Node 2: Jetson AGX Orin",
            "role": "Candidate Compute Host",
            "hardware": "Jetson-AGX-Orin",
            "cpu": round(dev2_cpu, 1),
            "gpu": round(dev2_gpu, 1),
            "temp_c": round(35.0 + (dev2_cpu / 100.0) * 41.0, 1),
            "active_task": dev2_active,
            "status": dev2_status,
            "queue_len": max(0, int(dev2_cpu / 16)),
            "is_overloaded": dev2_cpu > 75.0 or dev2_status == "CONTENDED",
            "fallback_active": False,
            "color": "#EF4444" if (dev2_cpu > 75.0 or dev2_status == "CONTENDED") else "#10B981",
            "x": 600,
            "y": 210,
        }
    }

    if fleet_size >= 3:
        is_dev3_stressed = "Correlated" in target_node or "Both" in target_node
        dev3_cpu = min(92.0, (75.0 + 8.0 * math.sin(t * 0.2)) if is_dev3_stressed and t >= 35.0 else (34.0 + 3.0 * math.sin(t * 0.1)))
        dev3_gpu = min(94.0, (82.0 + 5.0 * math.cos(t * 0.3)) if is_dev3_stressed and t >= 35.0 else (40.0 + 4.0 * math.cos(t * 0.15)))
        nodes["Device_3"] = {
            "id": "Device_3",
            "name": "Node 3: Generic Edge GPU",
            "role": "Secondary Offload Peer",
            "hardware": "Edge-GPU-Server",
            "cpu": round(dev3_cpu, 1),
            "gpu": round(dev3_gpu, 1),
            "temp_c": round(38.0 + (dev3_cpu / 100.0) * 32.0, 1),
            "active_task": "LiDARPreprocess" if not is_dev3_stressed else "PeerQueueCongestion",
            "status": "CONTENDED" if dev3_cpu > 70.0 else "HEALTHY",
            "queue_len": max(0, int(dev3_cpu / 20)),
            "is_overloaded": dev3_cpu > 70.0,
            "fallback_active": False,
            "color": "#EF4444" if dev3_cpu > 70.0 else "#8B5CF6",
            "x": 400,
            "y": 80,
        }

    if fleet_size >= 4:
        dev4_cpu = 21.0 + 2.0 * math.sin(t * 0.2)
        dev4_gpu = 12.0
        nodes["Device_4"] = {
            "id": "Device_4",
            "name": "Node 4: Raspberry Pi 5",
            "role": "Low-Power Sensor Hub",
            "hardware": "Raspberry-Pi-5",
            "cpu": round(dev4_cpu, 1),
            "gpu": round(dev4_gpu, 1),
            "temp_c": round(39.0 + (dev4_cpu / 100.0) * 15.0, 1),
            "active_task": "SensorTelemetry",
            "status": "HEALTHY",
            "queue_len": 0,
            "is_overloaded": False,
            "fallback_active": False,
            "color": "#EC4899",
            "x": 400,
            "y": 340,
        }

    if fleet_size >= 6:
        dev5_cpu = 28.0 + 3.0 * math.sin(t * 0.1)
        dev5_gpu = 30.0 + 4.0 * math.cos(t * 0.2)
        nodes["Device_5"] = {
            "id": "Device_5",
            "name": "Node 5: Jetson Xavier NX",
            "role": "Auxiliary Edge Worker",
            "hardware": "Jetson-Xavier-NX",
            "cpu": round(dev5_cpu, 1),
            "gpu": round(dev5_gpu, 1),
            "temp_c": round(36.0 + (dev5_cpu / 100.0) * 28.0, 1),
            "active_task": "AuxEdgeInference",
            "status": "HEALTHY",
            "queue_len": 0,
            "is_overloaded": False,
            "fallback_active": False,
            "color": "#F59E0B",
            "x": 90,
            "y": 90,
        }
        dev6_cpu = 19.0 + 2.0 * math.cos(t * 0.3)
        dev6_gpu = 22.0 + 3.0 * math.sin(t * 0.2)
        nodes["Device_6"] = {
            "id": "Device_6",
            "name": "Node 6: Coral Edge TPU",
            "role": "Auxiliary Edge Worker",
            "hardware": "Coral-Edge-TPU",
            "cpu": round(dev6_cpu, 1),
            "gpu": round(dev6_gpu, 1),
            "temp_c": round(34.0 + (dev6_cpu / 100.0) * 20.0, 1),
            "active_task": "QuantizedVisionFilter",
            "status": "HEALTHY",
            "queue_len": 0,
            "is_overloaded": False,
            "fallback_active": False,
            "color": "#06B6D4",
            "x": 710,
            "y": 90,
        }

    if fleet_size >= 8:
        dev7_cpu = 15.0 + 2.0 * math.sin(t * 0.15)
        dev7_gpu = 5.0
        nodes["Device_7"] = {
            "id": "Device_7",
            "name": "Node 7: Robot Arm Controller",
            "role": "Auxiliary Edge Worker",
            "hardware": "Robot-Arm-MCU",
            "cpu": round(dev7_cpu, 1),
            "gpu": round(dev7_gpu, 1),
            "temp_c": round(34.0 + (dev7_cpu / 100.0) * 12.0, 1),
            "active_task": "MotorKinematics",
            "status": "HEALTHY",
            "queue_len": 0,
            "is_overloaded": False,
            "fallback_active": False,
            "color": "#14B8A6",
            "x": 90,
            "y": 330,
        }
        dev8_cpu = 42.0 + 4.0 * math.sin(t * 0.25)
        dev8_gpu = 46.0 + 3.0 * math.cos(t * 0.2)
        nodes["Device_8"] = {
            "id": "Device_8",
            "name": "Node 8: High-Res Vision Node",
            "role": "Auxiliary Edge Worker",
            "hardware": "Vision-Sensor-Node",
            "cpu": round(dev8_cpu, 1),
            "gpu": round(dev8_gpu, 1),
            "temp_c": round(37.0 + (dev8_cpu / 100.0) * 35.0, 1),
            "active_task": "StereoDepthMap",
            "status": "HEALTHY",
            "queue_len": 1,
            "is_overloaded": False,
            "fallback_active": False,
            "color": "#A855F7",
            "x": 710,
            "y": 330,
        }

    # Primary channel: Device_1 <-> Device_2
    if stage_id == 3:
        l12_quality = "amber" if channel_jitter_ms > 2.0 else "green"
        l12_status = "IN_FLIGHT"
        l12_latency = 4.0 + channel_jitter_ms
        l12_abort = False
    elif stage_id == 4:
        l12_quality = "red"
        l12_status = "REMOTE_STRESSED"
        l12_latency = 16.5 + channel_jitter_ms
        l12_abort = False
    elif stage_id == 5:
        l12_quality = "red"
        l12_status = "ABORT"
        l12_latency = 19.5 + channel_jitter_ms
        l12_abort = True
    else:
        l12_quality = "green" if channel_jitter_ms < 5.0 else "amber"
        l12_status = "NOMINAL"
        l12_latency = round(2.0 + channel_jitter_ms * 0.2, 1)
        l12_abort = False

    links = [
        {
            "source": "Device_1",
            "target": "Device_2",
            "quality": l12_quality,
            "status": l12_status,
            "latency_ms": round(l12_latency, 1),
            "abort_tag": "ABORT: REMOTE BOTTLENECK" if l12_abort else None,
            "is_offload_channel": True
        }
    ]

    if fleet_size >= 3:
        links.append({
            "source": "Device_1",
            "target": "Device_3",
            "quality": "green",
            "status": "NOMINAL",
            "latency_ms": round(1.8 + channel_jitter_ms * 0.15, 1),
            "abort_tag": None,
            "is_offload_channel": False
        })
        links.append({
            "source": "Device_2",
            "target": "Device_3",
            "quality": "amber" if stage_id in [4, 5] else "green",
            "status": "NOMINAL",
            "latency_ms": round(6.5 if stage_id in [4, 5] else 2.2, 1),
            "abort_tag": None,
            "is_offload_channel": False
        })

    if fleet_size >= 4:
        links.append({
            "source": "Device_1",
            "target": "Device_4",
            "quality": "green",
            "status": "NOMINAL",
            "latency_ms": 1.4,
            "abort_tag": None,
            "is_offload_channel": False
        })
        links.append({
            "source": "Device_2",
            "target": "Device_4",
            "quality": "green",
            "status": "NOMINAL",
            "latency_ms": 2.1,
            "abort_tag": None,
            "is_offload_channel": False
        })
        links.append({
            "source": "Device_3",
            "target": "Device_4",
            "quality": "green",
            "status": "NOMINAL",
            "latency_ms": 2.5,
            "abort_tag": None,
            "is_offload_channel": False
        })

    if fleet_size >= 6:
        links.extend([
            {"source": "Device_1", "target": "Device_5", "quality": "green", "status": "NOMINAL", "latency_ms": 1.7, "abort_tag": None, "is_offload_channel": False},
            {"source": "Device_3", "target": "Device_5", "quality": "green", "status": "NOMINAL", "latency_ms": 2.0, "abort_tag": None, "is_offload_channel": False},
            {"source": "Device_2", "target": "Device_6", "quality": "green", "status": "NOMINAL", "latency_ms": 1.9, "abort_tag": None, "is_offload_channel": False},
            {"source": "Device_3", "target": "Device_6", "quality": "green", "status": "NOMINAL", "latency_ms": 2.2, "abort_tag": None, "is_offload_channel": False},
        ])

    if fleet_size >= 8:
        links.extend([
            {"source": "Device_1", "target": "Device_7", "quality": "green", "status": "NOMINAL", "latency_ms": 1.6, "abort_tag": None, "is_offload_channel": False},
            {"source": "Device_4", "target": "Device_7", "quality": "green", "status": "NOMINAL", "latency_ms": 2.3, "abort_tag": None, "is_offload_channel": False},
            {"source": "Device_2", "target": "Device_8", "quality": "green", "status": "NOMINAL", "latency_ms": 1.8, "abort_tag": None, "is_offload_channel": False},
            {"source": "Device_4", "target": "Device_8", "quality": "green", "status": "NOMINAL", "latency_ms": 2.4, "abort_tag": None, "is_offload_channel": False},
        ])

    topology = {
        "fleet_size": fleet_size,
        "nodes": list(nodes.values()),
        "links": links
    }
    return nodes, links, topology


def extract_task_intervals(tasks: List[Any], duration_ms: float) -> List[Dict[str, Any]]:
    """Extracts executed task intervals for synchronized Gantt chart visualization."""
    intervals = []
    for t in tasks:
        if t.start_time_ms is None and t.finish_time_ms is None:
            continue
        start = t.start_time_ms if t.start_time_ms is not None else t.release_time_ms
        finish = t.finish_time_ms if t.finish_time_ms is not None else duration_ms

        is_miss = (t.deadline_met is False) or (t.state.value == "DEADLINE_MISSED")
        if is_miss:
            cat = "Deadline Miss / Lateness"
            color = "#DC2626"
        elif t.is_degraded:
            cat = "Degraded Fallback"
            color = "#16A34A"
        elif t.is_remote_execution or t.offload_target_id is not None:
            cat = "Offload In-Flight"
            color = "#7C3AED"
        else:
            cat = "Nominal Execution"
            color = "#2563EB"

        remaining_slack = round(t.deadline_ms - finish, 2)
        exec_duration = round(max(0.2, finish - start), 2)

        intervals.append({
            "task_name": t.task_name,
            "instance_id": t.instance_id,
            "device_id": t.device_id,
            "origin_device_id": t.origin_device_id,
            "start_time_ms": round(start, 2),
            "finish_time_ms": round(finish, 2),
            "duration_ms": exec_duration,
            "release_time_ms": round(t.release_time_ms, 2),
            "deadline_ms": round(t.deadline_ms, 2),
            "nominal_wcet_ms": round(t.nominal_wcet_ms, 2),
            "degraded_wcet_ms": round(t.degraded_wcet_ms, 2),
            "is_degraded": t.is_degraded,
            "is_critical": t.is_critical,
            "deadline_met": t.deadline_met,
            "slack_ms": remaining_slack,
            "category": cat,
            "color": color
        })
    return sorted(intervals, key=lambda x: x["start_time_ms"])


def run_traced_simulation(duration_ms: float = 100.0, step_ms: float = 1.0) -> Dict[str, Any]:
    """
    Executes the Section 12 deterministic scenario under both PredictiveRuntime and EDF,
    generating synchronized millisecond-by-millisecond state vectors for interactive playback.
    """
    # 1. Run PredictiveRuntime
    sim_gg = create_deterministic_failure_demo_scenario(seed=42)
    sched_gg = PredictiveRuntimeScheduler(risk_threshold=0.60, reliability_threshold=0.70, safety_margin_ms=3.0)
    sim_gg.attach_scheduler(sched_gg)
    metrics_gg = sim_gg.run(duration_ms=duration_ms)

    # 2. Run EDF
    sim_edf = create_deterministic_failure_demo_scenario(seed=42)
    sched_edf = EDFScheduler()
    sim_edf.attach_scheduler(sched_edf)
    metrics_edf = sim_edf.run(duration_ms=duration_ms)

    # Replay is reduced exclusively from the canonical streams. Resource values
    # that were not recorded remain null; the former hand-authored narrative
    # below is unreachable and retained temporarily only for source-history
    # comparison during the dashboard migration.
    from rts_predictive.dashboard.frame_reducer import reduce_events_to_frames
    frames = reduce_events_to_frames(
        sim_gg.canonical_events,
        duration_ms=duration_ms,
        step_ms=step_ms,
        fleet_size=4,
    )
    latest = frames[-1] if frames else {"nodes": {}, "links": []}
    metrics_gg["wcrt_ms"] = metrics_gg.get("worst_case_response_time_ms", 0.0)
    metrics_edf["wcrt_ms"] = metrics_edf.get("worst_case_response_time_ms", 0.0)
    return {
        "evidence": "SIMULATED",
        "frames": frames,
        "max_t": float(duration_ms),
        "step_ms": step_ms,
        "topology": {"nodes": latest["nodes"], "links": latest["links"]},
        "metrics_gg": metrics_gg,
        "metrics_edf": metrics_edf,
        "sim_gg_log": sim_gg.telemetry_log,
        "sim_edf_log": sim_edf.telemetry_log,
        "tasks_gg": extract_task_intervals(sim_gg.all_tasks, duration_ms),
        "tasks_edf": extract_task_intervals(sim_edf.all_tasks, duration_ms),
    }

    # 3. Build Timeline Frame by Frame (1 ms resolution)
    frames: List[Dict[str, Any]] = []
    total_steps = int(duration_ms / step_ms) + 1

    for step_idx in range(total_steps):
        t = round(step_idx * step_ms, 2)

        # -------------------------------------------------------------
        # Determine PredictiveRuntime State Machine Phase (Section 12 Exact Flow)
        # -------------------------------------------------------------
        if t < 25.0:
            stage_id = 1
            stage_name = "Stage 1: Nominal Local Execution"
            stage_desc = "Sensors acquiring normally. CPU/GPU balanced. Slack > 15 ms."
            badge_color = "#16A34A"
            channel_state = "IDLE"
            watchdog_status = "IDLE"
            active_offload = None
        elif t < 33.0:
            stage_id = 2
            stage_name = "Stage 2: Device 1 Ingress Contention Spike"
            stage_desc = "Contention surge hits Device 1 (CPU 90%, GPU 95%). GNN detects rapidly diminishing slack."
            badge_color = "#D97706"
            channel_state = "QUEUE_BUILDUP"
            watchdog_status = "GNN_EVALUATING"
            active_offload = None
        elif t < 45.0:
            stage_id = 3
            stage_name = "Stage 3: GNN Risk Trigger -> Cooperative Offload"
            stage_desc = "GNN risk p_miss = 0.85 >= 0.65 threshold. Perception (16KB) offloaded to Device 2."
            badge_color = "#2563EB"
            channel_state = "IN_FLIGHT"
            watchdog_status = "WATCHDOG_ACTIVE"
            tx_pct = min(100.0, (t - 33.0) / (38.8 - 33.0) * 100.0) if t < 38.8 else 100.0
            active_offload = {
                "task_name": "Perception (16 KB)",
                "source": "Device_1",
                "target": "Device_2",
                "progress_pct": round(tx_pct, 1),
                "status": "Transmitting via Mesh Link" if t < 38.8 else "Remote Execution on Device 2",
            }
        elif t < 50.0:
            stage_id = 4
            stage_name = "Stage 4: Remote Device 2 Secondary Contention Shock"
            stage_desc = "Device 2 hit with sudden secondary contention (CPU 98%). Remote completion unsafe!"
            badge_color = "#DC2626"
            channel_state = "REMOTE_STRESSED"
            watchdog_status = "RISK_DETECTED"
            active_offload = {
                "task_name": "Perception (16 KB)",
                "source": "Device_1",
                "target": "Device_2",
                "progress_pct": 100.0,
                "status": "Target Overloaded (CPU 98%) - Deadline Threat",
            }
        elif t < 53.0:
            stage_id = 5
            stage_name = "Stage 5: Watchdog In-Flight Abort Triggered"
            stage_desc = "Watchdog aborts remote reliance at t=49.5ms! Deploys local MobileNet INT8 (WCET drops 15ms -> 5ms)."
            badge_color = "#7C3AED"
            channel_state = "ABORTED"
            watchdog_status = "RECOVERING_LOCALLY"
            active_offload = None
        else:
            stage_id = 6
            stage_name = "Stage 6: Local Degraded Model Completes (Saved!)"
            stage_desc = "Perception completed safely at t=52.4ms with +7.6ms slack remaining before D=60.0ms!"
            badge_color = "#16A34A"
            channel_state = "MISSION_SAFE"
            watchdog_status = "SAFE"
            active_offload = None

        # -------------------------------------------------------------
        # Telemetry & Resource States (Device 1 & Device 2)
        # -------------------------------------------------------------
        # Device 1 loads
        if t < 25.0:
            dev1_cpu = 28.0 + 4.0 * math.sin(t * 0.4)
            dev1_gpu = 35.0 + 5.0 * math.cos(t * 0.3)
            dev1_status = "HEALTHY"
        elif t < 125.0:
            dev1_cpu = min(98.0, 90.0 + 6.0 * math.sin(t * 0.2))
            dev1_gpu = min(99.0, 95.0 + 3.0 * math.cos(t * 0.5))
            dev1_status = "CONTENDED" if stage_id < 5 else "FALLBACK_ACTIVE"
        else:
            dev1_cpu = 45.0
            dev1_gpu = 40.0
            dev1_status = "NORMAL"

        # Device 2 loads
        if t < 45.0:
            dev2_cpu = 22.0 + 3.0 * math.cos(t * 0.2)
            dev2_gpu = 18.0 + 4.0 * math.sin(t * 0.3)
            dev2_status = "HEALTHY"
        elif t < 135.0:
            dev2_cpu = min(99.0, 98.0 + 1.5 * math.sin(t * 0.5))
            dev2_gpu = min(99.0, 95.0 + 2.0 * math.cos(t * 0.4))
            dev2_status = "CONTENDED"
        else:
            dev2_cpu = 30.0
            dev2_gpu = 25.0
            dev2_status = "NORMAL"

        # Active tasks at time t
        if t < 20.0:
            dev1_active = "Sense"
            dev2_active = "Sense"
        elif t < 33.0:
            dev1_active = "Perception (Nominal)"
            dev2_active = "ObstacleDetection"
        elif t < 45.0:
            dev1_active = "Actuation"
            dev2_active = "Perception (Offloaded)"
        elif t < 50.0:
            dev1_active = "Tracking"
            dev2_active = "Contention Queue"
        elif t < 53.0:
            dev1_active = "Perception [INT8 Fallback]"
            dev2_active = "Stalled Queue"
        else:
            dev1_active = "ObstacleDetection"
            dev2_active = "Sense"

        # PredictiveRuntime Cumulative stats up to time t
        gg_ev_until_t = [e for e in sim_gg.telemetry_log if e["timestamp_ms"] <= t]
        gg_completed = len([e for e in gg_ev_until_t if e["event"] == "TASK_COMPLETED"])
        gg_fallbacks = len([e for e in gg_ev_until_t if e["event"] == "PREDICTIVE_RUNTIME_FALLBACK_ACTIVATED"])
        gg_offloads = len([e for e in gg_ev_until_t if e["event"] == "PREDICTIVE_RUNTIME_OFFLOAD_DISPATCH"])
        gg_misses = len([e for e in gg_ev_until_t if e["event"] == "DEADLINE_MISSED"])

        # EDF Cumulative stats up to time t
        edf_ev_until_t = [e for e in sim_edf.telemetry_log if e["timestamp_ms"] <= t]
        edf_completed = len([e for e in edf_ev_until_t if e["event"] == "TASK_COMPLETED"])
        edf_misses = len([e for e in edf_ev_until_t if e["event"] == "DEADLINE_MISSED"])

        # Perception specific status under EDF
        if t < 25.0:
            edf_crit_status = "Running Normally"
        elif t < 59.1:
            edf_crit_status = "Blocked in GPU Contention Backlog"
        else:
            edf_crit_status = "DEADLINE MISSED (+18.4ms Late)"

        # Perception specific status under PredictiveRuntime
        if t < 33.0:
            gg_crit_status = "Device 1 (Contention Surge Detected)"
        elif t < 50.0:
            gg_crit_status = "In-Flight -> Device 2 (Candidate Degraded)"
        elif t < 53.0:
            gg_crit_status = "Aborted & Recovering Locally (INT8 Fallback)"
        else:
            gg_crit_status = "COMPLETED SAFELY @ 52.4ms (Slack: +7.6ms)"

        nodes_state, links_state, topo = build_fleet_nodes_and_links(
            fleet_size=4,
            t=t,
            stage_id=stage_id,
            dev1_cpu=dev1_cpu,
            dev1_gpu=dev1_gpu,
            dev1_status=dev1_status,
            dev1_active=dev1_active,
            dev2_cpu=dev2_cpu,
            dev2_gpu=dev2_gpu,
            dev2_status=dev2_status,
            dev2_active=dev2_active,
            channel_jitter_ms=5.0,
            active_offload=active_offload,
            target_node="Node 1"
        )

        frames.append({
            "t": t,
            "evidence": "DEMONSTRATION",
            "stage_id": stage_id,
            "stage_name": stage_name,
            "stage_desc": stage_desc,
            "badge_color": badge_color,

            "channel_state": channel_state,
            "watchdog_status": watchdog_status,
            "active_offload": active_offload,
            "nodes": nodes_state,
            "links": links_state,
            "dev1": {
                "cpu": round(dev1_cpu, 1),
                "gpu": round(dev1_gpu, 1),
                "temp_c": round(35.0 + (dev1_cpu / 100.0) * 38.0, 1),
                "active_task": dev1_active,
                "status": dev1_status,
                "queue_len": max(0, int(dev1_cpu / 18)),
            },
            "dev2": {
                "cpu": round(dev2_cpu, 1),
                "gpu": round(dev2_gpu, 1),
                "temp_c": round(35.0 + (dev2_cpu / 100.0) * 41.0, 1),
                "active_task": dev2_active,
                "status": dev2_status,
                "queue_len": max(0, int(dev2_cpu / 16)),
            },
            "gg_metrics": {
                "completed": gg_completed,
                "missed": gg_misses,
                "critical_misses": 0,
                "fallbacks": gg_fallbacks,
                "offloads": gg_offloads,
                "crit_status": gg_crit_status,
            },
            "edf_metrics": {
                "completed": edf_completed,
                "missed": edf_misses,
                "critical_misses": 2 if t >= 59.1 else 0,
                "crit_status": edf_crit_status,
            },
        })

    _, _, final_topo = build_fleet_nodes_and_links(
        fleet_size=4, t=duration_ms, stage_id=6,
        dev1_cpu=45.0, dev1_gpu=40.0, dev1_status="NORMAL", dev1_active="Sense",
        dev2_cpu=30.0, dev2_gpu=25.0, dev2_status="NORMAL", dev2_active="Sense"
    )

    metrics_gg["wcrt_ms"] = metrics_gg.get("worst_case_response_time_ms", 18.2)
    metrics_edf["wcrt_ms"] = metrics_edf.get("worst_case_response_time_ms", 86.2)

    for frame in frames:
        frame["evidence"] = "DEMONSTRATION"
    return {
        "evidence": "DEMONSTRATION",
        "frames": frames,
        "max_t": float(duration_ms),
        "step_ms": step_ms,
        "topology": final_topo,
        "metrics_gg": metrics_gg,
        "metrics_edf": metrics_edf,
        "sim_gg_log": sim_gg.telemetry_log,
        "sim_edf_log": sim_edf.telemetry_log,
        "tasks_gg": extract_task_intervals(sim_gg.all_tasks, duration_ms),
        "tasks_edf": extract_task_intervals(sim_edf.all_tasks, duration_ms),
    }



def run_dynamic_scenario(
    fault_time_ms: float = 25.0,
    contention_magnitude: float = 0.90,
    channel_jitter_ms: float = 5.0,
    target_node: str = "Node 1",
    duration_ms: float = 100.0,
    step_ms: float = 1.0,
    fleet_size: int = 4
) -> Dict[str, Any]:
    """
    Executes a dynamically parameterized scenario injecting synthetic runtime faults
    on the fly, evaluating both PredictiveRuntime and EDF to produce comparative timelines.
    """
    def _build_sim() -> DiscreteEventSimulator:
        cfg = PredictiveRuntimeConfig(simulation_duration_ms=duration_ms)
        sim = DiscreteEventSimulator(config=cfg, seed=42, fleet_size=fleet_size)
        sim.schedule_periodic_tasks(duration_ms=duration_ms)

        # Configure mesh link characteristics
        if "Device_2" in sim.devices["Device_1"].neighbors:
            sim.devices["Device_1"].neighbors["Device_2"].avg_latency_ms = 4.0 + channel_jitter_ms
            sim.devices["Device_1"].neighbors["Device_2"].packet_loss_rate = min(0.35, channel_jitter_ms * 0.012)

        # Inject contention faults based on target node
        if "Node 1" in target_node or "Simultaneous" in target_node or "Both" in target_node or "Correlated" in target_node:
            sim.schedule_contention_burst(
                target_device_id="Device_1",
                start_time_ms=fault_time_ms,
                duration_ms=min(80.0, duration_ms - fault_time_ms),
                cpu_load=contention_magnitude,
                gpu_load=min(0.99, contention_magnitude + 0.05),
                network_delay_ms=channel_jitter_ms
            )

        if "Node 2" in target_node or "Simultaneous" in target_node or "Both" in target_node or "Correlated" in target_node:
            t2 = fault_time_ms + (15.0 if ("Simultaneous" in target_node or "Both" in target_node or "Correlated" in target_node) else 0.0)
            if t2 < duration_ms:
                sim.schedule_contention_burst(
                    target_device_id="Device_2",
                    start_time_ms=t2,
                    duration_ms=min(70.0, duration_ms - t2),
                    cpu_load=contention_magnitude,
                    gpu_load=min(0.99, contention_magnitude + 0.04),
                    network_delay_ms=channel_jitter_ms * 1.5
                )

        return sim

    # Run PredictiveRuntime
    sim_gg = _build_sim()
    sched_gg = PredictiveRuntimeScheduler(risk_threshold=0.60, reliability_threshold=0.70, safety_margin_ms=3.0)
    sim_gg.attach_scheduler(sched_gg)
    metrics_gg = sim_gg.run(duration_ms=duration_ms)

    # Run EDF
    sim_edf = _build_sim()
    sched_edf = EDFScheduler()
    sim_edf.attach_scheduler(sched_edf)
    metrics_edf = sim_edf.run(duration_ms=duration_ms)

    tasks_gg = extract_task_intervals(sim_gg.all_tasks, duration_ms)
    tasks_edf = extract_task_intervals(sim_edf.all_tasks, duration_ms)

    from rts_predictive.dashboard.frame_reducer import reduce_events_to_frames
    frames = reduce_events_to_frames(
        sim_gg.canonical_events,
        duration_ms=duration_ms,
        step_ms=step_ms,
        fleet_size=fleet_size,
    )
    latest = frames[-1] if frames else {"nodes": {}, "links": []}
    metrics_gg["wcrt_ms"] = metrics_gg.get("worst_case_response_time_ms", 0.0)
    metrics_edf["wcrt_ms"] = metrics_edf.get("worst_case_response_time_ms", 0.0)
    metrics_gg["evidence"] = "SIMULATED"
    metrics_edf["evidence"] = "SIMULATED"
    return {
        "evidence": "SIMULATED",
        "frames": frames,
        "max_t": float(duration_ms),
        "step_ms": step_ms,
        "topology": {"nodes": latest["nodes"], "links": latest["links"]},
        "metrics_gg": metrics_gg,
        "metrics_edf": metrics_edf,
        "sim_gg_log": sim_gg.telemetry_log,
        "sim_edf_log": sim_edf.telemetry_log,
        "tasks_gg": tasks_gg,
        "tasks_edf": tasks_edf,
        "duration_ms": duration_ms,
        "params": {
            "fault_time_ms": fault_time_ms,
            "contention_magnitude": contention_magnitude,
            "channel_jitter_ms": channel_jitter_ms,
            "target_node": target_node,
            "fleet_size": fleet_size,
        },
    }

    # 3. Build Synchronized Millisecond Frames
    frames: List[Dict[str, Any]] = []
    total_steps = int(duration_ms / step_ms) + 1

    t_fault = fault_time_ms
    t_shock = t_fault + 15.0 if ("Simultaneous" in target_node or "Both" in target_node or "Correlated" in target_node) else (t_fault if "Node 2" in target_node else 999.0)

    for step_idx in range(total_steps):
        t = round(step_idx * step_ms, 2)

        if t < t_fault:
            stage_id = 1
            stage_name = "Stage 1: Nominal Execution"
            stage_desc = f"All nodes nominal. Dynamic fault scheduled at t={t_fault:.1f}ms."
            badge_color = "#16A34A"
            channel_state = "IDLE"
            watchdog_status = "IDLE"
            active_offload = None
        elif t < t_fault + 8.0:
            stage_id = 2
            stage_name = f"Stage 2: Fault Triggered on {target_node}"
            stage_desc = f"Contention surge ({int(contention_magnitude*100)}% load). GNN risk evaluation triggered."
            badge_color = "#D97706"
            channel_state = "QUEUE_BUILDUP"
            watchdog_status = "GNN_EVALUATING"
            active_offload = None
        elif t < min(t_shock, t_fault + 20.0):
            stage_id = 3
            stage_name = "Stage 3: Cooperative Offload Dispatched"
            stage_desc = f"Perception offloaded over wireless mesh (Jitter: {channel_jitter_ms:.1f}ms)."
            badge_color = "#2563EB"
            channel_state = "IN_FLIGHT"
            watchdog_status = "WATCHDOG_ACTIVE"
            active_offload = {
                "task_name": "Perception (16 KB)",
                "source": "Device_1",
                "target": "Device_2",
                "progress_pct": 50.0,
                "status": f"Transmitting via Mesh Link (Jitter: {channel_jitter_ms:.1f}ms)",
            }
        elif t < min(t_shock + 6.0, t_fault + 26.0) and t_shock < duration_ms:
            stage_id = 4
            stage_name = "Stage 4: Remote Neighbor Degradation"
            stage_desc = "Remote peer hit with secondary shock. Offload completion unsafe."
            badge_color = "#DC2626"
            channel_state = "REMOTE_STRESSED"
            watchdog_status = "RISK_DETECTED"
            active_offload = {
                "task_name": "Perception (16 KB)",
                "source": "Device_1",
                "target": "Device_2",
                "progress_pct": 100.0,
                "status": "Candidate Peer Stalled",
            }
        elif t < min(t_shock + 9.0, t_fault + 29.0) and t_shock < duration_ms:
            stage_id = 5
            stage_name = "Stage 5: Watchdog In-Flight Abort"
            stage_desc = "Watchdog detects remote bottleneck! Local degraded fallback deployed."
            badge_color = "#7C3AED"
            channel_state = "ABORTED"
            watchdog_status = "RECOVERING_LOCALLY"
            active_offload = None
        else:
            stage_id = 6
            stage_name = "Stage 6: Fallback Mission Preserved"
            stage_desc = "Tasks completed safely within analytical deadline bounds."
            badge_color = "#16A34A"
            channel_state = "MISSION_SAFE"
            watchdog_status = "SAFE"
            active_offload = None

        is_dev1_stressed = ("Node 1" in target_node or "Both" in target_node or "Simultaneous" in target_node or "Correlated" in target_node) and (t >= t_fault and t <= t_fault + 80.0)
        is_dev2_stressed = ("Node 2" in target_node or "Both" in target_node or "Simultaneous" in target_node or "Correlated" in target_node) and (t >= t_shock and t <= t_shock + 70.0)

        dev1_cpu = min(99.0, (contention_magnitude * 100.0) if is_dev1_stressed else (28.0 + 3.0 * math.sin(t * 0.4)))
        dev1_gpu = min(99.0, (min(0.99, contention_magnitude + 0.05) * 100.0) if is_dev1_stressed else (32.0 + 4.0 * math.cos(t * 0.3)))
        dev2_cpu = min(99.0, (contention_magnitude * 100.0) if is_dev2_stressed else (22.0 + 2.0 * math.cos(t * 0.2)))
        dev2_gpu = min(99.0, (min(0.99, contention_magnitude + 0.04) * 100.0) if is_dev2_stressed else (20.0 + 3.0 * math.sin(t * 0.3)))

        dev1_status = "CONTENDED" if is_dev1_stressed else ("FALLBACK_ACTIVE" if stage_id >= 5 else "HEALTHY")
        dev1_active = "Perception [Degraded]" if stage_id >= 5 else ("Perception" if is_dev1_stressed else "Sense")
        dev2_status = "CONTENDED" if is_dev2_stressed else "HEALTHY"
        dev2_active = "Perception (Remote)" if stage_id == 3 else ("Backlog" if is_dev2_stressed else "ObstacleDetection")

        nodes_state, links_state, topo = build_fleet_nodes_and_links(
            fleet_size=fleet_size,
            t=t,
            stage_id=stage_id,
            dev1_cpu=dev1_cpu,
            dev1_gpu=dev1_gpu,
            dev1_status=dev1_status,
            dev1_active=dev1_active,
            dev2_cpu=dev2_cpu,
            dev2_gpu=dev2_gpu,
            dev2_status=dev2_status,
            dev2_active=dev2_active,
            channel_jitter_ms=channel_jitter_ms,
            active_offload=active_offload,
            target_node=target_node
        )

        frames.append({
            "t": t,
            "stage_id": stage_id,
            "stage_name": stage_name,
            "stage_desc": stage_desc,
            "badge_color": badge_color,
            "channel_state": channel_state,
            "watchdog_status": watchdog_status,
            "active_offload": active_offload,
            "nodes": nodes_state,
            "links": links_state,
            "dev1": {
                "cpu": round(dev1_cpu, 1),
                "gpu": round(dev1_gpu, 1),
                "temp_c": round(35.0 + (dev1_cpu / 100.0) * 38.0, 1),
                "active_task": dev1_active,
                "status": dev1_status,
                "queue_len": max(0, int(dev1_cpu / 18)),
            },
            "dev2": {
                "cpu": round(dev2_cpu, 1),
                "gpu": round(dev2_gpu, 1),
                "temp_c": round(35.0 + (dev2_cpu / 100.0) * 41.0, 1),
                "active_task": dev2_active,
                "status": dev2_status,
                "queue_len": max(0, int(dev2_cpu / 16)),
            },
            "gg_metrics": {
                "completed": metrics_gg["completed_tasks"],
                "missed": metrics_gg["deadline_missed_count"],
                "critical_misses": metrics_gg["critical_misses"],
                "fallbacks": metrics_gg["total_fallbacks"],
                "offloads": metrics_gg["total_offloads"],
                "crit_status": "COMPLETED SAFELY (Preserved)" if t >= t_fault + 27.0 else "Arbitration In Progress",
            },
            "edf_metrics": {
                "completed": metrics_edf["completed_tasks"],
                "missed": metrics_edf["deadline_missed_count"],
                "critical_misses": metrics_edf["critical_misses"],
                "crit_status": f"MISSED DEADLINES ({metrics_edf['deadline_missed_count']} misses)" if metrics_edf['deadline_missed_count'] > 0 else "Nominal",
            }
        })

    _, _, final_topo = build_fleet_nodes_and_links(
        fleet_size=fleet_size, t=duration_ms, stage_id=6,
        dev1_cpu=dev1_cpu, dev1_gpu=dev1_gpu, dev1_status="HEALTHY", dev1_active="Sense",
        dev2_cpu=dev2_cpu, dev2_gpu=dev2_gpu, dev2_status="HEALTHY", dev2_active="Sense",
        channel_jitter_ms=channel_jitter_ms, target_node=target_node
    )

    metrics_gg["wcrt_ms"] = metrics_gg.get("worst_case_response_time_ms")
    metrics_edf["wcrt_ms"] = metrics_edf.get("worst_case_response_time_ms")
    metrics_gg["evidence"] = "SIMULATED"
    metrics_edf["evidence"] = "SIMULATED"
    for frame in frames:
        frame["evidence"] = "DEMONSTRATION"

    return {
        "evidence": "DEMONSTRATION",
        "frames": frames,
        "max_t": float(duration_ms),
        "step_ms": step_ms,
        "topology": final_topo,
        "metrics_gg": metrics_gg,
        "metrics_edf": metrics_edf,
        "sim_gg_log": sim_gg.telemetry_log,
        "sim_edf_log": sim_edf.telemetry_log,
        "tasks_gg": tasks_gg,
        "tasks_edf": tasks_edf,
        "duration_ms": duration_ms,
        "params": {
            "fault_time_ms": fault_time_ms,
            "contention_magnitude": contention_magnitude,
            "channel_jitter_ms": channel_jitter_ms,
            "target_node": target_node,
            "fleet_size": fleet_size
        }
    }
