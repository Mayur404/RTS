from rts_predictive.simulator.rng import (
    RNG_SCHEMA_VERSION,
    NamedRandomStreams,
    derive_stream_seed,
)


def test_named_streams_replay_exactly_for_same_root_seed():
    first = NamedRandomStreams(42)
    second = NamedRandomStreams(42)

    assert [first.stream("network_loss").random() for _ in range(5)] == [
        second.stream("network_loss").random() for _ in range(5)
    ]


def test_draws_from_one_domain_do_not_perturb_another_domain():
    baseline = NamedRandomStreams(7)
    perturbed = NamedRandomStreams(7)
    for _ in range(100):
        perturbed.stream("release_jitter").random()

    assert baseline.stream("network_loss").random() == perturbed.stream("network_loss").random()


def test_rng_provenance_exposes_versioned_stable_derivation():
    streams = NamedRandomStreams(3)
    provenance = streams.provenance()

    assert provenance["schema_version"] == RNG_SCHEMA_VERSION
    assert provenance["stream_seeds"]["network_loss"] == derive_stream_seed(3, "network_loss")
