"""Versioned integer-time specifications for the layered research engine."""
from dataclasses import dataclass, replace, field
from .serialization import CanonicalHashMixin
from .specs import (PipelineSpec, TaskSpec, WcetDistributionSpec, ResourceDemand,
                    ResourceKind, Criticality, PreemptionMode, ReleaseModel,
                    ExitPointSpec, create_autonomous_ai_pipeline_spec)
from .lifecycle import ExecutionAttempt

PPM = 1_000_000
GPU_CPU_RESERVATION_PPM = 150_000
CPU_TASK_MEMORY_MB = 32
GPU_TASK_MEMORY_MB = 128
TRACE_AUDIT_SCHEMA_VERSION = "research-trace-audit/1.0"


@dataclass(frozen=True)
class ResearchDevice(CanonicalHashMixin):
    device_id: str
    name: str
    kind: str
    cpu_speed_ppm: int
    gpu_speed_ppm: int
    memory_mb: int = 2048
    bandwidth_mbps: int = 60

    def __post_init__(self):
        for name in ("cpu_speed_ppm", "gpu_speed_ppm", "memory_mb", "bandwidth_mbps"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True)
class ResearchFault(CanonicalHashMixin):
    device_id: str
    start_us: int
    end_us: int
    cpu_ppm: int = 0
    gpu_ppm: int = 0
    extra_link_us: int = 0
    loss_ppm: int = 0

    def __post_init__(self):
        for name in ("start_us","end_us","cpu_ppm","gpu_ppm","extra_link_us","loss_ppm"):
            value=getattr(self,name)
            if isinstance(value,bool) or not isinstance(value,int) or value<0:raise ValueError(f"invalid {name}")
        if not 0 <= self.start_us < self.end_us:
            raise ValueError("invalid fault interval")
        if any(not 0 <= x <= PPM for x in (self.cpu_ppm, self.gpu_ppm, self.loss_ppm)):
            raise ValueError("fault fractions must be within capacity")


@dataclass(frozen=True)
class ResearchConfig(CanonicalHashMixin):
    schema_version: str = "rts_predictive.research-config/1.0"
    seed: int = 1000
    family: str = "bursty"
    release_end_us: int = 1_200_000
    drain_us: int = 300_000
    devices: tuple[ResearchDevice, ...] = ()
    workflows: tuple[PipelineSpec, ...] = ()
    faults: tuple[ResearchFault, ...] = ()
    layer_count: int = 4
    dispatch_cost_us: int = 40
    inference_cost_us: int = 250
    training_work_us_per_sample: int = 120
    aggregation_cost_us: int = 1000
    fl_period_us: int = 300_000
    watchdog_period_us: int = 2000
    base_link_us: int = 800
    jitter_us: int = 400
    loss_ppm: int = 10_000
    retry_limit: int = 2
    margin_us: int = 1000
    host_inference_budget_us: int = 10_000
    enforce_host_inference_budget: bool = False

    def __post_init__(self):
        for name in ("seed","release_end_us","drain_us","layer_count","dispatch_cost_us","inference_cost_us",
                     "training_work_us_per_sample","aggregation_cost_us","fl_period_us","watchdog_period_us",
                     "base_link_us","jitter_us","loss_ppm","retry_limit","margin_us","host_inference_budget_us"):
            value=getattr(self,name)
            if isinstance(value,bool) or not isinstance(value,int) or value<0:
                raise ValueError(f"{name} must be non-negative integer")
        if self.host_inference_budget_us <= 0 or type(self.enforce_host_inference_budget) is not bool:
            raise ValueError("positive host inference budget and boolean enforcement required")
        if self.seed < 0 or self.release_end_us <= 0 or self.drain_us <= 0:
            raise ValueError("seed and horizons must be valid")
        if self.layer_count < 2 or self.watchdog_period_us <= 0 or self.fl_period_us <= 0:
            raise ValueError("layer/period settings must be positive")
        ids = {d.device_id for d in self.devices}
        if not ids or len(ids) != len(self.devices) or not self.workflows:
            raise ValueError("unique devices and workflows are required")
        if any(f.device_id not in ids for f in self.faults):
            raise ValueError("unknown fault device")
        if self.loss_ppm>PPM:
            raise ValueError("loss exceeds one")
        if len({w.pipeline_id for w in self.workflows})!=len(self.workflows):
            raise ValueError("workflow identifiers must be unique")
        if any(w.release_model is not ReleaseModel.PERIODIC for w in self.workflows):
            raise ValueError("research engine supports periodic workflows")
        if any(w.drop_policy.value!="drop_job" for w in self.workflows):
            raise ValueError("research engine requires firm workflow drops")
        if any(t.wcet_distribution.kind not in {"constant","uniform"} for w in self.workflows for t in w.tasks):
            raise ValueError("research engine supports constant and uniform execution demand")
        if any(d.cpu_speed_ppm <= 0 or d.gpu_speed_ppm <= 0 or d.memory_mb <= 0
               or d.bandwidth_mbps <= 0 for d in self.devices):
            raise ValueError("invalid hardware capacity")
        if self.drain_us < max(w.end_to_end_deadline_us for w in self.workflows):
            raise ValueError("drain must cover every workflow deadline")

    @property
    def end_us(self):
        return self.release_end_us + self.drain_us


