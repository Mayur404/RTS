"""
Federated Learning Package for Cross-Device Execution and Reliability Modeling.
Implements Client Local Training, FedAvg Server Aggregation,
and Centralized Upper-Bound Benchmarking.
"""

from ghostguard.federated.model import DeviceExecutionReliabilityModel
from ghostguard.federated.client import FederatedClient
from ghostguard.federated.server import FedAvgServer

__all__ = [
    "DeviceExecutionReliabilityModel",
    "FederatedClient",
    "FedAvgServer",
]
