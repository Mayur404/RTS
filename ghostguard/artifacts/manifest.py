"""Run-manifest schema and checksum validation for research artifacts."""

from __future__ import annotations

import hmac
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Optional, Sequence, Tuple

from ghostguard.artifacts.canonical import canonical_json_bytes, sha256_file


RUN_MANIFEST_SCHEMA_VERSION = "ghostguard.run-manifest/1.0"
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class ManifestValidationError(ValueError):
    """Raised when a manifest does not satisfy its versioned contract."""


class ArtifactIntegrityError(ValueError):
    """Raised when an artifact is missing, unsafe, or fails validation."""


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {
            RunStatus.COMPLETED,
            RunStatus.PARTIAL,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }


def utc_now_iso() -> str:
    """Return an ISO-8601 UTC timestamp suitable for a manifest."""

    return datetime.now(timezone.utc).isoformat()


def _require_nonempty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ManifestValidationError(f"{field_name} must be a non-empty string")


def _require_sha256(value: str, field_name: str) -> None:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ManifestValidationError(f"{field_name} must be a lowercase SHA-256 digest")


def _require_utc_timestamp(value: str, field_name: str) -> datetime:
    _require_nonempty(value, field_name)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ManifestValidationError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ManifestValidationError(f"{field_name} must include a UTC offset")
    return parsed


def _expect_keys(
    data: Mapping[str, Any],
    required: set[str],
    optional: set[str] = frozenset(),
    *,
    context: str,
) -> None:
    missing = required.difference(data)
    unknown = set(data).difference(required | optional)
    if missing:
        raise ManifestValidationError(f"{context} is missing fields: {sorted(missing)}")
    if unknown:
        raise ManifestValidationError(f"{context} has unknown fields: {sorted(unknown)}")


def _validated_relative_path(path: str) -> PurePosixPath:
    _require_nonempty(path, "artifact.path")
    relative = PurePosixPath(path)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or "." in relative.parts
        or "\\" in path
        or relative.as_posix() != path
    ):
        raise ArtifactIntegrityError("artifact path must be a normalized relative POSIX path")
    return relative


def _resolve_artifact(root: str | Path, relative_path: str) -> Path:
    relative = _validated_relative_path(relative_path)
    root_path = Path(root).resolve()
    target = root_path.joinpath(*relative.parts).resolve()
    try:
        target.relative_to(root_path)
    except ValueError as exc:
        raise ArtifactIntegrityError("artifact path resolves outside its run directory") from exc
    return target


@dataclass(frozen=True)
class PolicyRecord:
    name: str
    version: str
    config_hash: str

    def __post_init__(self) -> None:
        _require_nonempty(self.name, "policy.name")
        _require_nonempty(self.version, "policy.version")
        _require_sha256(self.config_hash, "policy.config_hash")

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "version": self.version, "config_hash": self.config_hash}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PolicyRecord":
        _expect_keys(data, {"name", "version", "config_hash"}, context="policy")
        return cls(name=data["name"], version=data["version"], config_hash=data["config_hash"])


@dataclass(frozen=True)
class ScenarioRecord:
    schema_version: str
    sha256: str

    def __post_init__(self) -> None:
        _require_nonempty(self.schema_version, "scenario.schema_version")
        _require_sha256(self.sha256, "scenario.sha256")

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "sha256": self.sha256}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ScenarioRecord":
        _expect_keys(data, {"schema_version", "sha256"}, context="scenario")
        return cls(schema_version=data["schema_version"], sha256=data["sha256"])


@dataclass(frozen=True)
class ModelRecord:
    bundle_id: Optional[str] = None
    sha256: Optional[str] = None

    def __post_init__(self) -> None:
        if self.bundle_id is not None:
            _require_nonempty(self.bundle_id, "model.bundle_id")
        if self.sha256 is not None:
            _require_sha256(self.sha256, "model.sha256")
        if (self.bundle_id is None) != (self.sha256 is None):
            raise ManifestValidationError("model.bundle_id and model.sha256 must both be set or both be null")

    def to_dict(self) -> dict[str, Any]:
        return {"bundle_id": self.bundle_id, "sha256": self.sha256}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ModelRecord":
        _expect_keys(data, {"bundle_id", "sha256"}, context="model")
        return cls(bundle_id=data["bundle_id"], sha256=data["sha256"])


@dataclass(frozen=True)
class GitRecord:
    commit: str
    dirty: bool

    def __post_init__(self) -> None:
        _require_nonempty(self.commit, "git.commit")
        if not isinstance(self.dirty, bool):
            raise ManifestValidationError("git.dirty must be a boolean")

    def to_dict(self) -> dict[str, Any]:
        return {"commit": self.commit, "dirty": self.dirty}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GitRecord":
        _expect_keys(data, {"commit", "dirty"}, context="git")
        return cls(commit=data["commit"], dirty=data["dirty"])


