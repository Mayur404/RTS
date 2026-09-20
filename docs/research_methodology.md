# Research Methodology: GhostGuard

## 1. Research Question & Core Hypothesis
- **Research Question:** Can a predictive arbitration policy that selectively routes real-time workloads between local execution, cooperative offloading, and a verified local fallback reduce deadline violations across distributed edge fleets operating under computational contention and uncertain wireless links?
- **Hypothesis:** GhostGuard's proactive offload monitoring and verified fallback can reduce deadline misses relative to blind cooperative offloading while preserving critical timing safety when an offload target becomes unreliable mid-flight. Reactive degradation remains an explicit benchmark rather than an assumed weaker policy.

---

## 2. Methodology & Experimental Rigor

### 2.1 Absence of Data Leakage
- The dataset is generated procedurally directly from discrete-event simulation rollouts.
- Strict train/validation/test splits are enforced using disjoint sets of random seeds:
  - Training seeds: 101–105
  - Validation seeds: 201–202
  - Testing seeds: 301–302
- Graph features $G(t)$ capture only the past and instantaneous queue/resource state; the label $y(t)$ is computed from future execution trajectory within lookahead window $H = 30$ ms.

### 2.2 Discrete-Event Real-Time Systems Simulation
- Rather than ungrounded latency approximations, the simulator implements true RTS principles:
  - Task periods ($T_i$), release timestamps ($r_i$), deadlines ($D_i$), and WCETs ($C_i$).
  - Dynamic contention modeling: CPU concurrency, GPU stream multiplexing, memory bus saturation, and thermal throttling.
  - Inter-node wireless mesh transmission delay:
    $$\delta_{\text{comm}} = \text{base\_latency} + \frac{\text{payload\_kb} \times 8}{\text{bandwidth\_mbps} \times 1000} + \text{jitter}$$
  - Active monitoring: heartbeat callbacks intercept degraded remote execution before the deadline expires.

### 2.3 Decentralized Federated Learning
- Heterogeneous edge nodes log execution tuples $(x_k, t_{\text{exec}}, \text{success})$.
- Local model parameter updates $\Delta \theta_k$ are trained privately on client devices.
- Central server performs Federated Averaging (FedAvg):
  $$\theta^{(t+1)} = \sum_{k=1}^K \frac{n_k}{N} \theta_k^{(t+1)}$$
- No raw traces or proprietary operational timings are ever transmitted over the network.
- Compared against a privacy-violating centralized pooled-data reference; this is a diagnostic comparison, not a guaranteed upper bound.

### 2.4 Analytical Timing Verification of Fallback
- Fallback configurations are verified under explicit assumptions:
  - WCET of degraded task ($C_{\text{deg}}$)
  - Higher-priority task interference bound ($I_{\text{bound}}$)
  - Verification condition: $C_{\text{deg}} + I_{\text{bound}} \le D_{\text{crit}}$
- Dashboard and runtime telemetry report: *"Fallback VERIFIED under current configured timing assumptions"* rather than unproven guarantees.
