"""Deterministic serialization primitives for GhostGuard domain contracts."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


def freeze_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """Return a recursively isolated, read-only mapping.

    Domain objects must not retain references to caller-owned dictionaries.  Lists
    are converted to tuples and nested dictionaries are wrapped as mapping proxies.
    """

    def freeze(item: Any) -> Any:
        if isinstance(item, Mapping):
            return MappingProxyType({str(key): freeze(val) for key, val in item.items()})
        if isinstance(item, (list, tuple)):
            return tuple(freeze(element) for element in item)
        if isinstance(item, (set, frozenset)):
            return tuple(sorted((freeze(element) for element in item), key=repr))
        return item

    if value is not None and not isinstance(value, Mapping):
        raise TypeError("value must be a mapping")
    return freeze({} if value is None else value)


def to_canonical_data(value: Any) -> Any:
    """Convert supported domain values into JSON-compatible canonical data."""

    if dataclasses.is_dataclass(value):
        return {
            field.name: to_canonical_data(getattr(value, field.name))
            for field in dataclasses.fields(value)
            if not field.name.startswith("_")
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): to_canonical_data(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [to_canonical_data(item) for item in value]
    if isinstance(value, (set, frozenset)):
        converted = [to_canonical_data(item) for item in value]
        return sorted(converted, key=lambda item: canonical_json(item))
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite floats cannot be canonically serialized")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Serialize without whitespace using stable key ordering and UTF-8 text."""

    return json.dumps(
        to_canonical_data(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_sha256(value: Any) -> str:
    """Return the SHA-256 digest of canonical UTF-8 JSON."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class CanonicalHashMixin:
    """Stable serialization and configuration hashing for immutable specs."""

    def to_dict(self) -> dict[str, Any]:
        data = to_canonical_data(self)
        if not isinstance(data, dict):  # pragma: no cover - mixin is for dataclasses
            raise TypeError("canonical domain object did not serialize to an object")
        return data

    def to_json(self) -> str:
        return canonical_json(self)

    @property
    def configuration_hash(self) -> str:
        return canonical_sha256(self)

    @property
    def config_hash(self) -> str:
        """Short spelling used by manifests and API contracts."""

        return self.configuration_hash
