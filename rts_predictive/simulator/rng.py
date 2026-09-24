"""Versioned, domain-separated pseudo-random streams for reproducible runs."""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field


RNG_SCHEMA_VERSION = "rts_predictive.rng/1"
DEFAULT_STREAM_NAMES = (
    "release_jitter",
    "execution_time",
    "network_loss",
    "network_latency",
    "fault_injection",
)


def derive_stream_seed(root_seed: int, stream_name: str) -> int:
    """Derive a stable seed without depending on Python's randomized hash()."""
    material = f"{RNG_SCHEMA_VERSION}\0{root_seed}\0{stream_name}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:16], "big")


@dataclass
class NamedRandomStreams:
    root_seed: int
    _streams: dict[str, random.Random] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        if isinstance(self.root_seed, bool) or not isinstance(self.root_seed, int):
            raise TypeError("root_seed must be an integer")
        if self.root_seed < 0:
            raise ValueError("root_seed must be non-negative")
        for name in DEFAULT_STREAM_NAMES:
            self._streams[name] = random.Random(derive_stream_seed(self.root_seed, name))

    def stream(self, name: str) -> random.Random:
        if not name or not isinstance(name, str):
            raise ValueError("stream name must be a non-empty string")
        if name not in self._streams:
            self._streams[name] = random.Random(derive_stream_seed(self.root_seed, name))
        return self._streams[name]

    def provenance(self) -> dict[str, object]:
        return {
            "schema_version": RNG_SCHEMA_VERSION,
            "root_seed": self.root_seed,
            "stream_seeds": {
                name: derive_stream_seed(self.root_seed, name)
                for name in sorted(self._streams)
            },
        }
