"""
Integration tests for PredictiveRuntime REST API v1 endpoints.
Validates immutable run lifecycle, canonical event querying, frame retrieval,
policy comparison, model inspection, and timing certificates.
"""

import pytest
from fastapi import HTTPException
from rts_predictive.api.server import (
    health,
    get_models,
    create_run,
    get_run,
    get_run_events,
    get_run_frames,
    get_run_metrics,
    compare_policies,
    get_verification_certificate,
    analyze_verification,
    VerificationAnalyzeRequest,
    VerificationTaskRequest,
    RunCreateRequest,
    CompareRequest,
)


def test_api_v1_health():
    res = health()
    assert res["status"] == "ok"
    assert res["service"] == "rts_predictive-api"


def test_api_v1_models():
    data = get_models()
    assert "predictor" in data
    assert "federated" in data
    assert data["predictor"]["model_version"] == "rts_predictive.gnn-bundle/1"
    assert data["predictor"]["evidence"] == "SIMULATION_CALIBRATED"
    assert data["predictor"]["calibrated"] is True
    assert data["predictor"]["feature_schema"] == "hetero-task-resource/9-v2"
    assert data["predictor"]["measured_inference_latency_ms"] is None
    assert data["federated"]["evidence"] == "SIMULATION_EVALUATED"


def test_api_v1_analyzes_and_retrieves_bound_verification_certificate():
    certificate = analyze_verification(VerificationAnalyzeRequest(
        tasks=[
            VerificationTaskRequest(
                task_id="control", period_us=10_000, deadline_us=10_000,
                wcet_us=1_000, priority=2, overhead_us=100,
            ),
            VerificationTaskRequest(
                task_id="sense", period_us=20_000, deadline_us=20_000,
                wcet_us=2_000, priority=1, jitter_us=100,
            ),
        ],
        scenario_hash="scenario-test",
        scheduler_config_hash="fp-test",
        hardware_profile_hash="hardware-test",
        resource_partition_id="cpu0",
        fallback_mode_id="fallback-test",
    ))
    assert certificate["status"] == "VERIFIED"
    assert certificate["results"]
    retrieved = get_verification_certificate(certificate["certificate_id"])
    assert retrieved["certificate_sha256"] == certificate["certificate_sha256"]


def test_api_v1_create_and_query_run():
    # 1. Create Run
    req = RunCreateRequest(
        policy="rts_predictive",
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
    assert run_data["policy"] == "rts_predictive"
    assert "manifest" in run_data
    assert len(run_data["manifest"]["event_sha256"]) == 64
    assert run_data["manifest"]["components"]["predictor"] == "gnn"
    assert run_data["manifest"]["components"]["remote_estimator"] == "federated"
    assert len(run_data["manifest"]["source_sha256"]) == 64

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
    assert frames_data["frames"][0]["nodes"]["Device_1"]["cpu"] is None

    # 5. Query Metrics
    metrics_data = get_run_metrics(run_id)
    assert "critical_misses" in metrics_data
    assert "units" in metrics_data


def test_api_v1_compare():
    req = CompareRequest(
        policies=["rts_predictive", "edf"],
        scenario_type="bursty",
        seed=42,
        duration_ms=40.0,
    )
    data = compare_policies(req)
    assert "comparisons" in data
    assert "rts_predictive" in data["comparisons"]
    assert "edf" in data["comparisons"]


def test_api_rejects_unsupported_scenarios_and_policies():
    with pytest.raises(HTTPException, match="Unknown scenario"):
        create_run(RunCreateRequest(scenario_type="not_a_scenario"))
    with pytest.raises(HTTPException, match="Unknown policy"):
        create_run(RunCreateRequest(policy="not_a_policy", duration_ms=10))
    with pytest.raises(HTTPException, match="Run-ID comparison"):
        compare_policies(CompareRequest(run_ids=["missing"]))


def test_api_v1_verification_certificate():
    with pytest.raises(HTTPException) as exc:
        get_verification_certificate("cfg_hash_test_123")
    assert exc.value.status_code == 404
