"""
Integration tests for GhostGuard REST API v1 endpoints.
Validates immutable run lifecycle, canonical event querying, frame retrieval,
policy comparison, model inspection, and timing certificates.
"""

import pytest
from ghostguard.api.server import (
    health,
    get_models,
    create_run,
    get_run,
    get_run_events,
    get_run_frames,
    get_run_metrics,
    compare_policies,
    get_verification_certificate,
    RunCreateRequest,
    CompareRequest,
)


def test_api_v1_health():
    res = health()
    assert res["status"] == "ok"
    assert res["service"] == "ghostguard-api"


def test_api_v1_models():
    data = get_models()
    assert "predictor" in data
    assert "federated" in data
    assert data["predictor"]["model_version"] == "gnn-1.0.0"
    assert data["predictor"]["evidence"] == "MEASURED"


def test_api_v1_create_and_query_run():
    # 1. Create Run
    req = RunCreateRequest(
        policy="ghostguard",
        scenario_type="bursty",
        seed=42,
        duration_ms=50.0,
        fleet_size=2,
        contention=0.90,
        fault_time_ms=20.0,
        jitter_ms=5.0,
    )
    run_meta = create_run(req)
    assert "run_id" in run_meta
    assert run_meta["status"] == "completed"
    assert run_meta["event_count"] > 0
    run_id = run_meta["run_id"]

    # 2. Get Run Detail
    run_data = get_run(run_id)
    assert run_data["run_id"] == run_id
    assert run_data["policy"] == "ghostguard"
    assert "manifest" in run_data

    # 3. Query Events (paginated)
    events_data = get_run_events(run_id, limit=10)
    assert "events" in events_data
    assert len(events_data["events"]) <= 10
    if len(events_data["events"]) > 0:
        ev0 = events_data["events"][0]
        assert "timestamp_us" in ev0
        assert "event_type" in ev0

    # 4. Query Frames
    frames_data = get_run_frames(run_id)
    assert "frames" in frames_data
    assert len(frames_data["frames"]) > 0

    # 5. Query Metrics
    metrics_data = get_run_metrics(run_id)
    assert "critical_misses" in metrics_data
    assert "units" in metrics_data


def test_api_v1_compare():
    req = CompareRequest(
        policies=["ghostguard", "edf"],
        scenario_type="bursty",
        seed=42,
        duration_ms=40.0,
    )
    data = compare_policies(req)
    assert "comparisons" in data
    assert "ghostguard" in data["comparisons"]
    assert "edf" in data["comparisons"]


def test_api_v1_verification_certificate():
    data = get_verification_certificate("cfg_hash_test_123")
    assert "evidence" in data
    assert data["evidence"] == "ANALYTICAL"
    assert "SCHEDULABLE UNDER CERTIFICATE ASSUMPTIONS" in data["status"]
