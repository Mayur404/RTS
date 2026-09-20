"""
Federated Averaging (FedAvg) Central Server and Benchmark Coordinator.
Aggregates decentralized weights without collecting private execution traces.
Includes a centralized pooled-data reference comparison.
"""

from typing import List, Dict, Any, Optional
import torch
import torch.nn as nn
import torch.optim as optim
from ghostguard.federated.model import DeviceExecutionReliabilityModel
from ghostguard.federated.client import FederatedClient


class FedAvgServer:
    """Central server performing parameter aggregation across edge nodes."""

    def __init__(self, clients: Optional[List[FederatedClient]] = None):
        self.global_model = DeviceExecutionReliabilityModel()
        self.clients: List[FederatedClient] = clients or []
        self.round_history: List[Dict[str, Any]] = []

    def register_client(self, client: FederatedClient):
        self.clients.append(client)

    def run_federated_rounds(
        self,
        num_rounds: int = 5,
        local_epochs: int = 3,
        test_samples: Optional[List[Any]] = None
    ) -> Dict[str, Any]:
        """Executes FedAvg rounds."""
        global_weights = {k: v.cpu().clone() for k, v in self.global_model.state_dict().items()}

        for round_idx in range(1, num_rounds + 1):
            client_updates = []
            total_samples = 0

            # 1. Distribute current global weights to clients & train locally
            for client in self.clients:
                client.set_weights(global_weights)
                stats = client.train_local(epochs=local_epochs)
                n = stats["samples"]
                if n > 0:
                    client_updates.append((client.get_weights(), n))
                    total_samples += n

            # 2. FedAvg Parameter Aggregation
            if client_updates and total_samples > 0:
                new_weights = {}
                for key in global_weights.keys():
                    weighted_sum = torch.zeros_like(global_weights[key], dtype=torch.float32)
                    for w, n in client_updates:
                        weighted_sum += (w[key].float() * (n / total_samples))
                    new_weights[key] = weighted_sum
                global_weights = new_weights
                self.global_model.load_state_dict(global_weights)

            # 3. Evaluate global model on test set if provided
            round_stat: Dict[str, Any] = {
                "round": round_idx,
                "participating_clients": len(client_updates),
                "total_samples": total_samples
            }
            if test_samples:
                eval_metrics = self.evaluate(test_samples)
                round_stat.update(eval_metrics)

            self.round_history.append(round_stat)

        # Distribute final converged model to all clients
        for client in self.clients:
            client.set_weights(global_weights)

        return {
            "num_rounds": num_rounds,
            "round_history": self.round_history,
            "final_metrics": self.round_history[-1] if self.round_history else {}
        }

    def train_centralized_upper_bound(
        self,
        total_epochs: int = 15,
        test_samples: Optional[List[Any]] = None
    ) -> Dict[str, Any]:
        """
        Pooled-data reference: trains centrally with all client data pooled together.
        This violates privacy in real deployments. It is a comparison reference,
        not a guaranteed performance upper bound on a finite stochastic run.
        """
        central_model = DeviceExecutionReliabilityModel()
        optimizer = optim.Adam(central_model.parameters(), lr=0.005)
        crit_time = nn.HuberLoss(delta=1.0)
        crit_rel = nn.BCELoss()

        # Pool all private client traces centrally
        pooled_traces = []
        for c in self.clients:
            pooled_traces.extend(c.local_traces)

        if not pooled_traces:
            return {"status": "No data"}

        central_model.train()
        for _ in range(total_epochs):
            for feat, true_time, true_rel in pooled_traces:
                optimizer.zero_grad()
                t_pred, r_pred = central_model(feat)
                l_time = crit_time(t_pred, torch.tensor([[true_time]], dtype=torch.float32))
                l_rel = crit_rel(r_pred, torch.tensor([[true_rel]], dtype=torch.float32))
                loss = (0.1 * l_time) + l_rel
                loss.backward()
                optimizer.step()

        eval_res = {}
        if test_samples:
            central_model.eval()
            time_errors = []
            with torch.no_grad():
                for feat, true_time, true_rel in test_samples:
                    t_pred, _ = central_model(feat)
                    time_errors.append(abs(float(t_pred[0, 0].item()) - true_time))
            eval_res["centralized_mae_ms"] = sum(time_errors) / max(1, len(time_errors))

        return {
            "pooled_samples": len(pooled_traces),
            **eval_res
        }

    def evaluate(self, test_samples: List[Any]) -> Dict[str, float]:
        self.global_model.eval()
        time_errors = []
        correct_rel = 0

        with torch.no_grad():
            for feat, true_time, true_rel in test_samples:
                t_pred, r_pred = self.global_model(feat)
                time_errors.append(abs(float(t_pred[0, 0].item()) - true_time))
                pred_bin = 1.0 if float(r_pred[0, 0].item()) >= 0.5 else 0.0
                if pred_bin == true_rel:
                    correct_rel += 1

        n = max(1, len(test_samples))
        return {
            "mae_exec_time_ms": round(sum(time_errors) / n, 3),
            "reliability_accuracy": round(correct_rel / n, 4)
        }
