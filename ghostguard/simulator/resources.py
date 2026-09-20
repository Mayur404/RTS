"""
Resource Management and Contention Models for Real-Time Compute Nodes.
Models CPU, GPU, Memory, Network, and Thermal Throttling proxy.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional
from ghostguard.config import HardwareProfile


@dataclass
class ResourceUsageSnapshot:
    cpu_utilization: float      # 0.0 to 1.0 (or > 1.0 when oversubscribed)
    gpu_utilization: float      # 0.0 to 1.0
    memory_used_mb: float
    memory_pressure: float      # 0.0 to 1.0
    thermal_throttling_factor: float  # 1.0 = nominal, < 1.0 = throttled
    temperature_celsius: float
    network_tx_load_mbps: float


class ResourceManager:
    """Manages physical compute and communication resources of a single node."""

    def __init__(self, hardware: HardwareProfile, ambient_temp_c: float = 35.0):
        self.hw = hardware
        self.ambient_temp_c = ambient_temp_c
        self.temperature_c = ambient_temp_c
        self.thermal_throttle_threshold_c = 75.0
        self.thermal_cutoff_c = 90.0

        # Dynamic load states
        self.active_cpu_load: float = 0.0
        self.active_gpu_load: float = 0.0
        self.active_memory_mb: float = 0.0
        self.injected_cpu_stress: float = 0.0
        self.injected_gpu_stress: float = 0.0
        self.injected_memory_stress_mb: float = 0.0
        self.injected_network_drop_prob: float = 0.0
        self.injected_network_extra_delay_ms: float = 0.0

    def inject_stress(
        self,
        cpu_load: float = 0.0,
        gpu_load: float = 0.0,
        memory_mb: float = 0.0,
        network_delay_ms: float = 0.0,
        network_drop_prob: float = 0.0
    ):
        """Injects dynamic computational contention or network degradation."""
        self.injected_cpu_stress = max(0.0, cpu_load)
        self.injected_gpu_stress = max(0.0, gpu_load)
        self.injected_memory_stress_mb = max(0.0, memory_mb)
        self.injected_network_extra_delay_ms = max(0.0, network_delay_ms)
        self.injected_network_drop_prob = min(1.0, max(0.0, network_drop_prob))

    def clear_stress(self):
        self.injected_cpu_stress = 0.0
        self.injected_gpu_stress = 0.0
        self.injected_memory_stress_mb = 0.0
        self.injected_network_drop_prob = 0.0
        self.injected_network_extra_delay_ms = 0.0

    def update_thermal_state(self, delta_time_ms: float):
        """Simulates thermal buildup and cooling using a first-order thermal differential."""
        total_load = (self.get_effective_cpu_utilization() + self.get_effective_gpu_utilization()) / 2.0
        target_temp = self.ambient_temp_c + (total_load * 50.0 * self.hw.thermal_sensitivity)
        cooling_rate = 0.001 * delta_time_ms
        heating_rate = 0.002 * delta_time_ms * self.hw.thermal_sensitivity

        if target_temp > self.temperature_c:
            self.temperature_c += (target_temp - self.temperature_c) * min(1.0, heating_rate)
        else:
            self.temperature_c -= (self.temperature_c - target_temp) * min(1.0, cooling_rate)

        self.temperature_c = max(self.ambient_temp_c, min(105.0, self.temperature_c))

    def get_thermal_throttling_factor(self) -> float:
        """Returns processing speed multiplier due to thermal state [0.4 to 1.0]."""
        if self.temperature_c <= self.thermal_throttle_threshold_c:
            return 1.0
        overshoot = self.temperature_c - self.thermal_throttle_threshold_c
        max_overshoot = self.thermal_cutoff_c - self.thermal_throttle_threshold_c
        throttle = 1.0 - (0.6 * min(1.0, overshoot / max(1.0, max_overshoot)))
        return max(0.4, throttle)

    def get_effective_cpu_utilization(self) -> float:
        return self.active_cpu_load + self.injected_cpu_stress

    def get_effective_gpu_utilization(self) -> float:
        return self.active_gpu_load + self.injected_gpu_stress

    def get_effective_memory_mb(self) -> float:
        return self.active_memory_mb + self.injected_memory_stress_mb

    def get_memory_pressure(self) -> float:
        return min(1.0, self.get_effective_memory_mb() / max(1.0, self.hw.total_memory_mb))

    def calculate_effective_speed(self, requires_gpu: bool) -> float:
        """
        Calculates effective execution speed multiplier for a task
        accounting for hardware class, thermal throttling, and resource saturation.
        """
        base_mult = self.hw.gpu_speed_multiplier if requires_gpu else self.hw.cpu_speed_multiplier
        thermal_factor = self.get_thermal_throttling_factor()
        mem_pressure = self.get_memory_pressure()

        # Memory bus saturation penalty
        mem_penalty = 1.0 if mem_pressure < 0.8 else max(0.5, 1.0 - (mem_pressure - 0.8) * 2.0)

        # Contention concurrency slowdown if oversubscribed
        contention_mult = 1.0
        if requires_gpu:
            gpu_u = self.get_effective_gpu_utilization()
            if gpu_u > 1.0:
                contention_mult = 1.0 / gpu_u
        else:
            cpu_u = self.get_effective_cpu_utilization()
            if cpu_u > 1.0:
                contention_mult = 1.0 / cpu_u

        return base_mult * thermal_factor * mem_penalty * contention_mult

    def estimate_network_delay_ms(self, payload_kb: float, target_hw: Optional[HardwareProfile] = None) -> float:
        """Calculates transmission delay over simulated ad-hoc wireless mesh link."""
        eff_bandwidth = min(self.hw.bandwidth_mbps, target_hw.bandwidth_mbps if target_hw else self.hw.bandwidth_mbps)
        tx_time_ms = (payload_kb * 8.0) / (eff_bandwidth * 1000.0 / 1000.0) # KB -> bits / (Mbps -> bits/ms)
        # Add latency
        total_delay = self.hw.base_latency_ms + tx_time_ms + self.injected_network_extra_delay_ms
        return max(0.5, total_delay)

    def snapshot(self) -> ResourceUsageSnapshot:
        return ResourceUsageSnapshot(
            cpu_utilization=round(self.get_effective_cpu_utilization(), 3),
            gpu_utilization=round(self.get_effective_gpu_utilization(), 3),
            memory_used_mb=round(self.get_effective_memory_mb(), 1),
            memory_pressure=round(self.get_memory_pressure(), 3),
            thermal_throttling_factor=round(self.get_thermal_throttling_factor(), 3),
            temperature_celsius=round(self.temperature_c, 1),
            network_tx_load_mbps=round(self.hw.bandwidth_mbps, 1)
        )
