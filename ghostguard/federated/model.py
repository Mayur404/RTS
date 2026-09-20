"""
Shared Neural Model for Task Execution Time and Device Reliability.
Trained collaboratively across heterogeneous edge nodes via Federated Averaging.
"""

from typing import Tuple, Any
import torch
import torch.nn as nn


class DeviceExecutionReliabilityModel(nn.Module):
    """
    Predicts:
    1. Expected Task Execution Time on candidate hardware (ms)
    2. Reliability / Success Confidence score [0.0 to 1.0]
    """

    def __init__(self, in_features: int = 6, hidden_dim: int = 24):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(in_features, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU()
        )

        # Execution time regression head (ms)
        self.time_head = nn.Sequential(
            nn.Linear(hidden_dim, 12),
            nn.ReLU(),
            nn.Linear(12, 1),
            nn.Softplus()
        )

        # Reliability classification head [0, 1]
        self.rel_head = nn.Sequential(
            nn.Linear(hidden_dim, 12),
            nn.ReLU(),
            nn.Linear(12, 1),
            nn.Sigmoid()
        )

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        features = self.encoder(x)
        t_exec = self.time_head(features)
        rel = self.rel_head(features)
        return t_exec, rel

    @classmethod
    def extract_features(cls, task: Any, target_dev: Any) -> torch.Tensor:
        """Extracts normalized feature vector from a task and target device state."""
        cpu_u = target_dev.resources.get_effective_cpu_utilization()
        gpu_u = target_dev.resources.get_effective_gpu_utilization()

        vec = [
            task.nominal_wcet_ms / 50.0,
            1.0 if task.requires_gpu else 0.0,
            target_dev.hardware.cpu_speed_multiplier,
            target_dev.hardware.gpu_speed_multiplier,
            min(2.0, cpu_u),
            min(2.0, gpu_u)
        ]
        return torch.tensor([vec], dtype=torch.float32)

    def predict_execution_time(self, task: Any, target_dev: Any) -> float:
        """Queries expected execution time in milliseconds."""
        self.eval()
        with torch.no_grad():
            feat = self.extract_features(task, target_dev)
            t_exec, _ = self.forward(feat)
            return float(t_exec[0, 0].item())

    def predict_reliability(self, task: Any, target_dev: Any) -> float:
        """Queries predicted completion reliability probability."""
        self.eval()
        with torch.no_grad():
            feat = self.extract_features(task, target_dev)
            _, rel = self.forward(feat)
            return float(rel[0, 0].item())