def _cpu_task(name, work, period, deadline, critical=True, priority=5):
    return TaskSpec(name, (ResourceDemand(ResourceKind.CPU, 1.0),), deadline,
                    WcetDistributionSpec("uniform", max(1, work * 4 // 5), work, work),
                    criticality=Criticality.HIGH if critical else Criticality.LOW,
                    period_us=period, priority=priority,
                    preemption_mode=PreemptionMode.PREEMPTIVE)


def default_research_config(seed=1000, family="bursty", release_end_us=1_200_000):
    if family not in {"nominal", "bursty", "thermal", "unreliable"}:
        raise ValueError("unknown scenario family")
    fleet = (ResearchDevice("Device_1", "Scout drone", "drone", PPM, 1_100_000),
             ResearchDevice("Device_2", "Edge server", "server", 1_800_000, 2_200_000, 8192, 120),
             ResearchDevice("Device_3", "Ground rover", "rover", 1_200_000, 1_000_000),
             ResearchDevice("Device_4", "Robot arm", "arm", 1_100_000, 1_300_000))
    base = create_autonomous_ai_pipeline_spec(period_us=90_000, end_to_end_deadline_us=80_000)
    tasks = tuple(replace(t, relative_deadline_us=70_000 if t.task_id != "Actuation" else 10_000,
                          wcet_distribution=replace(t.wcet_distribution, kind="uniform"),
                          result_payload_bytes=512 if t.offloadable else 0)
                  for t in base.tasks)
    autonomy = replace(base, pipeline_id="autonomy", tasks=tasks, dependency_edges=(
        ("Sense", "ObstacleDetection"), ("Sense", "Perception"),
        ("ObstacleDetection", "Tracking"), ("Perception", "Tracking"),
        ("Tracking", "PathPlanning"), ("PathPlanning", "Actuation")))
    control = PipelineSpec("control", (_cpu_task("StateEstimate", 900, 20_000, 8000, priority=12),
                                       _cpu_task("ServoControl", 500, 20_000, 5000, priority=13)),
                           (("StateEstimate", "ServoControl"),), ReleaseModel.PERIODIC,
                           10_000, "ServoControl", period_us=20_000)
    telemetry = PipelineSpec("telemetry", (_cpu_task("HealthCheck", 1600, 120_000, 30_000, False, 2),
                                           _cpu_task("MapUpdate", 2200, 120_000, 40_000, False, 2),
                                           _cpu_task("Telemetry", 900, 120_000, 40_000, False, 1)),
                             (("HealthCheck", "MapUpdate"), ("MapUpdate", "Telemetry")),
                             ReleaseModel.PERIODIC, 75_000, "Telemetry", period_us=120_000)
    faults = ()
    if family == "bursty":
        faults = (ResearchFault("Device_1", 80_000, 360_000, 550_000, 880_000),
                  ResearchFault("Device_2", 140_000, 220_000, 650_000, 900_000),
                  ResearchFault("Device_3", 550_000, 820_000, 800_000, 750_000))
    elif family == "thermal":
        faults = (ResearchFault("Device_1", 100_000, 750_000, 400_000, 720_000),)
    elif family == "unreliable":
        faults = (ResearchFault("Device_1", 80_000, 360_000, 550_000, 850_000),
                  ResearchFault("Device_2", 130_000, 420_000, 650_000, 650_000, 3000, 200_000))
    return ResearchConfig(seed=seed, family=family, release_end_us=release_end_us,
                          devices=fleet, workflows=(autonomy, control, telemetry), faults=faults)


@dataclass
class ResearchTask:
    uid: str
    job_id: str
    origin: str
    spec: TaskSpec
    parents: tuple[str, ...]
    status: str = "BLOCKED"
    ready_us: int | None = None
    deadline: int = 0
    demand: int = 0
    current_attempt: str | None = None
    committed_attempt: str | None = None
    degraded: bool = False
    delivered_work: int = 0

    @property
    def gpu(self):
        return any(d.resource is ResourceKind.GPU and d.utilization_fraction > 0 for d in self.spec.resource_demands)

    @property
    def critical(self):
        return self.spec.criticality is Criticality.HIGH

    @property
    def remaining(self):
        # Predictor observes the declared budget and delivered work, not the
        # future sampled execution demand hidden in the simulator.
        return max(0,self.spec.wcet_distribution.wcet_us-self.delivered_work)


@dataclass
class ResearchJob:
    uid: str
    origin: str
    workflow: PipelineSpec
    release: int
    deadline: int
    tasks: dict[str, ResearchTask] = field(default_factory=dict)
    status: str = "ACTIVE"


@dataclass
class ResearchAttemptWork:
    lifecycle: ExecutionAttempt
    task_uid: str
    host: str
    total: int
    remaining: int
    degraded: bool = False
    utility: float = 1.0
    layer: int = 0
    layer_end: int = 0
    work_done: int = 0
    residual: int = 0
    generation: int = 0
    queued: bool = True
    phase: str = "QUEUED"
    compute_time_us: int = 0
    observed_resource: dict = field(default_factory=dict)
    request_arrival_us: int = 0
    fallback_order: int | None = None
    fallback_certificate: dict | None = None
    exit_checkpoint: str | None = None
    output_record: dict | None = None


@dataclass
class ResearchOperation:
    uid: str
    host: str
    kind: str
    remaining: int
    deadline: int
    payload: dict = field(default_factory=dict)
    residual: int = 0
    generation: int = 0
