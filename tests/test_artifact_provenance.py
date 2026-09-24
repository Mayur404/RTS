"""Contract tests for versioned manifests and canonical event artifacts."""

from __future__ import annotations

from dataclasses import replace

import pytest

from rts_predictive.artifacts import (
    EVENT_SCHEMA_VERSION,
    ArtifactIntegrityError,
    ArtifactRecord,
    CanonicalEventWriter,
    EnvironmentRecord,
    EventContractError,
    FailureRecord,
    GitRecord,
    ManifestValidationError,
    ModelRecord,
    PolicyRecord,
    RunManifest,
    RunStatus,
    ScenarioRecord,
    canonical_json_bytes,
    iter_canonical_events,
    read_manifest,
    sha256_canonical_json,
    sha256_file,
    write_manifest_atomic,
)


HASH_A = "a" * 64
HASH_B = "b" * 64


def make_manifest(**overrides):
    values = {
        "run_id": "run-001",
        "experiment_id": "experiment-smoke",
        "cell_id": "bursty-rts_predictive",
        "pair_id": "bursty-seed-42",
        "status": RunStatus.RUNNING,
        "created_at_utc": "2026-09-20T10:00:00+00:00",
        "completed_at_utc": None,
        "seed": 42,
        "rng_schema_version": "rng/1",
        "policy": PolicyRecord("rts_predictive", "1.0.0", HASH_A),
        "scenario": ScenarioRecord("rts_predictive.scenario/1.0", HASH_B),
        "model": ModelRecord(),
        "git": GitRecord("0123456789abcdef", True),
        "environment": EnvironmentRecord("3.12.4", HASH_A, "Windows-x86_64"),
        "command": ("python", "-m", "rts_predictive.experiments"),
    }
    values.update(overrides)
    return RunManifest(**values)


def make_event(sequence=0, timestamp_us=0, payload=None, **overrides):
    event = {
        "schema_version": EVENT_SCHEMA_VERSION,
        "run_id": "run-001",
        "sequence": sequence,
        "timestamp_us": timestamp_us,
        "event_type": "task_ready",
        "task_id": "task-1",
        "payload": payload or {"queue_depth": 2},
    }
    event.update(overrides)
    return event


def test_canonical_json_and_hash_are_order_independent():
    left = {"z": [3, {"beta": 2, "alpha": 1}], "a": "µs"}
    right = {"a": "µs", "z": [3, {"alpha": 1, "beta": 2}]}

    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert sha256_canonical_json(left) == sha256_canonical_json(right)
    with pytest.raises(ValueError, match="canonical-JSON"):
        canonical_json_bytes({"invalid": float("nan")})


def test_artifact_record_detects_tampering_and_unsafe_paths(tmp_path):
    artifact = tmp_path / "events.jsonl"
    artifact.write_bytes(b'{"event":"first"}\n')
    record = ArtifactRecord.from_path(tmp_path, "events.jsonl")
    record.verify(tmp_path)

    artifact.write_bytes(b'{"event":"tampered"}\n')
    with pytest.raises(ArtifactIntegrityError, match="mismatch"):
        record.verify(tmp_path)
    with pytest.raises(ArtifactIntegrityError, match="relative"):
        ArtifactRecord.from_path(tmp_path, "../outside.json")


def test_manifest_atomic_round_trip_and_artifact_validation(tmp_path):
    events_path = tmp_path / "events.jsonl"
    with CanonicalEventWriter(events_path, "run-001") as writer:
        writer.write(make_event())
        writer.write(make_event(sequence=1, timestamp_us=50, event_type="execution_start"))

    artifact = ArtifactRecord.from_path(tmp_path, "events.jsonl")
    manifest = make_manifest(
        status=RunStatus.COMPLETED,
        completed_at_utc="2026-09-20T10:00:01+00:00",
        artifacts=(artifact,),
    )
    manifest_path = tmp_path / "manifest.json"
    write_manifest_atomic(manifest_path, manifest)

    restored = read_manifest(manifest_path)
    assert restored == manifest
    assert manifest_path.read_bytes() == canonical_json_bytes(manifest.to_dict()) + b"\n"
    restored.validate_artifacts(tmp_path)


def test_event_jsonl_round_trip_hashes_canonical_uncompressed_bytes(tmp_path):
    path = tmp_path / "events.jsonl"
    events = [
        make_event(),
        make_event(
            sequence=1,
            timestamp_us=125,
            event_type="execution_start",
            caused_by_sequence=0,
            attempt_id="attempt-1",
        ),
    ]
    with CanonicalEventWriter(path, "run-001") as writer:
        for event in events:
            writer.write(event)
        digest = writer.sha256

    assert digest == sha256_file(path)
    assert list(iter_canonical_events(path, expected_run_id="run-001")) == events


def test_event_contract_protects_reserved_fields_and_stream_order(tmp_path):
    path = tmp_path / "events.jsonl"
    with CanonicalEventWriter(path, "run-001") as writer:
        with pytest.raises(EventContractError, match="reserved fields"):
            writer.write(make_event(payload={"run_id": "shadow"}))
        writer.write(make_event(sequence=2, timestamp_us=100))
        with pytest.raises(EventContractError, match="strictly increasing"):
            writer.write(make_event(sequence=2, timestamp_us=101))
        with pytest.raises(EventContractError, match="move backward"):
            writer.write(make_event(sequence=3, timestamp_us=99))

    with CanonicalEventWriter(tmp_path / "other.jsonl", "run-001") as writer:
        with pytest.raises(EventContractError, match="unknown top-level"):
            writer.write(make_event(unversioned_field=True))


def test_running_and_failed_manifests_preserve_lifecycle_state(tmp_path):
    running = make_manifest()
    path = tmp_path / "manifest.json"
    write_manifest_atomic(path, running)
    assert read_manifest(path).status == RunStatus.RUNNING
    assert read_manifest(path).completed_at_utc is None
    assert read_manifest(path).failure is None

    failed = replace(
        running,
        status=RunStatus.FAILED,
        completed_at_utc="2026-09-20T10:00:05Z",
        failure=FailureRecord("SIMULATION_ERROR", "event loop failed", {"sequence": 17}),
    )
    write_manifest_atomic(path, failed)
    restored = read_manifest(path)
    assert restored.status == RunStatus.FAILED
    assert restored.failure == failed.failure

    with pytest.raises(ManifestValidationError, match="failure record"):
        replace(running, status=RunStatus.FAILED, completed_at_utc="2026-09-20T10:00:05Z")
