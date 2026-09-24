"""The research replay must not invent telemetry or narrated outcomes."""

from rts_predictive.dashboard.frame_reducer import reduce_events_to_frames


def test_event_frames_keep_unobserved_values_null_and_count_real_misses():
    events = [
        {"timestamp_us": 2_000, "sequence": 1, "event_type": "TASK_READY",
         "device_id": "Device_1", "task_id": "task-1",
         "payload": {"is_critical": True, "task_name": "Sense"}},
        {"timestamp_us": 3_000, "sequence": 2, "event_type": "DEADLINE",
         "device_id": "Device_1", "task_id": "task-1", "payload": {}},
    ]
    frames = reduce_events_to_frames(events, duration_ms=4, step_ms=1,
                                     fleet_size=2)
    assert frames[0]["stage_name"] == "No Event"
    assert frames[0]["nodes"]["Device_1"]["cpu"] is None
    assert frames[0]["links"][0]["latency_ms"] is None
    assert frames[2]["stage_name"] == "Task Ready"
    assert frames[3]["gg_metrics"]["missed"] == 1
    assert frames[3]["gg_metrics"]["critical_misses"] == 1
