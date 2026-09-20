# Predictive Runtime Protection for Distributed Real-Time AI Systems

> **Real-Time Systems (RTS) Research Prototype & Interactive Benchmark Suite**  
> **Authors:** Mayur Raju (24BCS073), P Gnandeep (24BCS095), P Maruthi (24BCS098), P Sanjay (24BCS100), S Sudharsan Reddy (24BCS130)  
> **Course:** Real-Time Systems · **Instructor:** Dr. Swagatika Sahoo  
> **Department:** Computer Science and Engineering  

---

> [!WARNING]
> **Research status:** this repository is currently a demonstration prototype. Existing Section 12 numbers and paper figures are not yet provenance-backed research results and must not be cited as empirical evidence. See [RESEARCH_STATUS.md](RESEARCH_STATUS.md), [Implementation Plan.md](Implementation%20Plan.md), and [UI Design.md](UI%20Design.md).

## Overview

**GhostGuard** is a proactive, low-overhead runtime arbitration and protection framework for distributed fleets of heterogeneous edge nodes (autonomous drones, ground robots, and edge GPU clusters). 

In hard and firm real-time AI systems, unpredictable resource contention (thermal throttling, GPU execution bursts, and wireless channel jitter) causes traditional reactive scheduling policies like Earliest Deadline First (EDF) or Rate Monotonic (RM) to fail unrecoverably.

GhostGuard prevents deadline misses through a **4-Stage Runtime Arbitration Engine**:
1. **Sub-millisecond Graph Risk Estimation:** A compact Graph Neural Network ($T_{\text{infer}} \le 0.35\text{ ms}$) predicts deadline-violation risk stages ahead of time.
2. **Cooperative Offloading:** Intelligently evaluates candidate neighbors across the compute mesh under real-time feasibility constraints ($t + 2\delta_{\text{comm}} + T_{\text{exec}} + \Delta_{\text{margin}} \le D_i$).
3. **Active In-Flight Watchdog:** Monitors in-flight offloaded tasks. If the remote candidate experiences secondary contention, the watchdog aborts remote reliance mid-flight.
4. **Degraded Fallback Prototype:** Activates reduced-cost local inference. The research implementation will bind this action to a configuration-specific Response Time Analysis certificate before describing it as verified.

---

## Legacy Demonstration Output (Section 12 Walkthrough)

The values below are retained to reproduce the original scripted walkthrough. They currently conflict with aggregate simulator output and are not validated experimental results.

Under the Section 12 deterministic contention failure scenario (Device 1 contention burst at $t=25\text{ms}$, neighbor shock at $t=45\text{ms}$):

| Scheduler Policy | Total Misses | Critical Misses | DMR (%) | WCRT (ms) | Jitter (ms) | Fallbacks | Verdict |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Local-FIFO** | 19 | 12 | 13.2% | 104.8 | 21.4 | 0 | Severe Safety Failure |
| **RM-Local** | 14 | 9 | 9.7% | 91.5 | 17.8 | 0 | Unrecoverable Misses |
| **EDF-Local (Baseline)** | 11 | 8 | 7.6% | 86.2 | 15.5 | 0 | Reactive Contention Collapse |
| **Always-Offload** | 8 | 6 | 5.6% | 72.4 | 14.2 | 0 | Mesh & Queue Saturation |
| **Reactive-Degrade** | 5 | 3 | 3.5% | 48.0 | 12.1 | 12 | Triggers Too Late (Slack Depleted) |
| **GhostGuard (Proposed)** | **0** | **0** | **0.0%** | **18.2** | **8.4** | **44** | **Scripted demonstration value** |

---

## Quick Start & Verification

### 1. Environment Setup (Virtual Environment)
The project is configured to use the local virtual environment `.venv`:

```powershell
# Activate the virtual environment
.venv\Scripts\Activate.ps1
```

### 2. Launch the Interactive Decoupled Web Dashboard
Launch the high-performance, single-page web dashboard (FastAPI + HTML5 Canvas + Plotly.js) featuring an interactive multi-node distributed mesh topology (4, 6, or 8 nodes with live CPU/GPU/thermal tooltips), synchronized dual-timeline Gantt chart, and millisecond milestone scrubber:

```powershell
python scripts/run_web.py
```
> The dashboard will automatically launch at `http://localhost:8000`. Alternatively, run headless with `python scripts/run_server.py`.

### 3. Generate Publication Plots & LaTeX Tables
To rerun the deterministic benchmark suite, evaluate formal RTA proofs, and regenerate all publication figures (300-DPI PNG + vector PDF) and LaTeX tables:

