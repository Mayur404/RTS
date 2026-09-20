"""Canonical JSONL event artifact contract, independent of domain code."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional

from ghostguard.artifacts.canonical import canonical_json_bytes


EVENT_SCHEMA_VERSION = "ghostguard.event/1.0"
EVENT_REQUIRED_FIELDS = frozenset({
    "schema_version", "run_id", "sequence", "timestamp_us", "event_type", "payload",
})
EVENT_OPTIONAL_FIELDS = frozenset({
    "device_id", "job_id", "task_id", "attempt_id", "decision_id", "caused_by_sequence",
})
EVENT_RESERVED_FIELDS = EVENT_REQUIRED_FIELDS | EVENT_OPTIONAL_FIELDS


class EventContractError(ValueError):
    """Raised for an invalid canonical event or JSONL stream."""


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_canonical_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return an ordinary dictionary for a canonical event."""

    if not isinstance(event, Mapping):
        raise EventContractError("event must be an object")
    keys = set(event)
    missing = EVENT_REQUIRED_FIELDS.difference(keys)
    unknown = keys.difference(EVENT_RESERVED_FIELDS)
    if missing:
        raise EventContractError(f"event is missing fields: {sorted(missing)}")
    if unknown:
        raise EventContractError(f"event has unknown top-level fields: {sorted(unknown)}")
    if event["schema_version"] != EVENT_SCHEMA_VERSION:
        raise EventContractError(f"unsupported event schema: {event['schema_version']!r}")
    if not isinstance(event["run_id"], str) or not event["run_id"].strip():
        raise EventContractError("run_id must be a non-empty string")
    if not _is_int(event["sequence"]) or event["sequence"] < 0:
        raise EventContractError("sequence must be a non-negative integer")
    if not _is_int(event["timestamp_us"]) or event["timestamp_us"] < 0:
        raise EventContractError("timestamp_us must be a non-negative integer")
    if not isinstance(event["event_type"], str) or not event["event_type"].strip():
        raise EventContractError("event_type must be a non-empty string")
    payload = event["payload"]
    if not isinstance(payload, Mapping):
        raise EventContractError("payload must be an object")
    collisions = EVENT_RESERVED_FIELDS.intersection(payload)
    if collisions:
        raise EventContractError(f"payload contains reserved fields: {sorted(collisions)}")
    for field_name in EVENT_OPTIONAL_FIELDS - {"caused_by_sequence"}:
        value = event.get(field_name)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise EventContractError(f"{field_name} must be null or a non-empty string")
    caused_by = event.get("caused_by_sequence")
    if caused_by is not None:
        if not _is_int(caused_by) or caused_by < 0:
            raise EventContractError("caused_by_sequence must be null or a non-negative integer")
        if caused_by >= event["sequence"]:
            raise EventContractError("caused_by_sequence must precede sequence")
    normalized = dict(event)
    normalized["payload"] = dict(payload)
    try:
        canonical_json_bytes(normalized)
    except ValueError as exc:
        raise EventContractError(str(exc)) from exc
    return normalized


class CanonicalEventWriter:
    """Write validated canonical events and hash the exact JSONL bytes."""

    def __init__(self, path: str | Path, run_id: str):
        if not isinstance(run_id, str) or not run_id.strip():
            raise EventContractError("writer run_id must be a non-empty string")
        self.path = Path(path)
        self.run_id = run_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = self.path.open("xb")
        self._digest = hashlib.sha256()
        self._last_sequence: Optional[int] = None
        self._last_time_us: Optional[int] = None
        self._count = 0
        self._closed = False

    @property
    def count(self) -> int:
        return self._count

    @property
    def sha256(self) -> str:
        return self._digest.hexdigest()

    def write(self, event: Mapping[str, Any]) -> None:
        if self._closed:
            raise EventContractError("cannot write to a closed event writer")
        normalized = validate_canonical_event(event)
        if normalized["run_id"] != self.run_id:
            raise EventContractError("event run_id does not match writer run_id")
        sequence = normalized["sequence"]
        timestamp_us = normalized["timestamp_us"]
        if self._last_sequence is not None and sequence <= self._last_sequence:
            raise EventContractError("event sequences must be strictly increasing")
        if self._last_time_us is not None and timestamp_us < self._last_time_us:
            raise EventContractError("event timestamp_us cannot move backward")
        line = canonical_json_bytes(normalized) + b"\n"
        self._stream.write(line)
        self._digest.update(line)
        self._last_sequence = sequence
        self._last_time_us = timestamp_us
        self._count += 1

    def close(self) -> None:
        if not self._closed:
            self._stream.flush()
            os.fsync(self._stream.fileno())
            self._stream.close()
            self._closed = True

    def __enter__(self) -> "CanonicalEventWriter":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


def iter_canonical_events(
    path: str | Path,
    *,
    expected_run_id: Optional[str] = None,
) -> Iterator[dict[str, Any]]:
    """Yield validated events while enforcing stream order and run identity."""

    last_sequence: Optional[int] = None
    last_time_us: Optional[int] = None
    stream_run_id = expected_run_id
    try:
        source = Path(path).open("r", encoding="utf-8", newline="")
    except OSError as exc:
        raise EventContractError(f"cannot read event artifact: {exc}") from exc
    with source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                raise EventContractError(f"blank event line at {line_number}")
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EventContractError(f"invalid JSON at event line {line_number}: {exc}") from exc
            try:
                event = validate_canonical_event(parsed)
            except EventContractError as exc:
                raise EventContractError(f"invalid event at line {line_number}: {exc}") from exc
            if stream_run_id is None:
                stream_run_id = event["run_id"]
            if event["run_id"] != stream_run_id:
                raise EventContractError(f"run_id changed at event line {line_number}")
            if last_sequence is not None and event["sequence"] <= last_sequence:
                raise EventContractError(f"sequence is not strictly increasing at line {line_number}")
            if last_time_us is not None and event["timestamp_us"] < last_time_us:
                raise EventContractError(f"timestamp_us moved backward at line {line_number}")
            last_sequence = event["sequence"]
            last_time_us = event["timestamp_us"]
            yield event
