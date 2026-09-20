"""
Analytical Timing Verification for Real-Time Fallback Configurations.
Performs Response-Time Analysis (RTA) and Utilization Bound checks to verify that
degraded fallback modes preserve critical deadlines under stated assumptions.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
from ghostguard.config import TaskProfile, DEFAULT_TASK_PROFILES


@dataclass
class VerificationResult:
    """Result of analytical timing verification under explicit assumptions."""
    is_verified: bool
    status_statement: str
    nominal_utilization: float
    degraded_utilization: float
    interference_bound_ms: float
    worst_case_response_time_ms: float
    critical_deadline_ms: float
    assumptions: List[str]


class TimingAnalyzer:
    """Analytical verification engine for degraded fallback configurations."""

    @classmethod
    def verify_fallback_mode(
        cls,
        critical_task_name: str,
        task_profiles: Optional[Dict[str, TaskProfile]] = None,
        scheduler_type: str = "EDF"
    ) -> VerificationResult:
        """
        Analytically checks whether invoking the degraded fallback guarantees:
        WCET_deg + Interference_bound <= Deadline
        under specified scheduling assumptions.
        """
        profiles = task_profiles or DEFAULT_TASK_PROFILES
        crit_profile = profiles.get(critical_task_name)

        if not crit_profile:
            return VerificationResult(
                is_verified=False,
                status_statement="Task profile not found",
                nominal_utilization=0.0,
                degraded_utilization=0.0,
                interference_bound_ms=0.0,
                worst_case_response_time_ms=0.0,
                critical_deadline_ms=0.0,
                assumptions=[]
            )

        # 1. Compute Nominal Utilization
        u_nom = sum(p.wcet_ms / p.period_ms for p in profiles.values())

        # 2. Compute Degraded Mode Utilization
        # Non-critical background task suspended, others degraded
        u_deg = 0.0
        for name, p in profiles.items():
            if name == "BackgroundLogging":
                continue  # Disabled under fallback
            c_eff = p.degraded_wcet_ms if (p.is_critical or name == critical_task_name) else p.wcet_ms
            u_deg += (c_eff / p.period_ms)

        # 3. Compute Worst-Case Interference Bound on Critical Task
        # High priority or earlier deadline tasks interfering: Sense (1.5ms), Actuation (1.0ms)
        c_deg = crit_profile.degraded_wcet_ms
        interference = 0.0
        for name, p in profiles.items():
            if name != critical_task_name and p.is_critical and p.period_ms <= crit_profile.period_ms:
                # Up to ceil(D_crit / T_interferer) releases can interfere
                releases = -(-crit_profile.deadline_ms // p.period_ms)
                interference += releases * p.degraded_wcet_ms

        wcrt = c_deg + interference
        is_verified = (wcrt <= crit_profile.deadline_ms) and (u_deg <= 1.0)

        assumptions = [
            "Discrete preemption allowed at subtask boundaries",
            "Non-critical BackgroundLogging task completely suspended during degradation",
            f"Sensor acquisition operates at downsampled degraded WCET ({profiles['Sense'].degraded_wcet_ms} ms)",
            f"Degraded {critical_task_name} WCET bounded at {c_deg} ms",
            "Zero kernel context switch overhead assumption in base formulation",
        ]

        if is_verified:
            statement = "Fallback VERIFIED under current configured timing assumptions"
        else:
            statement = "Timing bound violated: WCRT exceeds deadline under current parameters"

        return VerificationResult(
            is_verified=is_verified,
            status_statement=statement,
            nominal_utilization=round(u_nom, 3),
            degraded_utilization=round(u_deg, 3),
            interference_bound_ms=round(interference, 2),
            worst_case_response_time_ms=round(wcrt, 2),
            critical_deadline_ms=crit_profile.deadline_ms,
            assumptions=assumptions
        )
