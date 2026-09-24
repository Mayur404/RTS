"""
Dataset generator for GNN training and evaluation.
Risk labels come from future deadline events in no-intervention rollouts.
"""

from typing import List, Dict, Tuple, Any, Optional
import torch
from rts_predictive.config import PredictiveRuntimeConfig
from rts_predictive.simulator.engine import DiscreteEventSimulator
from rts_predictive.simulator.tasks import TaskState
from rts_predictive.schedulers.local_fifo import LocalFIFOScheduler
from rts_predictive.gnn.graph_builder import HeteroGraphBuilder


class RolloutSample:
    """A single graph training sample with ground-truth rollout labels."""
    def __init__(
        self,
        x: torch.Tensor,
        edge_index: torch.Tensor,
        y_risk: float,
        y_ttv: float,
        y_cause: int,
        device_id: str,
        timestamp_ms: float,
        ttv_observed: bool,
    ):
        self.x = x
        self.edge_index = edge_index
        self.y_risk = torch.tensor([[y_risk]], dtype=torch.float32)
        self.y_ttv = torch.tensor([[y_ttv]], dtype=torch.float32)
        self.y_cause = torch.tensor([y_cause], dtype=torch.long)
        self.device_id = device_id
        self.timestamp_ms = timestamp_ms
        self.ttv_observed = ttv_observed


class RolloutDatasetGenerator:
    """Generates labeled dataset samples directly from simulator rollouts."""

    def __init__(self, config: Optional[PredictiveRuntimeConfig] = None):
        self.config = config or PredictiveRuntimeConfig()

    def generate_split(
        self,
        seeds: List[int],
        sim_duration_ms: float = 300.0,
        sample_interval_ms: float = 20.0
    ) -> List[RolloutSample]:
        """Runs simulations across given seeds and extracts labeled graph snapshots."""
        samples: List[RolloutSample] = []
        lookahead_ms = self.config.gnn_lookahead_horizon_ms

        for seed in seeds:
            sim = DiscreteEventSimulator(config=self.config, seed=seed, fleet_size=4)
            sim.schedule_periodic_tasks(duration_ms=sim_duration_ms)

            # Inject controlled contention bursts on some nodes
            sim.schedule_contention_burst(
                target_device_id="Device_1",
                start_time_ms=50.0,
                duration_ms=100.0,
                cpu_load=0.85,
                gpu_load=0.95
            )
            sim.schedule_contention_burst(
                target_device_id="Device_2",
                start_time_ms=120.0,
                duration_ms=80.0,
                cpu_load=0.90,
                gpu_load=0.80
            )

            scheduler = LocalFIFOScheduler()
            sim.attach_scheduler(scheduler)
            pending = []

            # Advance simulation step by step, sampling graphs
            current_time = 0.0
            while current_time < sim_duration_ms - lookahead_ms:
                # Run small slice
                next_time = current_time + sample_interval_ms
                sim.run(duration_ms=next_time)
                current_time = sim.current_time_ms

                # For each device, capture graph snapshot
                for dev_id, dev in sim.devices.items():
                    if not dev.ready_queue and not dev.running_tasks:
                        continue

                    active_now = list(dev.running_tasks) + list(dev.ready_queue)

                    # Determine dominant cause attribution
                    cpu_u = dev.resources.get_effective_cpu_utilization()
                    gpu_u = dev.resources.get_effective_gpu_utilization()
                    mem_p = dev.resources.get_memory_pressure()

                    if gpu_u > 0.8 and gpu_u >= cpu_u:
                        y_cause = 1  # GPU
                    elif cpu_u > 0.8:
                        y_cause = 0  # CPU
                    elif mem_p > 0.85:
                        y_cause = 2  # Memory
                    else:
                        y_cause = 3  # Queue / Network

                    for task in active_now:
                        if not task.is_critical:
                            continue
                        x, edge_index, _ = HeteroGraphBuilder.build_graph(
                            dev, current_time, focus_task_id=task.instance_id
                        )
                        pending.append((x, edge_index, task.instance_id, y_cause,
                                        dev_id, current_time))

            # Continue the same unmodified rollout to observe future outcomes.
            sim.run(duration_ms=sim_duration_ms)
            misses = {
                event["task_id"]: event["timestamp_ms"]
                for event in sim.telemetry_log
                if event["event"] == "DEADLINE_MISSED"
            }
            for x, edge_index, task_id, y_cause, dev_id, sampled_at in pending:
                future = [
                    miss_time for missed_task_id, miss_time in misses.items()
                    if missed_task_id == task_id
                    and sampled_at < miss_time <= sampled_at + lookahead_ms
                ]
                observed = bool(future)
                first_miss_time = min(future) if observed else sampled_at + lookahead_ms
                samples.append(RolloutSample(
                    x=x, edge_index=edge_index,
                    y_risk=float(observed),
                    y_ttv=(first_miss_time - sampled_at) / 1000.0,
                    y_cause=y_cause, device_id=dev_id,
                    timestamp_ms=sampled_at, ttv_observed=observed,
                ))

        return samples

    def build_dataset(
        self,
        train_seeds: List[int] = [101, 102, 103, 104, 105],
        val_seeds: List[int] = [201, 202],
        test_seeds: List[int] = [301, 302]
    ) -> Tuple[List[RolloutSample], List[RolloutSample], List[RolloutSample]]:
        """Constructs train, validation, and test splits with strictly disjoint seeds."""
        train_data = self.generate_split(train_seeds)
        val_data = self.generate_split(val_seeds)
        test_data = self.generate_split(test_seeds)
        return train_data, val_data, test_data