@dataclass(frozen=True)
class EnvironmentRecord:
    python: str
    dependencies_sha256: str
    platform: str

    def __post_init__(self) -> None:
        _require_nonempty(self.python, "environment.python")
        _require_sha256(self.dependencies_sha256, "environment.dependencies_sha256")
        _require_nonempty(self.platform, "environment.platform")

    def to_dict(self) -> dict[str, Any]:
        return {
            "python": self.python,
            "dependencies_sha256": self.dependencies_sha256,
            "platform": self.platform,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EnvironmentRecord":
        _expect_keys(data, {"python", "dependencies_sha256", "platform"}, context="environment")
        return cls(
            python=data["python"],
            dependencies_sha256=data["dependencies_sha256"],
            platform=data["platform"],
        )


@dataclass(frozen=True)
class FailureRecord:
    code: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_nonempty(self.code, "failure.code")
        _require_nonempty(self.message, "failure.message")
        if not isinstance(self.details, Mapping):
            raise ManifestValidationError("failure.details must be an object")
        canonical_json_bytes(dict(self.details))

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": dict(self.details)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FailureRecord":
        _expect_keys(data, {"code", "message", "details"}, context="failure")
        return cls(code=data["code"], message=data["message"], details=data["details"])


@dataclass(frozen=True)
class ArtifactRecord:
    path: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        _validated_relative_path(self.path)
        _require_sha256(self.sha256, "artifact.sha256")
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int) or self.size_bytes < 0:
            raise ManifestValidationError("artifact.size_bytes must be a non-negative integer")

    @classmethod
    def from_path(cls, root: str | Path, relative_path: str) -> "ArtifactRecord":
        target = _resolve_artifact(root, relative_path)
        if not target.is_file():
            raise ArtifactIntegrityError(f"artifact does not exist: {relative_path}")
        return cls(path=relative_path, sha256=sha256_file(target), size_bytes=target.stat().st_size)

    def verify(self, root: str | Path) -> None:
        target = _resolve_artifact(root, self.path)
        if not target.is_file():
            raise ArtifactIntegrityError(f"artifact does not exist: {self.path}")
        actual_size = target.stat().st_size
        if actual_size != self.size_bytes:
            raise ArtifactIntegrityError(
                f"artifact size mismatch for {self.path}: expected {self.size_bytes}, got {actual_size}"
            )
        actual_digest = sha256_file(target)
        if not hmac.compare_digest(actual_digest, self.sha256):
            raise ArtifactIntegrityError(f"artifact checksum mismatch for {self.path}")

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "size_bytes": self.size_bytes}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ArtifactRecord":
        _expect_keys(data, {"path", "sha256", "size_bytes"}, context="artifact")
        return cls(path=data["path"], sha256=data["sha256"], size_bytes=data["size_bytes"])


