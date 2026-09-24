"""
Unit tests for GNN Graph Construction, Architecture, and Rollout Training.
"""

import torch
import pytest
from rts_predictive.config import DEFAULT_TASK_PROFILES, HARDWARE_PROFILES
from rts_predictive.simulator.device import DeviceNode
from rts_predictive.simulator.tasks import TaskInstance
from rts_predictive.gnn.graph_builder import HeteroGraphBuilder
from rts_predictive.gnn.model import PredictiveRuntimeGNN
from rts_predictive.gnn.dataset import RolloutDatasetGenerator
from rts_predictive.gnn.trainer import GNNTrainer


def test_graph_builder_and_model_shapes():
    hw = HARDWARE_PROFILES["Drone-Standard"]
    dev = DeviceNode("Dev1", hw)

    # Add tasks
    t1 = TaskInstance.from_profile(DEFAULT_TASK_PROFILES["Sense"], "s1", "Dev1", 0.0)
    t2 = TaskInstance.from_profile(DEFAULT_TASK_PROFILES["Perception"], "p1", "Dev1", 0.0)
    dev.admit_task(t1)
    dev.admit_task(t2)

    x, edge_index, node_map = HeteroGraphBuilder.build_graph(
        dev, current_time_ms=5.0, focus_task_id="p1"
    )

    # Resource nodes (4) + Task nodes (2) = 6 nodes
    assert x.shape[0] == 6
    assert x.shape[1] == 9
    assert x[node_map["p1"], 8].item() == 1.0
    assert x[node_map["s1"], 8].item() == 0.0
    assert edge_index.shape[0] == 2
    assert "RES_CPU" in node_map
    assert "s1" in node_map

    # Test GNN forward
    model = PredictiveRuntimeGNN(in_features=9, hidden_dim=32)
    risk, ttv, cause = model(x, edge_index)

    assert risk.shape == (1, 1)
    assert 0.0 <= risk.item() <= 1.0
    assert ttv.shape == (1, 1)
    assert ttv.item() >= 0.0
    assert cause.shape == (1, 4)


def test_rollout_dataset_generator():
    gen = RolloutDatasetGenerator()
    samples = gen.generate_split(seeds=[42], sim_duration_ms=100.0, sample_interval_ms=30.0)
    assert len(samples) > 0

    sample = samples[0]
    assert sample.x.dim() == 2
    assert sample.edge_index.dim() == 2
    assert sample.y_risk.item() in (0.0, 1.0)
    assert all(sample.ttv_observed == bool(sample.y_risk.item()) for sample in samples)


def test_single_class_evaluation_reports_missing_auc_and_lead_time():
    samples = RolloutDatasetGenerator().generate_split(
        seeds=[42], sim_duration_ms=100.0, sample_interval_ms=20.0
    )
    negatives = [sample for sample in samples if sample.y_risk.item() == 0.0]
    assert negatives
    result = GNNTrainer().evaluate(negatives)
    assert result["roc_auc"] is None
    assert result["ttv_mae_seconds"] is None
    assert result["avg_prediction_lead_time_ms"] is None
