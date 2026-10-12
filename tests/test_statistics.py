from rts_predictive.experiments.statistics import bootstrap_mean_ci
import pytest


def test_bootstrap_interval_is_deterministic_and_does_not_invent_single_run_variance():
    single = bootstrap_mean_ci([0.2])
    assert single == {"mean": 0.2, "lower": None, "upper": None, "n": 1}

    first = bootstrap_mean_ci([0.1, 0.2, 0.4], seed=7, resamples=200)
    second = bootstrap_mean_ci([0.1, 0.2, 0.4], seed=7, resamples=200)
    assert first == second
    assert first["lower"] <= first["mean"] <= first["upper"]


@pytest.mark.parametrize("confidence", [0, 1, -0.1, 1.1, float("nan"), float("inf"), True])
def test_bootstrap_rejects_invalid_confidence_even_for_single_observation(confidence):
    with pytest.raises(ValueError, match="confidence"):
        bootstrap_mean_ci([0.2], confidence=confidence)


@pytest.mark.parametrize("resamples", [0, -1, 2.5, True])
def test_bootstrap_rejects_invalid_resampling_count(resamples):
    with pytest.raises(ValueError, match="resamples"):
        bootstrap_mean_ci([0.1, 0.2], resamples=resamples)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_bootstrap_rejects_nonfinite_evidence(value):
    with pytest.raises(ValueError, match="finite"):
        bootstrap_mean_ci([value])
