"""The documented training API can be inspected on lazy-annotation Python."""
from typing import get_type_hints

from rts_predictive.gnn.trainer import GNNTrainer
from rts_predictive import config


def test_training_api_annotations_resolve_for_tools_and_documentation():
    constructor=get_type_hints(GNNTrainer.__init__)
    training=get_type_hints(GNNTrainer.train_and_validate)
    assert {'model','config'} <= constructor.keys()
    assert {'epochs','save_dir','return'} <= training.keys()


def test_fleet_configuration_annotations_resolve_for_schema_inspection():
    assert 'NODE_FLEET_DEFINITIONS' in get_type_hints(config)
