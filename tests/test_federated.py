"""
Unit tests for Federated Learning (FedAvg) and Decentralized Execution Modeling.
"""

import torch
import pytest
from ghostguard.config import DEFAULT_TASK_PROFILES, HARDWARE_PROFILES
from ghostguard.simulator.device import DeviceNode
from ghostguard.simulator.tasks import TaskInstance
from ghostguard.federated.model import DeviceExecutionReliabilityModel
from ghostguard.federated.client import FederatedClient
from ghostguard.federated.server import FedAvgServer


def test_federated_model_and_client():
    hw = HARDWARE_PROFILES["Drone-Heavy"]
    dev = DeviceNode("Dev1", hw)
    task = TaskInstance.from_profile(DEFAULT_TASK_PROFILES["Perception"], "p1", "Dev1", 0.0)

    model = DeviceExecutionReliabilityModel()
    pred_time = model.predict_execution_time(task, dev)
    pred_rel = model.predict_reliability(task, dev)

    assert pred_time >= 0.0
    assert 0.0 <= pred_rel <= 1.0

    client = FederatedClient("Dev1")
    for _ in range(5):
        client.record_trace(task, dev, actual_exec_ms=14.0, success=True)

    res = client.train_local(epochs=1)
    assert res["samples"] == 5
    assert res["loss"] >= 0.0


def test_fedavg_aggregation():
    c1 = FederatedClient("C1")
    c2 = FederatedClient("C2")
    server = FedAvgServer(clients=[c1, c2])

    hw = HARDWARE_PROFILES["Drone-Standard"]
    dev = DeviceNode("Dev1", hw)
    task = TaskInstance.from_profile(DEFAULT_TASK_PROFILES["ObstacleDetection"], "o1", "Dev1", 0.0)

    for _ in range(6):
        c1.record_trace(task, dev, 8.0, True)
        c2.record_trace(task, dev, 9.0, True)

    history = server.run_federated_rounds(num_rounds=2, local_epochs=1)
    assert history["num_rounds"] == 2
    assert len(history["round_history"]) == 2
