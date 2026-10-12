"""
PredictiveRuntime System Configuration and Hyperparameters.
Centralizes real-time timing bounds, task profiles, hardware classes,
GNN architecture parameters, federated learning settings, and decision thresholds.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class TaskProfile:
    """Specification of a Real-Time AI pipeline task."""
    name: str
    period_ms: float
    deadline_ms: float
    wcet_ms: float               # Nominal worst-case execution time
    degraded_wcet_ms: float      # WCET under degraded fallback mode
    is_critical: bool
    is_offloadable: bool
    requires_gpu: bool
    cpu_util_fraction: float     # Nominal fraction of CPU required
    gpu_util_fraction: float     # Nominal fraction of GPU required
    memory_mb: float             # Memory working set in MB
    data_payload_kb: float       # Offload transmission payload size in KB
    priority: int = 1            # Priority (higher number = higher priority for fixed priority)
    degraded_description: str = "Reduced model / resolution"


# Default autonomous robot/drone AI pipeline task profiles
DEFAULT_TASK_PROFILES: Dict[str, TaskProfile] = {
    "Sense": TaskProfile(
        name="Sense",
        period_ms=20.0,
        deadline_ms=20.0,
        wcet_ms=3.0,
        degraded_wcet_ms=1.5,
        is_critical=True,
        is_offloadable=False,     # Sensor acquisition must remain local
        requires_gpu=False,
        cpu_util_fraction=0.15,
        gpu_util_fraction=0.0,
        memory_mb=128.0,
        data_payload_kb=0.0,
        priority=10,
        degraded_description="Downsampled frame capture (15fps)"
    ),
    "ObstacleDetection": TaskProfile(
        name="ObstacleDetection",
        period_ms=20.0,
        deadline_ms=20.0,
        wcet_ms=8.0,
        degraded_wcet_ms=2.5,
        is_critical=True,
        is_offloadable=True,
        requires_gpu=True,
        cpu_util_fraction=0.25,
        gpu_util_fraction=0.45,
        memory_mb=256.0,
        data_payload_kb=8.0,
        priority=9,
        degraded_description="Bounding-sphere LiDAR filter"
    ),
    "Perception": TaskProfile(
        name="Perception",
        period_ms=33.0,
        deadline_ms=33.0,
        wcet_ms=15.0,
        degraded_wcet_ms=5.0,
        is_critical=True,
        is_offloadable=True,
        requires_gpu=True,
        cpu_util_fraction=0.30,
        gpu_util_fraction=0.60,
        memory_mb=512.0,
        data_payload_kb=16.0,
        priority=8,
        degraded_description="MobileNet-Tiny INT8 Quantized"
    ),
    "Tracking": TaskProfile(
        name="Tracking",
        period_ms=50.0,
        deadline_ms=50.0,
        wcet_ms=12.0,
        degraded_wcet_ms=4.0,
        is_critical=False,
        is_offloadable=True,
        requires_gpu=False,
        cpu_util_fraction=0.25,
        gpu_util_fraction=0.0,
        memory_mb=128.0,
        data_payload_kb=4.0,
        priority=6,
        degraded_description="Linear Kalman Filter with pruned tracks"
    ),
    "PathPlanning": TaskProfile(
        name="PathPlanning",
        period_ms=50.0,
        deadline_ms=50.0,
        wcet_ms=14.0,
        degraded_wcet_ms=4.5,
        is_critical=True,
        is_offloadable=True,
        requires_gpu=True,
        cpu_util_fraction=0.35,
        gpu_util_fraction=0.30,
        memory_mb=256.0,
        data_payload_kb=8.0,
        priority=7,
        degraded_description="Greedy 2D waypoint heuristic"
    ),
    "Actuation": TaskProfile(
        name="Actuation",
        period_ms=10.0,
        deadline_ms=10.0,
        wcet_ms=2.0,
        degraded_wcet_ms=1.0,
        is_critical=True,
        is_offloadable=False,     # Motor control must execute locally
        requires_gpu=False,
        cpu_util_fraction=0.10,
        gpu_util_fraction=0.0,
        memory_mb=64.0,
        data_payload_kb=0.0,
        priority=11,             # Highest priority
        degraded_description="Direct PID safety clamp"
    ),
    "BackgroundLogging": TaskProfile(
        name="BackgroundLogging",
        period_ms=100.0,
        deadline_ms=100.0,
        wcet_ms=8.0,
        degraded_wcet_ms=0.0,     # Can be completely suspended
        is_critical=False,
        is_offloadable=False,
        requires_gpu=False,
        cpu_util_fraction=0.10,
        gpu_util_fraction=0.0,
        memory_mb=64.0,
        data_payload_kb=0.0,
        priority=1,              # Lowest priority
        degraded_description="Completely suspended during contention"
    ),
}


@dataclass
class HardwareProfile:
    """Hardware capability and configuration of a simulated compute node."""
    name: str
    cpu_speed_multiplier: float   # 1.0 = baseline, 1.5 = 50% faster, 0.7 = slower
    gpu_speed_multiplier: float
    total_memory_mb: float
    bandwidth_mbps: float         # Network link bandwidth in megabits/sec
    base_latency_ms: float        # Base link latency to neighbors
    thermal_sensitivity: float    # How fast throttling triggers under load (0.0 to 1.0)


HARDWARE_PROFILES: Dict[str, HardwareProfile] = {
    "Drone-Heavy": HardwareProfile(
        name="Drone-Heavy",
        cpu_speed_multiplier=1.3,
        gpu_speed_multiplier=1.4,
        total_memory_mb=2048.0,
        bandwidth_mbps=50.0,
        base_latency_ms=2.5,
        thermal_sensitivity=0.2
    ),
    "Drone-Standard": HardwareProfile(
        name="Drone-Standard",
        cpu_speed_multiplier=1.0,
        gpu_speed_multiplier=1.0,
        total_memory_mb=1024.0,
        bandwidth_mbps=40.0,
        base_latency_ms=3.0,
        thermal_sensitivity=0.4
    ),
    "Drone-Light": HardwareProfile(
        name="Drone-Light",
        cpu_speed_multiplier=0.75,
        gpu_speed_multiplier=0.70,
        total_memory_mb=512.0,
        bandwidth_mbps=30.0,
        base_latency_ms=4.0,
        thermal_sensitivity=0.6
    ),
    "Ground-Rover": HardwareProfile(
        name="Ground-Rover",
        cpu_speed_multiplier=1.6,
        gpu_speed_multiplier=1.8,
        total_memory_mb=4096.0,
        bandwidth_mbps=80.0,
        base_latency_ms=2.0,
        thermal_sensitivity=0.1
    ),
    "Jetson-Orin-Nano": HardwareProfile(
        name="Jetson-Orin-Nano",
        cpu_speed_multiplier=1.0,
        gpu_speed_multiplier=1.1,
        total_memory_mb=8192.0,
        bandwidth_mbps=60.0,
        base_latency_ms=2.5,
        thermal_sensitivity=0.35
    ),
    "Jetson-AGX-Orin": HardwareProfile(
        name="Jetson-AGX-Orin",
        cpu_speed_multiplier=1.8,
        gpu_speed_multiplier=2.2,
        total_memory_mb=16384.0,
        bandwidth_mbps=120.0,
        base_latency_ms=1.5,
        thermal_sensitivity=0.15
    ),
    "Edge-GPU-Server": HardwareProfile(
        name="Edge-GPU-Server",
        cpu_speed_multiplier=1.5,
        gpu_speed_multiplier=1.8,
        total_memory_mb=12288.0,
        bandwidth_mbps=100.0,
        base_latency_ms=2.0,
        thermal_sensitivity=0.20
    ),
    "Raspberry-Pi-5": HardwareProfile(
        name="Raspberry-Pi-5",
        cpu_speed_multiplier=0.6,
        gpu_speed_multiplier=0.4,
        total_memory_mb=4096.0,
        bandwidth_mbps=30.0,
        base_latency_ms=4.0,
        thermal_sensitivity=0.50
    ),
    "Jetson-Xavier-NX": HardwareProfile(
        name="Jetson-Xavier-NX",
        cpu_speed_multiplier=1.2,
        gpu_speed_multiplier=1.3,
        total_memory_mb=8192.0,
        bandwidth_mbps=50.0,
        base_latency_ms=2.8,
        thermal_sensitivity=0.30
    ),
    "Coral-Edge-TPU": HardwareProfile(
        name="Coral-Edge-TPU",
        cpu_speed_multiplier=0.8,
        gpu_speed_multiplier=1.0,
        total_memory_mb=2048.0,
        bandwidth_mbps=40.0,
        base_latency_ms=3.2,
        thermal_sensitivity=0.25
    ),
    "Robot-Arm-MCU": HardwareProfile(
        name="Robot-Arm-MCU",
        cpu_speed_multiplier=0.5,
        gpu_speed_multiplier=0.2,
        total_memory_mb=1024.0,
        bandwidth_mbps=25.0,
        base_latency_ms=4.5,
        thermal_sensitivity=0.40
    ),
    "Vision-Sensor-Node": HardwareProfile(
        name="Vision-Sensor-Node",
        cpu_speed_multiplier=0.9,
        gpu_speed_multiplier=0.8,
        total_memory_mb=4096.0,
        bandwidth_mbps=45.0,
        base_latency_ms=3.0,
        thermal_sensitivity=0.35
    ),
}

NODE_FLEET_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "id": "Device_1",
        "name": "Node 1: Jetson Orin Nano",
        "role": "Primary Origin / Ingress",
        "hardware_profile": "Jetson-Orin-Nano",
        "color": "#3B82F6",
        "x": 200,
        "y": 210,
    },
    {
        "id": "Device_2",
        "name": "Node 2: Jetson AGX Orin",
        "role": "Candidate Compute Host",
        "hardware_profile": "Jetson-AGX-Orin",
        "color": "#10B981",
        "x": 600,
        "y": 210,
    },
    {
        "id": "Device_3",
        "name": "Node 3: Generic Edge GPU",
        "role": "Secondary Offload Peer",
        "hardware_profile": "Edge-GPU-Server",
        "color": "#8B5CF6",
        "x": 400,
        "y": 80,
    },
    {
        "id": "Device_4",
        "name": "Node 4: Raspberry Pi 5",
        "role": "Low-Power Sensor Hub",
        "hardware_profile": "Raspberry-Pi-5",
        "color": "#EC4899",
        "x": 400,
        "y": 340,
    },
    {
        "id": "Device_5",
        "name": "Node 5: Jetson Xavier NX",
        "role": "Auxiliary Edge Worker",
        "hardware_profile": "Jetson-Xavier-NX",
        "color": "#F59E0B",
        "x": 90,
        "y": 90,
    },
    {
        "id": "Device_6",
        "name": "Node 6: Coral Edge TPU",
        "role": "Auxiliary Edge Worker",
        "hardware_profile": "Coral-Edge-TPU",
        "color": "#06B6D4",
        "x": 710,
        "y": 90,
    },
    {
        "id": "Device_7",
        "name": "Node 7: Robot Arm Controller",
        "role": "Auxiliary Edge Worker",
        "hardware_profile": "Robot-Arm-MCU",
        "color": "#14B8A6",
        "x": 90,
        "y": 330,
    },
    {
        "id": "Device_8",
        "name": "Node 8: High-Res Vision Node",
        "role": "Auxiliary Edge Worker",
        "hardware_profile": "Vision-Sensor-Node",
        "color": "#A855F7",
        "x": 710,
        "y": 330,
    },
]


@dataclass
class PredictiveRuntimeConfig:
    """Global configuration for simulator, GNN, FL, and Decision Engine."""
    # Simulator parameters
    simulation_duration_ms: float = 1000.0
    tick_step_ms: float = 0.5
    default_seed: int = 42
    default_fleet_size: int = 6

    # GNN Parameters
    gnn_node_features_dim: int = 9
    gnn_hidden_dim: int = 32
    gnn_lookahead_horizon_ms: float = 30.0   # How far ahead to predict deadline misses
    gnn_learning_rate: float = 0.003
    gnn_epochs: int = 25
    gnn_batch_size: int = 32

    # Federated Learning Parameters
    fl_num_rounds: int = 5
    fl_local_epochs: int = 3
    fl_learning_rate: float = 0.005
    fl_feature_dim: int = 6

    # Decision Engine Parameters
    risk_threshold_tau: float = 0.60         # Risk score >= 0.60 triggers offload evaluation
    reliability_threshold_tau: float = 0.70  # Minimum neighbor reliability score
    safety_margin_ms: float = 3.0           # Margin buffer required for offload acceptance

    # Baseline names
    schedulers: List[str] = field(default_factory=lambda: [
        "local_fifo",
        "edf",
        "rm",
        "reactive_fallback",
        "always_offload",
        "predictive_no_fallback",
        "rts_predictive",
    ])
