"""
Graph Neural Network (GNN) Package for Real-Time Runtime Protection.
Implements Graph Construction, Message Passing Architecture,
Rollout Dataset Generation, and Training/Evaluation Harness.
"""

from ghostguard.gnn.graph_builder import HeteroGraphBuilder
from ghostguard.gnn.model import GhostGuardGNN
from ghostguard.gnn.dataset import RolloutDatasetGenerator
from ghostguard.gnn.trainer import GNNTrainer

__all__ = [
    "HeteroGraphBuilder",
    "GhostGuardGNN",
    "RolloutDatasetGenerator",
    "GNNTrainer",
]
