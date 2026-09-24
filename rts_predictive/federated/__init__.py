"""
Federated Learning Package for Cross-Device Execution and Reliability Modeling.
Implements Client Local Training, FedAvg Server Aggregation,
and Centralized Upper-Bound Benchmarking.
"""

from rts_predictive.federated.model import DeviceExecutionReliabilityModel
from rts_predictive.federated.client import FederatedClient
from rts_predictive.federated.server import FedAvgServer

__all__ = [
    "DeviceExecutionReliabilityModel",
    "FederatedClient",
    "FedAvgServer",
]
