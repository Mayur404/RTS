# PredictiveRuntime System Architecture

## 1. Overview
PredictiveRuntime is a predictive runtime protection framework designed for distributed fleets of heterogeneous edge devices (autonomous drones, robots, and smart edge nodes). Real-time AI mission pipelines operate under strict timing deadlines ($D_i$) where exceeding a deadline leads to critical failures (e.g., missed collision avoidance, delayed control actuation).

```
+-----------------------------------------------------------------------------------------+
|                                    PREDICTIVE_RUNTIME NODE                                      |
|                                                                                         |
|   +---------------------------------------------------------------------------------+   |
|   |                       Real-Time Multi-Stage AI Pipeline                         |   |
|   |  Sense (20ms) -> Detect (20ms) -> Perception (33ms) -> Track (50ms) -> Plan ... |   |
|   +---------------------------------------------------------------------------------+   |
|                                            |                                            |
|                                            v                                            |
|   +---------------------------------------------------------------------------------+   |
|   |                         Heterogeneous Graph Constructor                         |   |
|   |  Nodes: Task Instances & Physical Resources (CPU, GPU, Memory, Network)         |   |
|   |  Edges: Data Dependencies, Resource Allocations, Computational Contention       |   |
|   +---------------------------------------------------------------------------------+   |
|                                            |                                            |
|                                            v                                            |
|   +---------------------------------------------------------------------------------+   |
|   |              Predictive Graph Neural Network (GNN) Runtime Monitor              |   |
|   |  Outputs: (1) Deadline Miss Risk p in [0, 1]                                    |   |
|   |           (2) Estimated Time-to-Violation Delta t_viol (seconds)                |   |
|   |           (3) Dominant Contention Bottleneck (CPU, GPU, Thermal, Queue)         |   |
|   +---------------------------------------------------------------------------------+   |
|                                            |                                            |
|                                            v                                            |
|   +---------------------------------------------------------------------------------+   |
|   |                      Three-Way Predictive Decision Engine                       |   |
|   |                                                                                 |   |
|   |   Risk <= tau_risk ?                                                            |   |
|   |   ├── YES ───────────────────────────────────────> [ Local Execution (EDF/RM) ] |   |
|   |   └── NO                                                                        |   |
|   |        │                                                                        |   |
|   |        v                                                                        |   |
|   |   Candidate Neighbor Evaluation (FL Model):                                     |   |
|   |   delta_comm + T_exec,j + Margin <= Deadline ?                                  |   |
|   |   ├── Safe Candidate Found ─────────────────────> [ Cooperative Offloading ]    |   |
|   |   │                                                        |                    |   |
|   |   │                                                        v (Active Monitoring)|   |
|   |   │                                              Remote Target Degraded?        |   |
|   |   │                                                ├── NO  -> Success           |   |
|   |   │                                                └── YES -> [ ABANDON &       |   |
|   |   │                                                             FALLBACK ]      |   |
|   |   └── No Safe Candidate Found ──────────────────> [ Verified Local Fallback ]   |   |
|   |                                                   (Analytical Timing Check:     |   |
|   |                                                    WCET_deg + I_bound <= D)     |   |
|   +---------------------------------------------------------------------------------+   |
+-----------------------------------------------------------------------------------------+
                                             ^
                                             | (Asynchronous parameter updates)
+-----------------------------------------------------------------------------------------+
|                         Decentralized Federated Learning (FedAvg)                       |
|   - Clients train locally on private execution traces (Workload, Load -> T_exec, Success)|
|   - Central server performs FedAvg weight aggregation without centralizing raw data     |
+-----------------------------------------------------------------------------------------+
```

---

## 2. Mathematical Timing & Schedulability Formulations

### 2.1 Dynamic Task Model
Each task instance $\tau_{i,k}$ released at time $r_{i,k}$ is characterized by:
$$\text{Deadline: } d_{i,k} = r_{i,k} + D_i$$
$$\text{Dynamic Slack: } S_i(t) = d_{i,k} - t - c_i(t)$$
$$\text{Response Time: } R_{i,k} = f_{i,k} - r_{i,k}$$
$$\text{Lateness: } L_{i,k} = f_{i,k} - d_{i,k}$$

A deadline violation occurs whenever $f_{i,k} > d_{i,k}$ ($L_{i,k} > 0$).

### 2.2 Cooperative Offload Feasibility
When offloading task $\tau_i$ to neighbor $d_j$, the total predicted completion time is:
$$\hat{T}_{\text{total}} = 2 \cdot \delta_{ij}(\text{payload}_i) + \hat{T}_{\text{exec}, j}(\tau_i)$$
where $\delta_{ij}$ accounts for transmission delay and base link latency:
$$\delta_{ij} = \delta_{\text{base}} + \frac{8 \cdot \text{payload}_i}{\text{bandwidth}_{ij}} + \text{jitter}$$

Offloading is permitted if and only if:
$$t + \hat{T}_{\text{total}} + \Delta_{\text{margin}} \le d_i \quad \land \quad \text{Reliability}(d_j) \ge \tau_{\text{rel}}$$

### 2.3 Verified Fallback Schedulability
Under degraded mode, non-critical logging tasks are suspended, and the critical task executes with a verified worst-case bound $C_i^{\text{deg}}$.
Schedulability is verified if:
$$C_i^{\text{deg}} + I_i^{\text{bound}} \le D_i \quad \land \quad U^{\text{deg}} = \sum_{j \neq \text{suspended}} \frac{C_j^{\text{deg}}}{T_j} \le 1.0$$
where $I_i^{\text{bound}} = \sum_{j \in hp(i)} \lceil \frac{D_i}{T_j} \rceil C_j^{\text{deg}}$.
