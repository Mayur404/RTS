"""
Script to train and evaluate GhostGuard GNN predictor.
Generates rollout dataset, trains multi-task GNN, and outputs performance metrics.
"""

import sys
import os
import torch

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ghostguard.config import GhostGuardConfig
from ghostguard.gnn.trainer import GNNTrainer


def main():
    # Model initialization and dropout must be repeatable for a research run.
    torch.manual_seed(42)
    print("==================================================")
    print("       GHOSTGUARD GNN TRAINING & EVALUATION       ")
    print("==================================================")
    config = GhostGuardConfig(gnn_epochs=15)
    trainer = GNNTrainer(config=config)

    print("\n[1/3] Generating synthetic rollout samples from simulator...")
    results = trainer.train_and_validate(epochs=15)

    print("\n[2/3] Training History:")
    for h in results["training_history"]:
        print(f"  Epoch {h['epoch']:2d} | Train Loss: {h['train_loss']:.4f} | Val F1: {h['val_f1']:.4f} | Val Acc: {h['val_acc']:.4f}")

    print("\n[3/3] Held-Out Test Evaluation:")
    metrics = results["final_test_metrics"]
    for k, v in metrics.items():
        print(f"  {k:30s}: {v}")

    print(f"\nTrained model saved to: {results['model_path']}")
    print("==================================================")


if __name__ == "__main__":
    main()
