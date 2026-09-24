"""Train, calibrate, evaluate, and package the federated remote estimator."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import torch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rts_predictive.federated.client import FederatedClient
from rts_predictive.federated.model import DeviceExecutionReliabilityModel
from rts_predictive.federated.server import FedAvgServer
from rts_predictive.gnn.calibration import TemperatureCalibrator, brier_score, expected_calibration_error
from rts_predictive.schedulers.local_fifo import LocalFIFOScheduler
from rts_predictive.simulator.engine import DiscreteEventSimulator


def collect_observations(seed: int, duration_ms: float = 500.0):
    sim = DiscreteEventSimulator(fleet_size=6, seed=seed)
    sim.schedule_periodic_tasks(duration_ms=duration_ms)
    sim.schedule_contention_burst("Device_1", 80.0, 180.0, cpu_load=0.95, gpu_load=0.95)
    sim.schedule_contention_burst("Device_2", 180.0, 140.0, cpu_load=1.1, gpu_load=1.0)
    sim.attach_scheduler(LocalFIFOScheduler())
    sim.run(duration_ms=duration_ms)
    observations = []
    for task in sim.all_tasks:
        if task.executed_service_ms <= 0 or task.execution_start_cpu_util is None:
            continue
        dev = sim.devices[task.device_id]
        feature = DeviceExecutionReliabilityModel.extract_features(
            task, dev,
            cpu_utilization=task.execution_start_cpu_util,
            gpu_utilization=task.execution_start_gpu_util,
        )
        observations.append((
            task.device_id, task, dev, feature, task.executed_service_ms,
            1.0 if task.deadline_met is True else 0.0,
        ))
    return observations


def evaluate(model, observations, calibrator):
    time_errors, probabilities, outcomes, q95_covered = [], [], [], []
    with torch.no_grad():
        for _, _, _, feature, actual_ms, success in observations:
            predicted_ms, predicted_rel = model(feature)
            mean_ms = float(predicted_ms[0, 0].item())
            probability = calibrator.apply(float(predicted_rel[0, 0].item()))
            time_errors.append(abs(mean_ms - actual_ms))
            probabilities.append(probability)
            outcomes.append(int(success))
            q95_covered.append(actual_ms <= mean_ms * model.q95_multiplier)
    return {
        "samples": len(observations),
        "execution_mae_ms": sum(time_errors) / len(time_errors),
        "reliability_brier": brier_score(probabilities, outcomes),
        "reliability_ece": expected_calibration_error(probabilities, outcomes),
        "q95_empirical_coverage": sum(q95_covered) / len(q95_covered),
    }


def main():
    torch.manual_seed(42)
    train = collect_observations(42) + collect_observations(101)
    validation = collect_observations(201)
    test = collect_observations(301)

    clients = []
    for device_id in sorted({row[0] for row in train}):
        client = FederatedClient(device_id, lr=0.005)
        for row_device, task, dev, _, actual_ms, success in train:
            if row_device == device_id:
                client.record_trace(task, dev, actual_ms, bool(success))
        clients.append(client)

    server = FedAvgServer(clients)
    rounds = server.run_federated_rounds(num_rounds=8, local_epochs=3)
    model = server.global_model
    model.eval()

    raw_probabilities, validation_outcomes, ratios = [], [], []
    with torch.no_grad():
        for _, _, _, feature, actual_ms, success in validation:
            predicted_ms, predicted_rel = model(feature)
            mean_ms = max(1e-6, float(predicted_ms[0, 0].item()))
            raw_probabilities.append(float(predicted_rel[0, 0].item()))
            validation_outcomes.append(int(success))
            ratios.append(actual_ms / mean_ms)
    calibrator = TemperatureCalibrator.fit(raw_probabilities, validation_outcomes)
    ratios.sort()
    q95_index = min(len(ratios) - 1, int(0.95 * len(ratios)))
    model.q95_multiplier = max(1.0, ratios[q95_index])
    metrics = evaluate(model, test, calibrator)

    model_dir = Path("models")
    model_dir.mkdir(exist_ok=True)
    weights_path = model_dir / "federated_remote_estimator.pt"
    torch.save(model.state_dict(), weights_path)
    bundle = {
        "bundle_version": "rts_predictive.federated-bundle/1",
        "feature_schema": "remote-execution/6-v1",
        "weights_sha256": hashlib.sha256(weights_path.read_bytes()).hexdigest(),
        "training": {
            "algorithm": "FedAvg", "rounds": 8, "local_epochs": 3,
            "train_seeds": [42, 101], "validation_seeds": [201], "test_seeds": [301],
            "clients": len(clients), "train_samples": len(train),
            "transmission_bytes": sum(row["transmission_bytes"] for row in rounds["round_history"]),
        },
        "reliability_calibration": {
            "method": "temperature_scaling", "temperature": calibrator.temperature,
        },
        "latency_q95_multiplier": model.q95_multiplier,
        "test_metrics": metrics,
        "evidence": "SIMULATION_EVALUATED",
    }
    weights_path.with_suffix(".bundle.json").write_text(
        json.dumps(bundle, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(bundle, indent=2))


if __name__ == "__main__":
    main()
