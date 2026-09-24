import pytest

from rts_predictive.gnn.calibration import (
    TemperatureCalibrator,
    brier_score,
    expected_calibration_error,
    select_f1_threshold,
)


def test_ece_uses_observed_bin_frequency_and_sample_weight():
    assert expected_calibration_error([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1], bins=2) == pytest.approx(0.15)
    assert expected_calibration_error([0.0, 1.0], [0, 1], bins=10) == 0.0


def test_ece_rejects_invalid_evidence():
    with pytest.raises(ValueError):
        expected_calibration_error([0.5], [])
    with pytest.raises(ValueError):
        expected_calibration_error([float("nan")], [1])


def test_temperature_calibration_and_threshold_are_validation_derived():
    probabilities = [0.1, 0.35, 0.65, 0.9]
    outcomes = [0, 0, 1, 1]
    calibrator = TemperatureCalibrator.fit(probabilities, outcomes)
    calibrated = [calibrator.apply(value) for value in probabilities]

    assert calibrator.temperature > 0
    assert brier_score(calibrated, outcomes) <= brier_score([0.5] * 4, outcomes)
    assert 0 <= select_f1_threshold(calibrated, outcomes) <= 1
