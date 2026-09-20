# Experimental Evaluation & Ablation Suite

## 1. Experimental Setup
The GhostGuard evaluation harness systematically evaluates 7 distinct scheduling paradigms under deterministic, seed-controlled simulation workloads:

1. **Local-FIFO:** Tasks execute in First-In-First-Out order locally.
2. **EDF-Local:** Earliest Deadline First uniprocessor dynamic priority algorithm.
3. **RM-Local:** Rate Monotonic static priority scheduling (shorter period = higher priority).
4. **Reactive-Degradation:** Standard EDF with reactive degradation only triggered *after* severe contention or deadline miss is observed.
5. **Always-Offload:** Naive cooperative offloading to available neighbors without deadline safety checking.
6. **Predictive-NoFallback:** GNN-based deadline risk prediction triggering offload, but lacking active monitoring and local fallback.
7. **GhostGuard (Proposed):** Full three-way predictive arbitration with active remote monitoring and analytically verified degraded fallback.

---

## 2. Evaluation Metrics

### Primary Metrics
- **Deadline Miss Ratio (%):** $\frac{\text{Missed Deadlines}}{\text{Total Released Tasks}}$
- **Violations Prevented:** Reduction in missed deadlines compared with baseline.
- **Worst-Case Response Time (WCRT):** Maximum observed duration from release to completion ($R_{\max}$).
- **Prediction Lead Time:** Mean duration in milliseconds between GNN risk alert and projected deadline violation.

### Secondary Metrics
- **Response Time Jitter (ms):** Standard deviation of task response times.
- **Offload Success Rate (%):** Proportion of offloaded tasks that successfully complete before their deadline.
- **Fallback Recovery Rate (%):** Proportion of in-flight degraded offloads rescued by verified local fallback.

---

## 3. Ablation Studies
To demonstrate the empirical necessity of each component, the harness evaluates six ablations:
- **Full-GhostGuard:** Baseline complete model.
- **w/o GNN:** Predictive GNN replaced by static queue-length heuristic threshold.
- **w/o Federated Learning:** Offload execution estimator replaced by nominal hardware clock assumption without load calibration.
- **w/o Offloading:** Predictive local fallback only; no cooperative task sharing.
- **w/o Fallback:** Predictive offloading only; no active monitoring or fallback recovery.
- **w/o Neighbor Reliability:** Offloading without historical reliability tracking.
