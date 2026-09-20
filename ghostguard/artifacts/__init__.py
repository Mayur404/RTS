"""Versioned, simulator-independent research artifact contracts."""

from ghostguard.artifacts.canonical import (
    canonical_json_bytes,
    sha256_bytes,
    sha256_canonical_json,
    sha256_file,
)
from ghostguard.artifacts.events import (
    EVENT_SCHEMA_VERSION,
    CanonicalEventWriter,
    EventContractError,
    iter_canonical_events,
    validate_canonical_event,
)
from ghostguard.artifacts.manifest import (
    RUN_MANIFEST_SCHEMA_VERSION,
    ArtifactIntegrityError,
    ArtifactRecord,
    EnvironmentRecord,
    FailureRecord,
    GitRecord,
    ManifestValidationError,
    ModelRecord,
    PolicyRecord,
    RunManifest,
    RunStatus,
    ScenarioRecord,
    read_manifest,
    utc_now_iso,
    write_manifest_atomic,
)

__all__ = [
    "EVENT_SCHEMA_VERSION",
    "RUN_MANIFEST_SCHEMA_VERSION",
    "ArtifactIntegrityError",
    "ArtifactRecord",
    "CanonicalEventWriter",
    "EnvironmentRecord",
    "EventContractError",
    "FailureRecord",
    "GitRecord",
    "ManifestValidationError",
    "ModelRecord",
    "PolicyRecord",
    "RunManifest",
    "RunStatus",
    "ScenarioRecord",
    "canonical_json_bytes",
    "iter_canonical_events",
    "read_manifest",
    "sha256_bytes",
    "sha256_canonical_json",
    "sha256_file",
    "utc_now_iso",
    "validate_canonical_event",
    "write_manifest_atomic",
]
