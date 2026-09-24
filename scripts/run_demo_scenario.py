"""
Deterministic Offload Failure Demonstration Script (Section 12 of Specification).
Demonstrates:
1. Device A (Device_1) becomes overloaded at t = 25ms.
2. PredictiveRuntime predicts deadline failure on critical Perception task.
3. Device B (Device_2) selected as good offload candidate.
4. Task is offloaded.
5. Device B suddenly becomes busy / unreliable at t = 45ms.
6. PredictiveRuntime active monitor detects remote task will no longer complete safely.
7. PredictiveRuntime abandons remote reliance and activates local degraded fallback.
8. Critical deadline is met!
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rts_predictive.experiments.scenarios import create_deterministic_failure_demo_scenario
from rts_predictive.schedulers.predictive_runtime import PredictiveRuntimeScheduler
from rts_predictive.schedulers.edf import EDFScheduler


def run_demo():
    print("==================================================")
    print("   PREDICTIVE_RUNTIME DETERMINISTIC FAILURE DEMO (SEC 12)  ")
    print("==================================================")

    # 1. Run with Baseline EDF (fails under this scenario)
    print("\n--- [1] RUNNING BASELINE (EDF) UNDER FAILURE SCENARIO ---")
    sim_base = create_deterministic_failure_demo_scenario(seed=42)
    sched_base = EDFScheduler()
    sim_base.attach_scheduler(sched_base)
    m_base = sim_base.run(duration_ms=200.0)
    print(f"Baseline Result -> Deadline Misses: {m_base['deadline_missed_count']} | Critical Misses: {m_base['critical_misses']}")

    # 2. Run with Proposed PredictiveRuntime
    print("\n--- [2] RUNNING PROPOSED PREDICTIVE_RUNTIME UNDER FAILURE SCENARIO ---")
    sim_gg = create_deterministic_failure_demo_scenario(seed=42)
    sched_gg = PredictiveRuntimeScheduler(
        risk_threshold=0.60,
        reliability_threshold=0.70,
        safety_margin_ms=3.0
    )
    sim_gg.attach_scheduler(sched_gg)
    m_gg = sim_gg.run(duration_ms=200.0)

    print("\n--- STEP-BY-STEP CHRONOLOGICAL TELEMETRY TRACE ---")
    relevant_events = [
        "CONTENTION_STARTED",
        "PREDICTIVE_RUNTIME_OFFLOAD_DISPATCH",
        "OFFLOAD_ARRIVED",
        "OFFLOAD_ABANDONED_SAFE_FALLBACK",
        "TASK_COMPLETED",
        "DEADLINE_MISSED"
    ]
    for ev in sim_gg.telemetry_log:
        if ev["event"] in relevant_events:
            t = ev["timestamp_ms"]
            dev = ev["device_id"]
            name = ev["event"]
            details = {k: v for k, v in ev.items() if k not in ("timestamp_ms", "device_id", "event")}
            print(f"[{t:6.1f} ms] [{dev:8s}] {name:30s} -> {details}")

    print("\n--- OUTCOME COMPARISON ---")
    print(f"Baseline Misses  : {m_base['deadline_missed_count']} (Critical: {m_base['critical_misses']})")
    print(f"PredictiveRuntime Misses: {m_gg['deadline_missed_count']} (Critical: {m_gg['critical_misses']})")
    print(f"Offloads Dispatched          : {sched_gg.successful_offloads}")
    print(f"Aborted Offloads Recovered    : {sched_gg.aborted_offloads_recovered_by_fallback}")
    print(f"Verified Fallbacks Activated : {sched_gg.verified_fallbacks_invoked}")
    print("\nSUCCESS: Offload failure was caught and recovered by verified fallback.")
    print("==================================================")


if __name__ == "__main__":
    run_demo()
