"""Calibration and operating-point tools for observed binary outcomes."""

from dataclasses import dataclass
from math import exp, isfinite, log


def expected_calibration_error(probabilities, outcomes, bins=10):
    """Return weighted absolute confidence-frequency gap over equal-width bins.

    The result is an empirical metric. It is meaningful only for held-out
    observations with labels generated after the decision timestamp.
    """
    probabilities = list(probabilities)
    outcomes = list(outcomes)
    if len(probabilities) != len(outcomes) or not probabilities:
        raise ValueError("non-empty equally sized probability and outcome arrays required")
    if isinstance(bins, bool) or not isinstance(bins, int) or bins < 1:
        raise ValueError("bins must be a positive integer")
    counts = [0] * bins
    sums_p = [0.0] * bins
    sums_y = [0] * bins
    for p, y in zip(probabilities, outcomes):
        if not isinstance(p, (int, float)) or not isfinite(p) or not 0 <= p <= 1:
            raise ValueError("probabilities must be finite in [0, 1]")
        if y not in (0, 1) or isinstance(y, bool):
            raise ValueError("outcomes must be binary integers")
        index = min(bins - 1, int(p * bins))
        counts[index] += 1
        sums_p[index] += p
        sums_y[index] += y
    n = len(probabilities)
    return sum(abs(sums_p[i] - sums_y[i]) for i in range(bins)) / n


def brier_score(probabilities, outcomes):
    probabilities, outcomes = _validate_observations(probabilities, outcomes)
    return sum((probability - outcome) ** 2 for probability, outcome in zip(probabilities, outcomes)) / len(outcomes)


def _validate_observations(probabilities, outcomes):
    probabilities = list(probabilities)
    outcomes = list(outcomes)
    if len(probabilities) != len(outcomes) or not probabilities:
        raise ValueError("non-empty equally sized probability and outcome arrays required")
    if any(not isinstance(p, (int, float)) or not isfinite(p) or not 0 <= p <= 1 for p in probabilities):
        raise ValueError("probabilities must be finite in [0, 1]")
    if any(y not in (0, 1) or isinstance(y, bool) for y in outcomes):
        raise ValueError("outcomes must be binary integers")
    return probabilities, outcomes


@dataclass(frozen=True)
class TemperatureCalibrator:
    """One-parameter probability calibrator selected on validation data."""

    temperature: float = 1.0

    def __post_init__(self):
        if isinstance(self.temperature, bool) or not isinstance(self.temperature, (int, float)) or not isfinite(self.temperature) or self.temperature <= 0:
            raise ValueError("temperature must be finite and positive")

    def apply(self, probability: float) -> float:
        if not 0 <= probability <= 1:
            raise ValueError("probability must be in [0, 1]")
        clipped = min(1.0 - 1e-7, max(1e-7, probability))
        logit = log(clipped / (1.0 - clipped)) / self.temperature
        # Evaluate the sigmoid on the side with a non-positive exponent.
        # Very small positive temperatures may legitimately saturate it.
        if logit >= 0:
            return 1.0 / (1.0 + exp(-logit))
        exponent = exp(logit)
        return exponent / (1.0 + exponent)

    @classmethod
    def fit(cls, probabilities, outcomes) -> "TemperatureCalibrator":
        probabilities, outcomes = _validate_observations(probabilities, outcomes)
        if len(set(outcomes)) < 2:
            return cls(1.0)
        candidates = [0.25 + index * 0.025 for index in range(151)]

        def log_loss(temperature: float) -> float:
            calibration = cls(temperature)
            calibrated = [calibration.apply(value) for value in probabilities]
            return -sum(
                outcome * log(max(value, 1e-12))
                + (1 - outcome) * log(max(1 - value, 1e-12))
                for value, outcome in zip(calibrated, outcomes)
            ) / len(outcomes)

        return cls(min(candidates, key=lambda value: (log_loss(value), value)))


def select_f1_threshold(probabilities, outcomes) -> float:
    """Choose an operating threshold from validation observations only."""
    probabilities, outcomes = _validate_observations(probabilities, outcomes)
    candidates = sorted(set([0.0, 1.0, *probabilities]))
    best = (float("-inf"), float("-inf"), 0.5)
    for threshold in candidates:
        predicted = [value >= threshold for value in probabilities]
        true_positive = sum(pred and outcome == 1 for pred, outcome in zip(predicted, outcomes))
        false_positive = sum(pred and outcome == 0 for pred, outcome in zip(predicted, outcomes))
        false_negative = sum(not pred and outcome == 1 for pred, outcome in zip(predicted, outcomes))
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        candidate = (f1, recall, -threshold)
        if candidate > best:
            best = candidate
    return -best[2]
