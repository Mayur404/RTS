"""
Graph Neural Network (GNN) Package for Real-Time Runtime Protection.
Implements Graph Construction, Message Passing Architecture,
Rollout Dataset Generation, and Training/Evaluation Harness.
"""

from rts_predictive.gnn.graph_builder import HeteroGraphBuilder
from rts_predictive.gnn.model import PredictiveRuntimeGNN
from rts_predictive.gnn.dataset import RolloutDatasetGenerator
from rts_predictive.gnn.trainer import GNNTrainer

__all__ = [
    "HeteroGraphBuilder",
    "PredictiveRuntimeGNN",
    "RolloutDatasetGenerator",
    "GNNTrainer",
]
