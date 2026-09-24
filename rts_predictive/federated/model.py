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
    def extract_features(
        cls,
        task: Any,
        target_dev: Any,
        cpu_utilization: float | None = None,
        gpu_utilization: float | None = None,
    ) -> torch.Tensor:
        """Extracts normalized feature vector from a task and target device state."""
        cpu_u = (target_dev.resources.get_effective_cpu_utilization()
                 if cpu_utilization is None else cpu_utilization)
        gpu_u = (target_dev.resources.get_effective_gpu_utilization()
                 if gpu_utilization is None else gpu_utilization)

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
            probability = float(rel[0, 0].item())
            from rts_predictive.gnn.calibration import TemperatureCalibrator
            return TemperatureCalibrator(
                getattr(self, "reliability_temperature", 1.0)
            ).apply(probability)

    def predict_q95_execution_time(self, task: Any, target_dev: Any) -> float:
        """Conservative 95th-percentile execution latency bound in milliseconds."""
        t_mean = self.predict_execution_time(task, target_dev)
        return t_mean * getattr(self, "q95_multiplier", 1.25)


def create_default_federated_model() -> DeviceExecutionReliabilityModel:
    """Constructs an untrained estimator for experiments; no calibration is implied."""
    # Keep paired policy runs on identical initial weights without perturbing
    # the caller's RNG. These are not learned federated parameters.
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(0)
        model = DeviceExecutionReliabilityModel()
    model.eval()
    return model


def load_federated_model(
    weights_path: str = "models/federated_remote_estimator.pt",
) -> DeviceExecutionReliabilityModel:
    """Load an evaluated federated estimator and verify its bundle integrity."""
    import hashlib
    import json
    from pathlib import Path

    weights = Path(weights_path)
    bundle_path = weights.with_suffix(".bundle.json")
    if not weights.is_file() or not bundle_path.is_file():
        raise FileNotFoundError("federated estimator weights and bundle are required")
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(weights.read_bytes()).hexdigest()
    if bundle.get("weights_sha256") != digest:
        raise ValueError("federated estimator bundle does not match its weights")
    if bundle.get("feature_schema") != "remote-execution/6-v1":
        raise ValueError("unsupported federated estimator feature schema")
    model = DeviceExecutionReliabilityModel()
    model.load_state_dict(torch.load(weights, map_location="cpu", weights_only=True))
    model.q95_multiplier = float(bundle["latency_q95_multiplier"])
    model.reliability_temperature = float(bundle["reliability_calibration"]["temperature"])
    model.bundle_version = bundle["bundle_version"]
    model.evaluated = True
    model.eval()
    return model
