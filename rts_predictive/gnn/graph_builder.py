"""
Graph Representation Builder for Real-Time AI Task Pipelines and Hardware Resources.
Constructs heterogeneous task-resource graphs suitable for PyTorch Geometric GNN models.
"""

from typing import Dict, List, Tuple, Any, Optional
import torch
from rts_predictive.simulator.device import DeviceNode
from rts_predictive.simulator.tasks import TaskInstance


class HeteroGraphBuilder:
    """Builds graph representations from the live runtime state of a compute node."""

    RESOURCE_NAMES = ["RES_CPU", "RES_GPU", "RES_MEM", "RES_NET"]

    @classmethod
    def build_graph(
        cls,
        dev: DeviceNode,
        current_time_ms: float,
        focus_task_id: Optional[str] = None,
    ) -> Tuple[torch.Tensor, torch.Tensor, Dict[str, int]]:
        """
        Constructs node features X [N, 9] and edge_index E [2, M].
        Returns: (x_tensor, edge_index_tensor, node_to_idx_mapping)
        """
        active_tasks = list(dev.running_tasks) + list(dev.ready_queue)
        # Limit to first 12 tasks to bound graph size
        active_tasks = active_tasks[:12]

        node_map: Dict[str, int] = {}
        node_features: List[List[float]] = []

        # 1. Add Resource Nodes (Indices 0..3)
        res_snapshot = dev.resources.snapshot()
        cpu_u = dev.resources.get_effective_cpu_utilization()
        gpu_u = dev.resources.get_effective_gpu_utilization()
        mem_p = dev.resources.get_memory_pressure()
        therm = dev.resources.get_thermal_throttling_factor()

        # CPU Resource Node
        node_map["RES_CPU"] = len(node_features)
        node_features.append([
            1.0, 0.0, 0.0,
            min(2.0, cpu_u),
            min(1.0, len(dev.ready_queue) / 10.0),
            therm,
            0.0, 0.0, 0.0
        ])

        # GPU Resource Node
        node_map["RES_GPU"] = len(node_features)
        node_features.append([
            0.0, 1.0, 0.0,
            min(2.0, gpu_u),
            min(1.0, sum(1 for t in active_tasks if t.requires_gpu) / 5.0),
            therm,
            0.0, 0.0, 0.0
        ])

        # Memory Resource Node
        node_map["RES_MEM"] = len(node_features)
        node_features.append([
            0.0, 0.0, 1.0,
            min(1.0, mem_p),
            min(1.0, res_snapshot.memory_used_mb / 2048.0),
            0.0, 0.0, 0.0, 0.0
        ])

        # Network Resource Node
        node_map["RES_NET"] = len(node_features)
        node_features.append([
            0.0, 0.0, 0.0,
            min(1.0, dev.resources.hw.bandwidth_mbps / 100.0),
            min(1.0, dev.resources.injected_network_extra_delay_ms / 20.0),
            dev.resources.injected_network_drop_prob,
            0.0, 0.0, 0.0
        ])

        # 2. Add Task Nodes
        for task in active_tasks:
            idx = len(node_features)
            node_map[task.instance_id] = idx
            slack = task.slack_ms(current_time_ms)
            norm_slack = max(-2.0, min(2.0, slack / 50.0))

            node_features.append([
                1.0 if task.is_critical else 0.0,
                1.0 if task.is_offloadable else 0.0,
                1.0 if task.requires_gpu else 0.0,
                task.nominal_wcet_ms / 50.0,
                task.remaining_work_ms / 50.0,
                norm_slack,
                task.priority / 10.0,
                1.0 if task.is_degraded else 0.0,
                1.0 if task.instance_id == focus_task_id else 0.0,
            ])

        # 3. Construct Edges
        src_edges: List[int] = []
        dst_edges: List[int] = []

        cpu_idx = node_map["RES_CPU"]
        gpu_idx = node_map["RES_GPU"]
        mem_idx = node_map["RES_MEM"]

        # Edges between Tasks and Resources
        for task in active_tasks:
            t_idx = node_map[task.instance_id]
            # Task uses CPU
            src_edges.extend([t_idx, cpu_idx])
            dst_edges.extend([cpu_idx, t_idx])

            # Task uses GPU if required
            if task.requires_gpu:
                src_edges.extend([t_idx, gpu_idx])
                dst_edges.extend([gpu_idx, t_idx])

            # Task uses Memory
            src_edges.extend([t_idx, mem_idx])
            dst_edges.extend([mem_idx, t_idx])

        # Task Contention Edges (tasks competing for same GPU or CPU)
        for i in range(len(active_tasks)):
            for j in range(i + 1, len(active_tasks)):
                t1 = active_tasks[i]
                t2 = active_tasks[j]
                if t1.requires_gpu and t2.requires_gpu:
                    idx1 = node_map[t1.instance_id]
                    idx2 = node_map[t2.instance_id]
                    src_edges.extend([idx1, idx2])
                    dst_edges.extend([idx2, idx1])

        # Self-loops for message passing stability
        for i in range(len(node_features)):
            src_edges.append(i)
            dst_edges.append(i)

        x_tensor = torch.tensor(node_features, dtype=torch.float32)
        edge_index = torch.tensor([src_edges, dst_edges], dtype=torch.long)

        return x_tensor, edge_index, node_map
