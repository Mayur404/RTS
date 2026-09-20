"""
Unit tests for GNN Graph Construction, Architecture, and Rollout Training.
"""

import torch
import pytest
from ghostguard.config import DEFAULT_TASK_PROFILES, HARDWARE_PROFILES
from ghostguard.simulator.device import DeviceNode
from ghostguard.simulator.tasks import TaskInstance
from ghostguard.gnn.graph_builder import HeteroGraphBuilder
from ghostguard.gnn.model import GhostGuardGNN
from ghostguard.gnn.dataset import RolloutDatasetGenerator
from ghostguard.gnn.trainer import GNNTrainer


def test_graph_builder_and_model_shapes():
    hw = HARDWARE_PROFILES["Drone-Standard"]
    dev = DeviceNode("Dev1", hw)

    # Add tasks
    t1 = TaskInstance.from_profile(DEFAULT_TASK_PROFILES["Sense"], "s1", "Dev1", 0.0)
    t2 = TaskInstance.from_profile(DEFAULT_TASK_PROFILES["Perception"], "p1", "Dev1", 0.0)
    dev.admit_task(t1)
    dev.admit_task(t2)

    x, edge_index, node_map = HeteroGraphBuilder.build_graph(dev, current_time_ms=5.0)

    # Resource nodes (4) + Task nodes (2) = 6 nodes
    assert x.shape[0] == 6
    assert x.shape[1] == 8
    assert edge_index.shape[0] == 2
    assert "RES_CPU" in node_map
    assert "s1" in node_map

    # Test GNN forward
    model = GhostGuardGNN(in_features=8, hidden_dim=32)
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
