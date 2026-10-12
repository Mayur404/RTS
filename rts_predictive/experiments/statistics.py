"""Deterministic descriptive and paired uncertainty summaries."""

from __future__ import annotations

import random
from math import isfinite
from statistics import mean
from typing import Iterable


def bootstrap_mean_ci(
    values: Iterable[float], confidence: float = 0.95, resamples: int = 2000, seed: int = 0
) -> dict[str, float | int | None]:
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not isfinite(confidence) or not 0 < confidence < 1:
        raise ValueError("confidence must be finite and strictly between 0 and 1")
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples < 1:
        raise ValueError("resamples must be a positive integer")
    observations = [float(value) for value in values]
    if not observations:
        raise ValueError("at least one observation is required")
    if not all(isfinite(value) for value in observations):
        raise ValueError("observations must be finite")
    estimate = mean(observations)
    if len(observations) < 2:
        return {"mean": estimate, "lower": None, "upper": None, "n": len(observations)}
    rng = random.Random(seed)
    boot = sorted(
        mean(rng.choices(observations, k=len(observations)))
        for _ in range(resamples)
    )
    alpha = (1.0 - confidence) / 2.0
    lower_index = max(0, int(alpha * resamples))
    upper_index = min(resamples - 1, int((1.0 - alpha) * resamples) - 1)
    return {
        "mean": estimate,
        "lower": boot[lower_index],
        "upper": boot[upper_index],
        "n": len(observations),
    }
