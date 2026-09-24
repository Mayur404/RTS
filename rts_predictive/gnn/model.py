"""
PredictiveRuntime Graph Neural Network (GNN) Architecture.
Implements multi-layer message passing to predict:
1. Deadline-miss probability / risk score
2. Estimated time-to-violation (seconds)
3. Dominant resource bottleneck attribution
"""

from typing import Tuple, Dict, Any, Optional
import torch
import torch.nn as nn
import torch.nn.functional as F

try:
    from torch_geometric.nn import GCNConv, global_mean_pool
    HAS_PYG = True
except ImportError:
    HAS_PYG = False


class PredictiveRuntimeGNN(nn.Module):
    """
    Message-Passing Graph Neural Network for Real-Time Deadline Protection.
    Processes dynamic task-resource graphs and outputs risk, timing, and attribution.
    """

    CAUSE_NAMES = ["CPU contention", "GPU contention", "Memory pressure", "Queue/Network delay"]

    def __init__(self, in_features: int = 9, hidden_dim: int = 32):
        super().__init__()
        self.in_features = in_features
        self.hidden_dim = hidden_dim
        self.calibration_temperature = 1.0
        self.decision_threshold = 0.5
        self.bundle_version = None
        self.calibrated = False

        # Graph Message Passing Layers
        if HAS_PYG:
            self.conv1 = GCNConv(in_features, hidden_dim)
            self.conv2 = GCNConv(hidden_dim, hidden_dim)
        else:
            # Fallback lightweight message passing if PyG native conv unavailable
            self.fc_node = nn.Linear(in_features, hidden_dim)
            self.fc_msg = nn.Linear(hidden_dim, hidden_dim)

        self.norm1 = nn.LayerNorm(hidden_dim)
        self.norm2 = nn.LayerNorm(hidden_dim)
        self.dropout = nn.Dropout(p=0.1)

        # Multi-task Prediction Heads
        self.risk_head = nn.Sequential(
            nn.Linear(hidden_dim, 16),
            nn.ReLU(),
            nn.Linear(16, 1),
            nn.Sigmoid()
        )

        self.ttv_head = nn.Sequential(
            nn.Linear(hidden_dim, 16),
            nn.ReLU(),
            nn.Linear(16, 1),
            nn.Softplus()  # Enforce positive time-to-violation
        )

        self.cause_head = nn.Sequential(
            nn.Linear(hidden_dim, 16),
            nn.ReLU(),
            nn.Linear(16, 4)  # 4 bottleneck classes
        )

    def forward(
        self,
        x: torch.Tensor,
        edge_index: torch.Tensor,
        batch: Optional[torch.Tensor] = None
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        Forward pass.
        Returns:
            risk: [B, 1] probability
            ttv: [B, 1] seconds
            cause_logits: [B, 4] logits
        """
        if HAS_PYG:
            h = self.conv1(x, edge_index)
            h = F.relu(self.norm1(h))
            h = self.dropout(h)
            h = self.conv2(h, edge_index)
            h = F.relu(self.norm2(h))
        else:
            # Simple scatter mean message passing
            src, dst = edge_index[0], edge_index[1]
            h0 = F.relu(self.norm1(self.fc_node(x)))
            # Aggregate neighbor messages
            msg = h0[src]
            aggr = torch.zeros_like(h0)
            aggr.index_add_(0, dst, msg)
            deg = torch.zeros(h0.size(0), 1, device=x.device)
            deg.index_add_(0, dst, torch.ones_like(src, dtype=torch.float32).unsqueeze(1))
            aggr = aggr / deg.clamp(min=1.0)
            h = F.relu(self.norm2(self.fc_msg(aggr) + h0))

        # Global pooling across graph nodes
        if batch is None:
            # Single graph: average all nodes
            graph_rep = torch.mean(h, dim=0, keepdim=True)
        else:
            if HAS_PYG:
                graph_rep = global_mean_pool(h, batch)
            else:
                num_graphs = int(batch.max().item()) + 1
                graph_rep = torch.zeros(num_graphs, self.hidden_dim, device=x.device)
                for b_idx in range(num_graphs):
                    mask = (batch == b_idx)
                    if mask.any():
                        graph_rep[b_idx] = torch.mean(h[mask], dim=0)

        risk = self.risk_head(graph_rep)
        ttv = self.ttv_head(graph_rep)
        cause_logits = self.cause_head(graph_rep)

        return risk, ttv, cause_logits

    def predict(
        self,
        task: Any,
        dev: Any,
        current_time_ms: float
    ) -> Tuple[float, float, str]:
        """Inference wrapper for runtime integration with PredictiveRuntime scheduler."""
        from rts_predictive.gnn.graph_builder import HeteroGraphBuilder
        self.eval()
        with torch.no_grad():
            x, edge_index, _ = HeteroGraphBuilder.build_graph(
                dev, current_time_ms, focus_task_id=task.instance_id
            )
            risk_t, ttv_t, cause_t = self.forward(x, edge_index)
            risk = self._calibrate_probability(float(risk_t[0, 0].item()))
            ttv = float(ttv_t[0, 0].item())
            cause_idx = int(torch.argmax(cause_t[0]).item())
            cause_name = self.CAUSE_NAMES[cause_idx]
            return risk, ttv, cause_name

    def _calibrate_probability(self, probability: float) -> float:
        from rts_predictive.gnn.calibration import TemperatureCalibrator
        return TemperatureCalibrator(self.calibration_temperature).apply(probability)

    def predict_detailed(
        self,
        task: Any,
        dev: Any,
        current_time_ms: float
    ) -> Dict[str, Any]:
        """Inference with runtime latency measurement and full cause probabilities."""
        import time
        from rts_predictive.gnn.graph_builder import HeteroGraphBuilder
        start_ns = time.perf_counter_ns()
        self.eval()
        with torch.no_grad():
            x, edge_index, _ = HeteroGraphBuilder.build_graph(
                dev, current_time_ms, focus_task_id=task.instance_id
            )
            risk_t, ttv_t, cause_t = self.forward(x, edge_index)
            probs = F.softmax(cause_t[0], dim=-1)
            infer_us = max(1, (time.perf_counter_ns() - start_ns) // 1000)
            cause_probs = {self.CAUSE_NAMES[i]: round(float(probs[i].item()), 4) for i in range(len(self.CAUSE_NAMES))}
            cause_idx = int(torch.argmax(cause_t[0]).item())
            return {
                "miss_probability": self._calibrate_probability(float(risk_t[0, 0].item())),
                "ttv_ms": float(ttv_t[0, 0].item()) * 1000.0,
                "dominant_cause": self.CAUSE_NAMES[cause_idx],
                "cause_probabilities": cause_probs,
                "inference_us": infer_us,
                "model_version": self.bundle_version or "weights-only",
                "calibrated": self.calibrated,
            }


def load_pretrained_gnn(weights_path: str = "models/gnn_predictive_runtime.pt") -> PredictiveRuntimeGNN:
    """Load weights and, when present, their integrity-checked model bundle."""
    import hashlib
    import json
    import os
    model = PredictiveRuntimeGNN()
    if not os.path.exists(weights_path):
        raise FileNotFoundError(f"GNN weights are unavailable: {weights_path}")
    state_dict = torch.load(weights_path, map_location="cpu", weights_only=True)
    model.load_state_dict(state_dict)
    bundle_path = os.path.splitext(weights_path)[0] + ".bundle.json"
    if os.path.exists(bundle_path):
        with open(bundle_path, "r", encoding="utf-8") as handle:
            bundle = json.load(handle)
        with open(weights_path, "rb") as handle:
            actual_digest = hashlib.sha256(handle.read()).hexdigest()
        if bundle.get("weights_sha256") != actual_digest:
            raise ValueError("GNN model bundle does not match the saved weights")
        if bundle.get("feature_schema") != "hetero-task-resource/9-v2":
            raise ValueError("unsupported GNN feature schema")
        calibration = bundle.get("calibration", {})
        if calibration.get("method") != "temperature_scaling":
            raise ValueError("unsupported GNN calibration method")
        model.calibration_temperature = float(calibration["temperature"])
        model.decision_threshold = float(bundle["decision_threshold"])
        model.bundle_version = str(bundle["bundle_version"])
        model.calibrated = True
    model.eval()
    return model

