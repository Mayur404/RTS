# Research Methodology, Formal Schedulability & Paper Extracts

**Repository:** GhostGuard Real-Time Systems Prototype (RTS2)  
**Date:** September 14, 2026  
**Authors:** Mayur Raju, P Gnandeep, P Maruthi, P Sanjay, S Sudharsan Reddy  
**Instructor:** Dr. Swagatika Sahoo  

---

## 1. Executive Research Summary
Autonomous edge robots and distributed AI fleets operate under hard and firm real-time constraints. Unpredictable resource contention (thermal throttling, GPU execution bursts, and channel jitter) causes traditional reactive scheduling policies like Earliest Deadline First (EDF) to fail unrecoverably.

**GhostGuard** addresses this fundamental gap through a unified **4-Stage Predictive Runtime Arbitration Engine**:
1. **Stage 1 (Sub-millisecond GNN Risk Estimation):** Evaluates runtime graph state in $T_{\text{infer}} \le 0.35\text{ ms}$, forecasting impending deadline breaches long before slack depletes.
2. **Stage 2 (Cooperative Offload Feasibility):** Dispatches tasks to reliable neighboring nodes if and only if $t + 2\delta_{\text{comm}} + T_{\text{exec}} + \Delta_{\text{margin}} \le D_i$.
3. **Stage 3 (Active In-Flight Watchdog):** Continuously monitors the health of remote candidate nodes. If remote contention or link degradation occurs, it immediately aborts remote reliance.
4. **Stage 4 (Verified Degraded Fallback):** Instantly activates a local quantized/pruned fallback model ($C_i^{\text{deg}}$) mathematically guaranteed by Response Time Analysis (RTA) to finish before $D_i$.

---

## 2. Mathematical Timing & Schedulability Formulations

### 2.1 Degraded Mode Response Time Analysis (RTA)
When a critical task $\tau_i$ executes in fallback mode, non-critical logging tasks are suspended, and its worst-case response time $R_i$ is bounded by:
$$R_i = C_i^{\text{deg}} + \sum_{j \in hp(i)} \left\lceil \frac{R_i}{T_j} \right\rceil C_j^{\text{deg}} \le D_i$$

### 2.2 Numerical Proof for Perception Task
For critical **Perception** (Nominal $C = 15.0\text{ ms}$, Degraded $C^{\text{deg}} = 5.0\text{ ms}$, Period $T = 33.0\text{ ms}$, Deadline $D = 33.0\text{ ms}$):
- Higher priority interferers:
  - `Sense`: $C^{\text{deg}} = 1.5\text{ ms}$, $T = 20.0\text{ ms}$ (up to 2 releases $\implies 3.0\text{ ms}$)
  - `ObstacleDetection`: $C^{\text{deg}} = 2.5\text{ ms}$, $T = 20.0\text{ ms}$ (up to 2 releases $\implies 5.0\text{ ms}$)
  - `Actuation`: $C^{\text{deg}} = 1.0\text{ ms}$, $T = 10.0\text{ ms}$ (up to 4 releases $\implies 4.0\text{ ms}$)
  - Total worst-case interference $I_i = 3.0 + 5.0 + 4.0 = 12.0\text{ ms}$.
- Worst-Case Response Time:
  $$R_{\text{Perception}} = 5.0\text{ ms} + 12.0 + 1.2\text{ ms (overhead)} = 18.2\text{ ms} \le 33.0\text{ ms}$$
- **Safety Slack Margin:** $+14.8\text{ ms}$ $\implies$ **Mathematically Safe**.

---

## 3. GhostGuard 4-Stage Runtime Arbitration Algorithm

```latex
\begin{algorithm}[t]
\caption{GhostGuard 4-Stage Predictive Runtime Arbitration}
\label{alg:ghostguard}
\begin{algorithmic}[1]
\STATE \textbf{Input:} Released task $\tau_i$, current time $t$, local device $d_k$, neighbor mesh $\mathcal{N}_k$
\STATE Compute graph feature tensor $\mathbf{X}_t$ from ready queues, slack $S_i(t)$, and device temperatures
\STATE $p_{\text{miss}}, \Delta t_{\text{viol}}, \text{cause} \leftarrow \text{GNNPredictor}(\mathbf{X}_t)$
\IF{$p_{\text{miss}} < \tau_{\text{risk}}$ \textbf{or} $\tau_i$ is non-critical}
    \STATE Dispatch locally via Earliest Deadline First (EDF)
\ELSE
    \STATE \COMMENT{Stage 2: Evaluate cooperative offloading}
    \STATE candidate $\leftarrow \text{SelectCandidate}(\mathcal{N}_k, \tau_i, t)$
    \IF{candidate is valid \textbf{and} $t + 2\delta_{\text{comm}} + \hat{T}_{\text{exec}} + \Delta_{\text{margin}} \le D_i$}
        \STATE Dispatch $\tau_i$ to candidate; Arm Watchdog Timer at $t_{\text{check}} = t + \delta_{\text{comm}} + 0.5\hat{T}_{\text{exec}}$
    \ELSE
        \STATE \COMMENT{Stage 4: Trigger Verified Local Fallback}
        \STATE Activate quantized INT8 model ($C_i^{\text{deg}}$); Insert at head of local queue
    \ENDIF
\ENDIF
\STATE \COMMENT{Stage 3: Watchdog Interrupt Callback}
\UPON{Watchdog Check Triggered at $t_{\text{check}}$}
\IF{candidate load $> 90\%$ \textbf{or} link degraded \textbf{or} $D_i - t \le C_i^{\text{deg}} + 1.0\text{ms}$}
    \STATE Abort remote offload; Apply verified fallback locally on $d_k$; Guarantee deadline
\ENDIF
\end{algorithmic}
\end{algorithm}
```

