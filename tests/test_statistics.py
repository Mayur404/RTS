from rts_predictive.experiments.statistics import bootstrap_mean_ci


def test_bootstrap_interval_is_deterministic_and_does_not_invent_single_run_variance():
    single = bootstrap_mean_ci([0.2])
    assert single == {"mean": 0.2, "lower": None, "upper": None, "n": 1}

    first = bootstrap_mean_ci([0.1, 0.2, 0.4], seed=7, resamples=200)
    second = bootstrap_mean_ci([0.1, 0.2, 0.4], seed=7, resamples=200)
    assert first == second
    assert first["lower"] <= first["mean"] <= first["upper"]
