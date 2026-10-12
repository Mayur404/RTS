"""
Independent Training and Evaluation Harness for PredictiveRuntime GNN.
Computes Accuracy, Precision, Recall, F1, ROC-AUC, MAE for Time-to-Violation,
and Prediction Lead Time.
"""

import hashlib
import os
import json
from typing import Dict, Any, List, Tuple, Optional
import torch
import torch.nn as nn
import torch.optim as optim
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    precision_score,
    recall_score,
    f1_score,
    roc_auc_score,
)

from rts_predictive.config import PredictiveRuntimeConfig
from rts_predictive.gnn.model import PredictiveRuntimeGNN
from rts_predictive.gnn.dataset import RolloutSample, RolloutDatasetGenerator
from rts_predictive.gnn.calibration import (
    TemperatureCalibrator,
    brier_score,
    expected_calibration_error,
    select_f1_threshold,
)


class GNNTrainer:
    """Trains and rigorously evaluates the PredictiveRuntime GNN predictor."""

    def __init__(
        self,
        model: Optional[PredictiveRuntimeGNN] = None,
        config: Optional[PredictiveRuntimeConfig] = None
    ):
        self.config = config or PredictiveRuntimeConfig()
        if model is None:
            with torch.random.fork_rng(devices=[]):
                torch.manual_seed(self.config.default_seed)
                model = PredictiveRuntimeGNN(
                    in_features=self.config.gnn_node_features_dim,
                    hidden_dim=self.config.gnn_hidden_dim,
                )
        self.model = model
        self.optimizer = optim.Adam(
            self.model.parameters(),
            lr=self.config.gnn_learning_rate,
            weight_decay=1e-4
        )
        self.criterion_risk = nn.BCELoss()
        self.criterion_ttv = nn.HuberLoss(delta=0.01)
        self.criterion_cause = nn.CrossEntropyLoss()

    def train_epoch(self, train_samples: List[RolloutSample]) -> Dict[str, float]:
        self.model.train()
        total_loss = 0.0
        risk_loss_sum = 0.0
        ttv_loss_sum = 0.0

        for sample in train_samples:
            self.optimizer.zero_grad()
            risk_pred, ttv_pred, cause_pred = self.model(sample.x, sample.edge_index)

            l_risk = self.criterion_risk(risk_pred, sample.y_risk)
            l_ttv = (self.criterion_ttv(ttv_pred, sample.y_ttv)
                     if sample.ttv_observed else ttv_pred.sum() * 0.0)
            l_cause = self.criterion_cause(cause_pred, sample.y_cause)

            loss = l_risk + (2.0 * l_ttv) + (0.5 * l_cause)
            loss.backward()
            self.optimizer.step()

            total_loss += loss.item()
            risk_loss_sum += l_risk.item()
            ttv_loss_sum += l_ttv.item()

        n = max(1, len(train_samples))
        return {
            "loss": total_loss / n,
            "risk_loss": risk_loss_sum / n,
            "ttv_loss": ttv_loss_sum / n
        }

    def evaluate(
        self,
        test_samples: List[RolloutSample],
        calibrator: Optional[TemperatureCalibrator] = None,
        threshold: float = 0.5,
    ) -> Dict[str, Any]:
        """Evaluates model performance metrics on test samples."""
        if not test_samples:
            raise ValueError("evaluation requires held-out rollout observations")
        self.model.eval()
        y_true_risk: List[int] = []
        y_pred_risk_prob: List[float] = []
        y_pred_risk_bin: List[int] = []
        ttv_errors: List[float] = []
        lead_times_ms: List[float] = []

        with torch.no_grad():
            for sample in test_samples:
                risk_pred, ttv_pred, cause_pred = self.model(sample.x, sample.edge_index)

                prob = float(risk_pred[0, 0].item())
                if calibrator is not None:
                    prob = calibrator.apply(prob)
                true_label = int(sample.y_risk[0, 0].item())

                y_true_risk.append(true_label)
                y_pred_risk_prob.append(prob)
                y_pred_risk_bin.append(1 if prob >= threshold else 0)

                # Time-to-violation error
                pred_ttv = float(ttv_pred[0, 0].item())
                true_ttv = float(sample.y_ttv[0, 0].item())
                if sample.ttv_observed:
                    ttv_errors.append(abs(pred_ttv - true_ttv))

                # Prediction lead time (if true risk occurred and predicted correctly)
                if true_label == 1 and prob >= threshold:
                    lead_times_ms.append(true_ttv * 1000.0)

        # Standard ML Metrics
        acc = accuracy_score(y_true_risk, y_pred_risk_bin)
        prec = precision_score(y_true_risk, y_pred_risk_bin, zero_division=0)
        rec = recall_score(y_true_risk, y_pred_risk_bin, zero_division=0)
        f1 = f1_score(y_true_risk, y_pred_risk_bin, zero_division=0)

        # ROC-AUC if both classes present
        auc = (roc_auc_score(y_true_risk, y_pred_risk_prob)
               if len(set(y_true_risk)) > 1 else None)
        auprc = (average_precision_score(y_true_risk, y_pred_risk_prob)
                 if len(set(y_true_risk)) > 1 else None)

        mae_ttv = sum(ttv_errors) / len(ttv_errors) if ttv_errors else None
        avg_lead_time_ms = (sum(lead_times_ms) / len(lead_times_ms)
                            if lead_times_ms else None)

        return {
            "test_samples_count": len(test_samples),
            "accuracy": round(acc, 4),
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1_score": round(f1, 4),
            "roc_auc": round(auc, 4) if auc is not None else None,
            "auprc": round(auprc, 4) if auprc is not None else None,
            "brier_score": round(brier_score(y_pred_risk_prob, y_true_risk), 4),
            "ece": round(expected_calibration_error(y_pred_risk_prob, y_true_risk), 4),
            "decision_threshold": threshold,
            "ttv_mae_seconds": round(mae_ttv, 4) if mae_ttv is not None else None,
            "avg_prediction_lead_time_ms": (
                round(avg_lead_time_ms, 2) if avg_lead_time_ms is not None else None
            ),
        }

    def train_and_validate(
        self,
        epochs: Optional[int] = None,
        save_dir: str = "models"
    ) -> Dict[str, Any]:
        """Runs full training lifecycle on procedurally generated rollout data."""
        num_epochs = epochs or self.config.gnn_epochs
        generator = RolloutDatasetGenerator(self.config)
        train_data, val_data, test_data = generator.build_dataset()

        history = []
        for epoch in range(1, num_epochs + 1):
            train_metrics = self.train_epoch(train_data)
            if epoch % 5 == 0 or epoch == num_epochs:
                val_metrics = self.evaluate(val_data)
                history.append({
                    "epoch": epoch,
                    "train_loss": round(train_metrics["loss"], 4),
                    "val_f1": val_metrics["f1_score"],
                    "val_acc": val_metrics["accuracy"]
                })

        # Fit calibration and select the operating point on validation only.
        self.model.eval()
        validation_probabilities = []
        validation_outcomes = []
        with torch.no_grad():
            for sample in val_data:
                risk, _, _ = self.model(sample.x, sample.edge_index)
                validation_probabilities.append(float(risk[0, 0].item()))
                validation_outcomes.append(int(sample.y_risk[0, 0].item()))
        calibrator = TemperatureCalibrator.fit(validation_probabilities, validation_outcomes)
        calibrated_validation = [calibrator.apply(value) for value in validation_probabilities]
        threshold = select_f1_threshold(calibrated_validation, validation_outcomes)

        # Test data are touched once after calibration and threshold selection.
        final_test_metrics = self.evaluate(test_data, calibrator, threshold)

        # Save weights
        os.makedirs(save_dir, exist_ok=True)
        model_path = os.path.join(save_dir, "gnn_predictive_runtime.pt")
        torch.save(self.model.state_dict(), model_path)
        with open(model_path, "rb") as handle:
            weights_sha256 = hashlib.sha256(handle.read()).hexdigest()
        data_manifest = {
            "generator": "future-deadline-rollout/1",
            "train_seeds": [101, 102, 103, 104, 105],
            "validation_seeds": [201, 202],
            "test_seeds": [301, 302],
            "sample_counts": {
                "train": len(train_data), "validation": len(val_data), "test": len(test_data),
            },
            "lookahead_ms": self.config.gnn_lookahead_horizon_ms,
        }
        manifest_bytes = json.dumps(data_manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        data_manifest["sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
        bundle = {
            "bundle_version": "rts_predictive.gnn-bundle/1",
            "weights_sha256": weights_sha256,
            "feature_schema": "hetero-task-resource/9-v2",
            "normalization": "embedded-in-feature-builder-v1",
            "calibration": {
                "method": "temperature_scaling",
                "temperature": calibrator.temperature,
                "validation_ece": expected_calibration_error(calibrated_validation, validation_outcomes),
            },
            "decision_threshold": threshold,
            "training": {
                "epochs": num_epochs,
                "learning_rate": self.config.gnn_learning_rate,
                "torch_initialization_seed": self.config.default_seed,
            },
            "data_manifest": data_manifest,
            "test_metrics": final_test_metrics,
        }
        bundle_path = os.path.join(save_dir, "gnn_predictive_runtime.bundle.json")
        with open(bundle_path, "w", encoding="utf-8") as handle:
            json.dump(bundle, handle, indent=2, sort_keys=True)

        return {
            "training_history": history,
            "final_test_metrics": final_test_metrics,
            "model_path": model_path,
            "bundle_path": bundle_path,
        }