@dataclass(frozen=True)
class RunManifest:
    run_id: str
    experiment_id: str
    cell_id: Optional[str]
    pair_id: Optional[str]
    status: RunStatus
    created_at_utc: str
    completed_at_utc: Optional[str]
    seed: int
    rng_schema_version: str
    policy: PolicyRecord
    scenario: ScenarioRecord
    model: ModelRecord
    git: GitRecord
    environment: EnvironmentRecord
    command: Tuple[str, ...]
    artifacts: Tuple[ArtifactRecord, ...] = ()
    failure: Optional[FailureRecord] = None
    schema_version: str = RUN_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RUN_MANIFEST_SCHEMA_VERSION:
            raise ManifestValidationError(f"unsupported manifest schema: {self.schema_version}")
        _require_nonempty(self.run_id, "run_id")
        _require_nonempty(self.experiment_id, "experiment_id")
        for field_name, value in (("cell_id", self.cell_id), ("pair_id", self.pair_id)):
            if value is not None:
                _require_nonempty(value, field_name)
        if not isinstance(self.status, RunStatus):
            raise ManifestValidationError("status must be a RunStatus")
        created = _require_utc_timestamp(self.created_at_utc, "created_at_utc")
        completed = None
        if self.completed_at_utc is not None:
            completed = _require_utc_timestamp(self.completed_at_utc, "completed_at_utc")
            if completed < created:
                raise ManifestValidationError("completed_at_utc cannot precede created_at_utc")
        if self.status.is_terminal and completed is None:
            raise ManifestValidationError("terminal runs require completed_at_utc")
        if not self.status.is_terminal and completed is not None:
            raise ManifestValidationError("non-terminal runs cannot have completed_at_utc")
        if self.status == RunStatus.FAILED and self.failure is None:
            raise ManifestValidationError("failed runs require a failure record")
        if self.status != RunStatus.FAILED and self.failure is not None:
            raise ManifestValidationError("only failed runs may include a failure record")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ManifestValidationError("seed must be an integer")
        _require_nonempty(self.rng_schema_version, "rng_schema_version")
        nested_records = (
            ("policy", self.policy, PolicyRecord),
            ("scenario", self.scenario, ScenarioRecord),
            ("model", self.model, ModelRecord),
            ("git", self.git, GitRecord),
            ("environment", self.environment, EnvironmentRecord),
        )
        for field_name, value, expected_type in nested_records:
            if not isinstance(value, expected_type):
                raise ManifestValidationError(f"{field_name} must be a {expected_type.__name__}")
        if not isinstance(self.command, tuple) or not self.command:
            raise ManifestValidationError("command must be a non-empty tuple")
        for index, item in enumerate(self.command):
            _require_nonempty(item, f"command[{index}]")
        if not isinstance(self.artifacts, tuple):
            raise ManifestValidationError("artifacts must be a tuple")
        if any(not isinstance(record, ArtifactRecord) for record in self.artifacts):
            raise ManifestValidationError("artifacts must contain only ArtifactRecord values")
        paths = [record.path for record in self.artifacts]
        if len(paths) != len(set(paths)):
            raise ManifestValidationError("artifact paths must be unique")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "experiment_id": self.experiment_id,
            "cell_id": self.cell_id,
            "pair_id": self.pair_id,
            "status": self.status.value,
            "created_at_utc": self.created_at_utc,
            "completed_at_utc": self.completed_at_utc,
            "seed": self.seed,
            "rng_schema_version": self.rng_schema_version,
            "policy": self.policy.to_dict(),
            "scenario": self.scenario.to_dict(),
            "model": self.model.to_dict(),
            "git": self.git.to_dict(),
            "environment": self.environment.to_dict(),
            "command": list(self.command),
            "artifacts": [record.to_dict() for record in self.artifacts],
            "failure": self.failure.to_dict() if self.failure is not None else None,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RunManifest":
        required = {
            "schema_version", "run_id", "experiment_id", "cell_id", "pair_id", "status",
            "created_at_utc", "completed_at_utc", "seed", "rng_schema_version", "policy",
            "scenario", "model", "git", "environment", "command", "artifacts", "failure",
        }
        _expect_keys(data, required, context="manifest")
        try:
            status = RunStatus(data["status"])
        except (TypeError, ValueError) as exc:
            raise ManifestValidationError(f"unknown run status: {data['status']!r}") from exc
        command = data["command"]
        artifacts = data["artifacts"]
        if not isinstance(command, Sequence) or isinstance(command, (str, bytes)):
            raise ManifestValidationError("command must be an array of strings")
        if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes)):
            raise ManifestValidationError("artifacts must be an array")
        failure_data = data["failure"]
        return cls(
            schema_version=data["schema_version"],
            run_id=data["run_id"],
            experiment_id=data["experiment_id"],
            cell_id=data["cell_id"],
            pair_id=data["pair_id"],
            status=status,
            created_at_utc=data["created_at_utc"],
            completed_at_utc=data["completed_at_utc"],
            seed=data["seed"],
            rng_schema_version=data["rng_schema_version"],
            policy=PolicyRecord.from_dict(data["policy"]),
            scenario=ScenarioRecord.from_dict(data["scenario"]),
            model=ModelRecord.from_dict(data["model"]),
            git=GitRecord.from_dict(data["git"]),
            environment=EnvironmentRecord.from_dict(data["environment"]),
            command=tuple(command),
            artifacts=tuple(ArtifactRecord.from_dict(item) for item in artifacts),
            failure=FailureRecord.from_dict(failure_data) if failure_data is not None else None,
        )

    def validate_artifacts(self, root: str | Path) -> None:
        for record in self.artifacts:
            record.verify(root)


def write_manifest_atomic(path: str | Path, manifest: RunManifest) -> None:
    """Atomically replace *path* with a canonical manifest document."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(manifest.to_dict()) + b"\n"
    temporary_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{target.name}.", suffix=".tmp", dir=target.parent, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, target)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def read_manifest(path: str | Path) -> RunManifest:
    """Read and validate a versioned manifest."""

    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestValidationError(f"cannot read manifest: {exc}") from exc
    if not isinstance(data, Mapping):
        raise ManifestValidationError("manifest root must be an object")
    return RunManifest.from_dict(data)
