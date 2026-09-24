"""Deterministic descriptive and paired uncertainty summaries."""

from __future__ import annotations

import random
from statistics import mean
from typing import Iterable


def bootstrap_mean_ci(
    values: Iterable[float], confidence: float = 0.95, resamples: int = 2000, seed: int = 0
) -> dict[str, float | int | None]:
    observations = [float(value) for value in values]
    if not observations:
        raise ValueError("at least one observation is required")
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
