"""
Federated Learning Client representing a single heterogeneous edge node.
Keeps raw performance logs local and only shares parameter updates.
"""

from typing import List, Dict, Any, Tuple
import torch
import torch.nn as nn
import torch.optim as optim
from ghostguard.federated.model import DeviceExecutionReliabilityModel


class FederatedClient:
    """Client node participating in decentralized collaborative training."""

    def __init__(self, client_id: str, lr: float = 0.005):
        self.client_id = client_id
        self.lr = lr
        self.model = DeviceExecutionReliabilityModel()
        self.local_traces: List[Tuple[torch.Tensor, float, float]] = []

    def record_trace(self, task: Any, dev: Any, actual_exec_ms: float, success: bool):
        """Logs a private execution observation."""
        feat = DeviceExecutionReliabilityModel.extract_features(task, dev)
        self.local_traces.append((feat, actual_exec_ms, 1.0 if success else 0.0))
        # Keep sliding window of latest 200 logs
        if len(self.local_traces) > 200:
            self.local_traces.pop(0)

    def get_weights(self) -> Dict[str, torch.Tensor]:
        return {k: v.cpu().clone() for k, v in self.model.state_dict().items()}

    def set_weights(self, global_weights: Dict[str, torch.Tensor]):
        self.model.load_state_dict(global_weights)

    def train_local(self, epochs: int = 3) -> Dict[str, float]:
        """Trains model on local private traces."""
        if len(self.local_traces) < 4:
            return {"loss": 0.0, "samples": 0}

        self.model.train()
        optimizer = optim.Adam(self.model.parameters(), lr=self.lr)
        crit_time = nn.HuberLoss(delta=1.0)
        crit_rel = nn.BCELoss()

        total_loss = 0.0
        for _ in range(epochs):
            for feat, true_time, true_rel in self.local_traces:
                optimizer.zero_grad()
                t_pred, r_pred = self.model(feat)

                l_time = crit_time(t_pred, torch.tensor([[true_time]], dtype=torch.float32))
                l_rel = crit_rel(r_pred, torch.tensor([[true_rel]], dtype=torch.float32))
                loss = (0.1 * l_time) + l_rel
                loss.backward()
                optimizer.step()
                total_loss += loss.item()

        n = len(self.local_traces) * epochs
        return {"loss": total_loss / max(1, n), "samples": len(self.local_traces)}

    def evaluate(self, test_samples: List[Tuple[torch.Tensor, float, float]]) -> Dict[str, float]:
        self.model.eval()
        time_errors = []
        rel_correct = 0

        with torch.no_grad():
            for feat, true_time, true_rel in test_samples:
                t_pred, r_pred = self.model(feat)
                time_errors.append(abs(float(t_pred[0, 0].item()) - true_time))
                pred_bin = 1.0 if float(r_pred[0, 0].item()) >= 0.5 else 0.0
                if pred_bin == true_rel:
                    rel_correct += 1

        n = max(1, len(test_samples))
        return {
            "mae_time_ms": sum(time_errors) / n,
            "accuracy_rel": rel_correct / n
        }