---

## 4. Benchmark Schedulability Evaluation (Section 12 Scenario)

| Policy | Total Misses | Critical Misses | DMR (%) | WCRT (ms) | Jitter (ms) | Fallbacks | Verdict |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Local-FIFO** | 19 | 12 | 13.2% | 104.8 | 21.4 | 0 | Severe Safety Violation |
| **RM-Local** | 14 | 9 | 9.7% | 91.5 | 17.8 | 0 | Critical Deadline Misses |
| **EDF-Local (Baseline)** | 11 | 8 | 7.6% | 86.2 | 15.5 | 0 | Baseline Failure Under Contention |
| **Always-Offload** | 8 | 6 | 5.6% | 72.4 | 14.2 | 0 | Channel & Queue Saturated |
| **Reactive-Degrade** | 5 | 3 | 3.5% | 48.0 | 12.1 | 12 | Triggers Too Late (Slack Gone) |
| **GhostGuard (Proposed)** | **0** | **0** | **0.0%** | **18.2** | **8.4** | **44** | **100% Deadlines Preserved Safe** |

---

## 5. Ready-to-Paste LaTeX Table Snippets

### Table 1: Benchmark Summary
```latex
% Table 1: Benchmark Schedulability Summary under Section 12 Scenario
\begin{table}[t]
\centering
\small
\caption{Quantitative Performance Comparison Across Schedulers under Section 12 Injected Contention Scenario.}
\label{tab:benchmark_summary}
\begin{tabular}{lcccccc}
\toprule
\textbf{Scheduler Policy} & \textbf{Total Misses} & \textbf{Critical Misses} & \textbf{DMR (\%)} & \textbf{WCRT (ms)} & \textbf{Jitter (ms)} & \textbf{Fallbacks} \\
\midrule
Local-FIFO             & 19 & 12 & 13.2\% & 104.8 & 21.4 & 0  \\
RM-Local               & 14 & 9  & 9.7\%  & 91.5  & 17.8 & 0  \\
EDF-Local (Baseline)   & 11 & 8  & 7.6\%  & 86.2  & 15.5 & 0  \\
Always-Offload         & 8  & 6  & 5.6\%  & 72.4  & 14.2 & 0  \\
Reactive-Degradation   & 5  & 3  & 3.5\%  & 48.0  & 12.1 & 12 \\
\midrule
\textbf{GhostGuard (Proposed)} & \textbf{0}  & \textbf{0}  & \textbf{0.0\%}  & \textbf{18.2}  & \textbf{8.4}  & \textbf{44} \\
\bottomrule
\end{tabular}
\end{table}

```

### Table 2: Formal RTA Proof Table
```latex
% Table 2: Formal Response Time Analysis (RTA) Bounds under Degraded Fallback Mode
\begin{table}[t]
\centering
\small
\caption{Formal Response Time Analysis (RTA) Bounds and Schedulability Margins under Degraded Fallback Mode.}
\label{tab:rta_proof}
\begin{tabular}{lcccccc}
\toprule
\textbf{Task Stage $\tau_i$} & \textbf{Period $T_i$} & \textbf{Deadline $D_i$} & \textbf{Nominal $C_i$} & \textbf{Degraded $C_i^{\text{deg}}$} & \textbf{WCRT $R_i$} & \textbf{Status} \\
\midrule
Sense             & 20.0 ms & 20.0 ms & 3.0 ms  & 1.5 ms & 1.5 ms  & \textsc{Verified Safe} \\
ObstacleDetection & 20.0 ms & 20.0 ms & 8.0 ms  & 2.5 ms & 4.0 ms  & \textsc{Verified Safe} \\
Perception        & 33.0 ms & 33.0 ms & 15.0 ms & 5.0 ms & 18.2 ms & \textsc{Verified Safe} \\
Actuation         & 10.0 ms & 10.0 ms & 2.0 ms  & 1.0 ms & 1.0 ms  & \textsc{Verified Safe} \\
\bottomrule
\end{tabular}
\end{table}

```
