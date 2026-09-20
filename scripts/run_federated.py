"""Run FedAvg and save a reproducible pooled-data reference comparison."""

import sys
import os
import json
import torch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ghostguard.config import GhostGuardConfig, HARDWARE_PROFILES
from ghostguard.simulator.engine import DiscreteEventSimulator
from ghostguard.federated.client import FederatedClient
from ghostguard.federated.server import FedAvgServer
from ghostguard.schedulers.local_fifo import LocalFIFOScheduler


def main():
    # Make model initialization and local SGD reproducible alongside simulator seed 42.
    torch.manual_seed(42)
    print("==================================================")
    print("     GHOSTGUARD FEDERATED LEARNING (FedAvg)       ")
    print("==================================================")

    # 1. Run quick simulation to populate private client execution logs
    sim = DiscreteEventSimulator(fleet_size=6, seed=42)
    sim.schedule_periodic_tasks(duration_ms=400.0)
    sim.attach_scheduler(LocalFIFOScheduler())
    sim.run(duration_ms=400.0)

    # 2. Initialize Federated Clients
    clients = []
    for dev_id, dev in sim.devices.items():
        client = FederatedClient(client_id=dev_id, lr=0.005)
        # Populate traces from device completed tasks
        for task in dev.completed_tasks + dev.deadline_missed_tasks:
            client.record_trace(
                task=task,
                dev=dev,
                actual_exec_ms=task.response_time_ms or task.nominal_wcet_ms,
                success=task.deadline_met if task.deadline_met is not None else False
            )
        clients.append(client)

    server = FedAvgServer(clients=clients)

    # Generate test samples from global tasks
    test_samples = []
    for t in sim.all_tasks[-40:]:
        dev = sim.devices.get(t.device_id)
        if dev:
            from ghostguard.federated.model import DeviceExecutionReliabilityModel
            feat = DeviceExecutionReliabilityModel.extract_features(t, dev)
            test_samples.append((feat, t.nominal_wcet_ms, 1.0 if t.deadline_met else 0.0))

    print(f"Decentralized Fleet: {len(clients)} Heterogeneous Edge Nodes")
    print(f"Total Local Execution Logs: {sum(len(c.local_traces) for c in clients)}")

    # 3. Run Federated Rounds
    print("\nExecuting FedAvg Decentralized Training Rounds...")
    fl_results = server.run_federated_rounds(num_rounds=5, local_epochs=3, test_samples=test_samples)

    for r in fl_results["round_history"]:
        print(f"  Round {r['round']} | Participating Nodes: {r['participating_clients']} | MAE Exec Time: {r.get('mae_exec_time_ms', 'N/A')} ms | Reliability Acc: {r.get('reliability_accuracy', 'N/A')}")

    # 4. Compare with centralized pooled-data reference (privacy-violating)
    print("\nBenchmarking Centralized Pooled-Data Reference...")
    cent_res = server.train_centralized_upper_bound(total_epochs=15, test_samples=test_samples)
    print(f"  Centralized Reference MAE Exec Time: {cent_res.get('centralized_mae_ms', 'N/A'):.3f} ms")

    os.makedirs("results", exist_ok=True)
    artifact = {
        "federated_rounds": fl_results["round_history"],
        "centralized_pooled_data_reference": cent_res,
        "seed": 42,
    }
    with open(os.path.join("results", "federated_results.json"), "w") as output:
        json.dump(artifact, output, indent=2)
    print("  Saved: results/federated_results.json")

    print("\nFederated Learning evaluation completed successfully.")
    print("==================================================")


if __name__ == "__main__":
    main()