```powershell
python scripts/generate_paper_artifacts.py
```
* **Publication Figures:** Saved to `results/plots/` (`fig1_timeline_trace`, `fig2_dmr_comparison`, `fig3_latency_cdf`, `fig4_gnn_overhead`).
* **LaTeX Tables & Paper Extracts:** Saved to `results/paper/` (`table1_benchmark_summary.tex`, `table2_rta_verification.tex`, `PAPER_DATA.json`, `PAPER_EXTRACTS.md`).

### 4. Run Automated Test Suite
Verify 100% test passage across the simulation engine, GNN model, federated learning, and paper artifacts:

```powershell
python -m pytest tests/
```

---

## Autonomous AI Pipeline Task Specification

| Task Stage $\tau_i$ | Criticality | Period $T_i$ | Deadline $D_i$ | Nominal WCET $C_i$ | Degraded WCET $C_i^{\text{deg}}$ | Fallback Mechanism |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Sense** | Critical | 20.0 ms | 20.0 ms | 3.0 ms | 1.5 ms | Downsampled frame capture |
| **ObstacleDetection** | Critical | 20.0 ms | 20.0 ms | 8.0 ms | 2.5 ms | Bounding-sphere LiDAR filter |
| **Perception** | Medium | 33.0 ms | 33.0 ms | 15.0 ms | 5.0 ms | MobileNet-Tiny INT8 Quantized |
| **Tracking** | Medium | 50.0 ms | 50.0 ms | 12.0 ms | 4.0 ms | Pruned Linear Kalman Filter |
| **PathPlanning** | Medium | 50.0 ms | 50.0 ms | 14.0 ms | 4.5 ms | Coarse Grid A* Search |
| **Actuation** | Critical | 10.0 ms | 10.0 ms | 2.0 ms | 1.0 ms | Direct feed-forward command |
| **BackgroundLogging** | Low | 100.0 ms | 100.0 ms | 5.0 ms | 0.0 ms | Suspended under fallback |

---

## Formal Timing Verification

Degraded mode schedulability is verified via exact Response Time Analysis (RTA):
$$R_i = C_i^{\text{deg}} + \sum_{j \in hp(i)} \left\lceil \frac{R_i}{T_j} \right\rceil C_j^{\text{deg}} \le D_i$$

For the critical **Perception** pipeline stage:
* Degraded WCET $C^{\text{deg}} = 5.0\text{ ms}$
* Interference from higher priority tasks ($hp$):
  $$\left\lceil \frac{33.0}{20.0} \right\rceil \times 1.5\text{ ms (Sense)} + \left\lceil \frac{33.0}{20.0} \right\rceil \times 2.5\text{ ms (Obstacle)} + \left\lceil \frac{33.0}{10.0} \right\rceil \times 1.0\text{ ms (Actuation)} = 3.0 + 5.0 + 4.0 = 12.0\text{ ms}$$
* Worst-Case Response Time:
  $$R_{\text{Perception}} = 5.0 + 12.0 + 1.2\text{ ms (scheduler overhead)} = 18.2\text{ ms} \le 33.0\text{ ms}$$
* **Legacy analytical example:** the displayed $+14.8\text{ ms}$ margin is not yet produced by an exact configuration-bound certificate and must be recomputed by the research-grade analyzer.

---

## Repository Structure

```
d:/Course/RTS2/
├── frontend/                      # Decoupled Single-Page Web Dashboard (HTML5, Tailwind, Plotly.js)
│   ├── index.html                 # 4-Section streamlined command center layout
│   └── app.js                     # 60 FPS scrubber, SVG mesh animator, Gantt timeline
├── ghostguard/
│   ├── api/                       # Lightweight FastAPI REST & static file server
│   │   └── server.py              # Endpoints: /api/simulate, /api/section12, /api/health
│   ├── config.py                  # Real-time task profiles & hardware classes
│   ├── experiments/
│   │   ├── plotting.py            # 300-DPI PNG and vector PDF plotting suite
│   │   ├── scenarios.py           # Deterministic contention scenario generators
│   │   └── runner.py              # Automated experiment testbed
│   ├── federated/                 # FedAvg latency modeling across nodes
│   ├── gnn/                       # PyTorch Geometric GNN runtime risk predictor
│   ├── schedulers/                # GhostGuard, EDF, RM, FIFO, and Ablations
│   ├── simulator/                 # Discrete-event engine, queues, thermal models
│   └── verification/              # Response Time Analysis (RTA) verification
├── scripts/
│   ├── generate_paper_artifacts.py # Generates publication plots, LaTeX tables, and JSON
│   ├── run_web.py                 # Launches FastAPI server and opens browser dashboard
│   ├── run_server.py              # Starts FastAPI server on port 8000
│   └── run_demo_scenario.py       # Terminal execution of Section 12 scenario
├── results/
│   ├── plots/                     # Publication figures (fig1 to fig4) in PNG and PDF
│   └── paper/                     # LaTeX tables (table1, table2) and PAPER_DATA.json
└── tests/                         # 24 passing PyTest verification suites
```
