"""Replay frames derived from canonical events only.

The event stream currently has no utilization or temperature samples. Such
fields remain null instead of being filled with plausible-looking numbers.
"""

from __future__ import annotations

from typing import Any

from rts_predictive.config import HARDWARE_PROFILES, NODE_FLEET_DEFINITIONS


def reduce_events_to_frames(
    canonical_events: list[dict[str, Any]],
    duration_ms: float = 100.0,
    step_ms: float = 1.0,
    fleet_size: int = 4,
    device_states: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Produce replay snapshots without inferring unrecorded measurements."""
    if duration_ms < 0 or step_ms <= 0:
        raise ValueError("duration must be non-negative and step must be positive")
    ordered = sorted(canonical_events, key=lambda event: (
        event["timestamp_us"], event["sequence"],
    ))
    metadata = {}
    hardware_keys = list(HARDWARE_PROFILES)
    for index in range(fleet_size):
        dev_id = f"Device_{index + 1}"
        hardware = HARDWARE_PROFILES[hardware_keys[index % len(hardware_keys)]]
        role = (NODE_FLEET_DEFINITIONS[index]["role"]
                if index < len(NODE_FLEET_DEFINITIONS) else "Edge worker")
        metadata[dev_id] = {
            "id": dev_id, "name": f"Node {index + 1}: {hardware.name}",
            "role": role, "hardware": hardware.name,
            "x": 200 + (index % 2) * 400,
            "y": 120 + (index // 2) * 180,
        }

    released_critical: dict[str, bool] = {}
    completed: set[str] = set()
    missed: set[str] = set()
    fallback_tasks: set[str] = set()
    offloaded_tasks: set[str] = set()
    active_offloads: dict[str, dict[str, Any]] = {}
    contention: set[str] = set()
    resource_state: dict[str, dict[str, Any]] = {}
    latest: dict[str, Any] | None = None
    cursor = 0
    frames = []
    frame_count = int(duration_ms / step_ms) + 1

    for index in range(frame_count):
        timestamp_us = int(round(index * step_ms * 1000))
        while cursor < len(ordered) and ordered[cursor]["timestamp_us"] <= timestamp_us:
            event = ordered[cursor]
            latest = event
            kind = event["event_type"]
            task_id = event.get("task_id")
            dev_id = event.get("device_id")
            payload = event["payload"]
            if kind == "TASK_READY" and task_id:
                released_critical[task_id] = bool(payload.get("is_critical"))
            elif kind == "TASK_COMMIT" and task_id:
                completed.add(task_id)
                if payload.get("deadline_met") is False:
                    missed.add(task_id)
                active_offloads.pop(task_id, None)
            elif kind == "DEADLINE" and task_id:
                missed.add(task_id)
                active_offloads.pop(task_id, None)
            elif kind == "FALLBACK_TRIGGER" and task_id:
                fallback_tasks.add(task_id)
            elif kind == "OFFLOAD_DISPATCH" and task_id:
                offloaded_tasks.add(task_id)
                active_offloads[task_id] = {
                    "source": dev_id,
                    "target": payload.get("target_id"),
                    "packet_label": task_id,
                    "progress": None,
                    "color": "#8B5CF6",
                }
            elif kind in ("RESULT_TX_END", "LATE_RESULT_DISCARDED", "OFFLOAD_ABORT") and task_id:
                active_offloads.pop(task_id, None)
            elif kind == "FAULT_START" and dev_id:
                contention.add(dev_id)
            elif kind == "FAULT_END" and dev_id:
                contention.discard(dev_id)
            elif kind == "RESOURCE_SAMPLE" and dev_id:
                running = payload.get("running_tasks") or []
                resource_state[dev_id] = {
                    "cpu": payload.get("cpu_utilization"),
                    "gpu": payload.get("gpu_utilization"),
                    "temp_c": payload.get("temperature_c"),
                    "queue_len": payload.get("ready_queue_len"),
                    "active_task": running[0] if running else None,
                }
            cursor += 1

        active_offload = next(iter(active_offloads.values()), None)
        nodes = {}
        for dev_id, config in metadata.items():
            stressed = dev_id in contention
            sample = resource_state.get(dev_id, {})
            nodes[dev_id] = {
                **config,
                "cpu": sample.get("cpu"), "gpu": sample.get("gpu"),
                "temp_c": sample.get("temp_c"),
                "active_task": sample.get("active_task"),
                "queue_len": sample.get("queue_len"),
                "status": "CONTENDED" if stressed else "UNKNOWN",
                "is_overloaded": None,
                "fallback_active": None,
                "color": "#EF4444" if stressed else "#64748B",
            }

        links = []
        keys = list(metadata)
        for left_index, source in enumerate(keys):
            for target in keys[left_index + 1:]:
                active = any({item["source"], item["target"]} == {source, target}
                             for item in active_offloads.values())
                links.append({
                    "source": source, "target": target,
                    "latency_ms": None, "quality": "UNKNOWN",
                    "color": "#8B5CF6" if active else "#64748B",
                    "width": 3 if active else 1.5,
                })

        latest_kind = latest["event_type"] if latest else "NO_EVENT"
        latest_time = latest["timestamp_us"] / 1000 if latest else None
        status = "INTERCEPT_ABORT" if latest_kind == "OFFLOAD_ABORT" else (
            "MONITORING" if active_offloads else "IDLE"
        )
        frames.append({
            "t": timestamp_us / 1000,
            "evidence": "SIMULATED",
            "stage_id": None,
            "stage_name": latest_kind.replace("_", " ").title(),
            "stage_desc": (f"Latest recorded event at {latest_time:.3f} ms"
                           if latest_time is not None else "No event recorded yet"),
            "badge_color": "#EF4444" if latest_kind == "DEADLINE" else "#3B82F6",
            "channel_state": "UNKNOWN",
            "watchdog_status": status,
            "active_offload": active_offload,
            "nodes": nodes,
            "links": links,
            "dev1": {key: nodes.get("Device_1", {}).get(key) for key in
                     ("cpu", "gpu", "temp_c", "active_task", "status", "queue_len")},
            "dev2": {key: nodes.get("Device_2", {}).get(key) for key in
                     ("cpu", "gpu", "temp_c", "active_task", "status", "queue_len")},
            "gg_metrics": {
                "completed": len(completed),
                "missed": len(missed),
                "critical_misses": sum(released_critical.get(task_id, False)
                                       for task_id in missed),
                "fallbacks": len(fallback_tasks),
                "offloads": len(offloaded_tasks),
            },
        })
    return frames
