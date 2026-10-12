"""Read-only live projections; no scheduling or synthetic observations."""

from __future__ import annotations


def live_statistics(events, critical_names=()):
    """Reduce outcomes in the retained event window (pending tasks are censored).

    A commit and deadline for the same task count as one evaluated outcome.
    Response times are task response times, never pipeline response times.
    """
    commits, misses, critical = {}, set(), set()
    released = set()
    offloads = fallbacks = 0
    for event in events:
        kind, task_id, payload = event["event_type"], event.get("task_id"), event["payload"]
        if kind == "TASK_READY" and task_id:
            released.add(task_id)
        if task_id and (payload.get("is_critical") or payload.get("task_name") in critical_names):
            critical.add(task_id)
        if kind == "TASK_COMMIT" and task_id:
            commits[task_id] = payload
            if payload.get("deadline_met") is False:
                misses.add(task_id)
        if kind == "DEADLINE" and task_id:
            misses.add(task_id)
        offloads += kind == "OFFLOAD_DISPATCH"
        fallbacks += kind in ("FALLBACK_TRIGGER", "OFFLOAD_ABORT")
    evaluated = set(commits) | misses
    timely = set(commits) - misses
    responses = [p["response_time_ms"] for p in commits.values()
                 if p.get("response_time_ms") is not None]
    utilities = [commits[t].get("output_utility", 1.0) for t in timely]
    return {
        "completed": len(timely), "missed": len(misses),
        "critical_misses": len(misses & critical), "evaluated": len(evaluated),
        "pending": len(released - evaluated),
        "wcrt_ms": max(responses) if responses else None,
        "offloads": offloads, "fallbacks": fallbacks,
        "dmr_pct": 100 * len(misses) / len(evaluated) if evaluated else None,
        "avg_utility": sum(utilities) / len(utilities) if utilities else None,
        "scope": "retained_event_window", "evidence": "LIVE_NON_EVIDENCE",
    }


def resource_dependency_graph(sim):
    """Project actual admitted tasks and their CPU/GPU demands.

    Allocation edges mean running; demand edges mean queued. These are
    contention relationships, not deadlock or physical motion claims.
    """
    resources, tasks, edges = [], [], []
    for device_id, device in sim.devices.items():
        for kind, utilization in (
            ("CPU", device.resources.get_effective_cpu_utilization()),
            ("GPU", device.resources.get_effective_gpu_utilization()),
        ):
            resources.append({"id": f"{device_id}:{kind}", "device_id": device_id,
                              "kind": kind, "utilization": utilization})
        for status, members in (("RUNNING", device.running_tasks), ("QUEUED", device.ready_queue)):
            for task in members:
                tasks.append({"id": task.instance_id, "name": task.task_name,
                              "device_id": device_id, "origin_device_id": task.origin_device_id,
                              "job_id": task.pipeline_job_id, "state": status,
                              "deadline_ms": task.deadline_ms,
                              "remaining_work_ms": max(0.0, task.remaining_work_ms),
                              "degraded": task.is_degraded})
                for kind, demand in (("CPU", task.cpu_util_fraction), ("GPU", task.gpu_util_fraction)):
                    if demand > 0:
                        edges.append({"source": task.instance_id, "target": f"{device_id}:{kind}",
                                      "kind": "allocation" if status == "RUNNING" else "demand",
                                      "demand_fraction": demand})
    return {"schema_version": "rts_predictive.live-resource-graph/1.0",
            "resources": resources, "tasks": tasks, "edges": edges,
            "evidence": "LIVE_NON_EVIDENCE"}
