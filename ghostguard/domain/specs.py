"""Immutable and validated research configuration contracts."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .serialization import CanonicalHashMixin, freeze_mapping, to_canonical_data


SCHEMA_VERSION = "1.0.0"


class Criticality(str, Enum):
    LOW = "low"
    HIGH = "high"


class ResourceKind(str, Enum):
    CPU = "cpu"
    GPU = "gpu"


class PreemptionMode(str, Enum):
    PREEMPTIVE = "preemptive"
    NON_PREEMPTIVE = "non_preemptive"
    CHECKPOINT = "checkpoint"


class ReleaseModel(str, Enum):
    PERIODIC = "periodic"
    SPORADIC = "sporadic"


class DropPolicy(str, Enum):
    DROP_JOB = "drop_job"
    USE_STALE_DATA = "use_stale_data"
    DEGRADED_PATH = "degraded_path"


class InstrumentationLevel(str, Enum):
    MINIMAL = "minimal"
    STANDARD = "standard"
    VERBOSE = "verbose"


class FaultShape(str, Enum):
    STEP = "step"
    RAMP = "ramp"
    PULSE = "pulse"


def _identifier(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _int_us(value: int, field_name: str, *, positive: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer number of microseconds")
    minimum = 1 if positive else 0
    if value < minimum:
        comparator = "positive" if positive else "non-negative"
        raise ValueError(f"{field_name} must be {comparator}")


def _positive_number(value: float, field_name: str, *, allow_zero: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field_name} must be finite")
    invalid = value < 0 if allow_zero else value <= 0
    if invalid:
        raise ValueError(f"{field_name} must be {'non-negative' if allow_zero else 'positive'}")


def _probability(value: float, field_name: str) -> None:
    _positive_number(value, field_name, allow_zero=True)
    if value > 1:
        raise ValueError(f"{field_name} must be between 0 and 1")


@dataclass(frozen=True)
class WcetDistributionSpec(CanonicalHashMixin):
    """A bounded execution-time distribution sampled once per attempt."""

    kind: str
    bcet_us: int
    nominal_us: int
    wcet_us: int
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _identifier(self.kind, "kind")
        for name in ("bcet_us", "nominal_us", "wcet_us"):
            _int_us(getattr(self, name), name, positive=True)
        if not self.bcet_us <= self.nominal_us <= self.wcet_us:
            raise ValueError("execution bounds must satisfy bcet_us <= nominal_us <= wcet_us")
        object.__setattr__(self, "parameters", freeze_mapping(self.parameters))
        to_canonical_data(self.parameters)


@dataclass(frozen=True)
class ResourceDemand(CanonicalHashMixin):
    resource: ResourceKind
    utilization_fraction: float
    memory_bytes: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.resource, ResourceKind):
            object.__setattr__(self, "resource", ResourceKind(self.resource))
        _probability(self.utilization_fraction, "utilization_fraction")
        _int_us(self.memory_bytes, "memory_bytes")


@dataclass(frozen=True)
class ExitPointSpec(CanonicalHashMixin):
    checkpoint_id: str
    elapsed_work_interval_us: tuple[int, int]
    checkpoint_overhead_us: int
    remaining_wcet_us: int
    output_utility: float
    structurally_valid: bool = True

    def __post_init__(self) -> None:
        _identifier(self.checkpoint_id, "checkpoint_id")
        interval = tuple(self.elapsed_work_interval_us)
        if len(interval) != 2:
            raise ValueError("elapsed_work_interval_us must contain (start_us, end_us)")
        _int_us(interval[0], "elapsed_work_interval_us[0]")
        _int_us(interval[1], "elapsed_work_interval_us[1]")
        if interval[1] < interval[0]:
            raise ValueError("elapsed work interval end must not precede its start")
        _int_us(self.checkpoint_overhead_us, "checkpoint_overhead_us")
        _int_us(self.remaining_wcet_us, "remaining_wcet_us")
        _probability(self.output_utility, "output_utility")
        object.__setattr__(self, "elapsed_work_interval_us", interval)


@dataclass(frozen=True)
class TaskSpec(CanonicalHashMixin):
    task_id: str
    resource_demands: tuple[ResourceDemand, ...]
    relative_deadline_us: int
    wcet_distribution: WcetDistributionSpec
    criticality: Criticality = Criticality.LOW
    preemption_mode: PreemptionMode = PreemptionMode.PREEMPTIVE
    period_us: int | None = None
    minimum_interarrival_us: int | None = None
    request_payload_bytes: int = 0
    result_payload_bytes: int = 0
    offloadable: bool = False
    exit_points: tuple[ExitPointSpec, ...] = ()
    output_utility: float = 1.0
    priority: int = 0

    def __post_init__(self) -> None:
        _identifier(self.task_id, "task_id")
        object.__setattr__(self, "resource_demands", tuple(self.resource_demands))
        object.__setattr__(self, "exit_points", tuple(self.exit_points))
        if not self.resource_demands:
            raise ValueError("resource_demands must not be empty")
        if len({demand.resource for demand in self.resource_demands}) != len(self.resource_demands):
            raise ValueError("resource_demands cannot repeat a resource kind")
        _int_us(self.relative_deadline_us, "relative_deadline_us", positive=True)
        if self.period_us is None and self.minimum_interarrival_us is None:
            raise ValueError("period_us or minimum_interarrival_us is required")
        if self.period_us is not None:
            _int_us(self.period_us, "period_us", positive=True)
        if self.minimum_interarrival_us is not None:
            _int_us(self.minimum_interarrival_us, "minimum_interarrival_us", positive=True)
        for name in ("request_payload_bytes", "result_payload_bytes"):
            _int_us(getattr(self, name), name)
        _probability(self.output_utility, "output_utility")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise TypeError("priority must be an integer")
        if not isinstance(self.criticality, Criticality):
            object.__setattr__(self, "criticality", Criticality(self.criticality))
        if not isinstance(self.preemption_mode, PreemptionMode):
            object.__setattr__(self, "preemption_mode", PreemptionMode(self.preemption_mode))
        checkpoint_ids = [point.checkpoint_id for point in self.exit_points]
        if len(checkpoint_ids) != len(set(checkpoint_ids)):
            raise ValueError("exit point checkpoint IDs must be unique within a task")


@dataclass(frozen=True)
class PipelineSpec(CanonicalHashMixin):
    pipeline_id: str
    tasks: tuple[TaskSpec, ...]
    dependency_edges: tuple[tuple[str, str], ...]
    release_model: ReleaseModel
    end_to_end_deadline_us: int
    sink_task_id: str
    period_us: int | None = None
    minimum_interarrival_us: int | None = None
    drop_policy: DropPolicy = DropPolicy.DROP_JOB

    def __post_init__(self) -> None:
        _identifier(self.pipeline_id, "pipeline_id")
        object.__setattr__(self, "tasks", tuple(self.tasks))
        object.__setattr__(
            self,
            "dependency_edges",
            tuple((str(source), str(target)) for source, target in self.dependency_edges),
        )
        if not self.tasks:
            raise ValueError("tasks must not be empty")
        task_ids = [task.task_id for task in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("task IDs must be unique within a pipeline")
        if self.sink_task_id not in task_ids:
            raise ValueError("sink_task_id must identify a pipeline task")
        if not isinstance(self.release_model, ReleaseModel):
            object.__setattr__(self, "release_model", ReleaseModel(self.release_model))
        if not isinstance(self.drop_policy, DropPolicy):
            object.__setattr__(self, "drop_policy", DropPolicy(self.drop_policy))
        _int_us(self.end_to_end_deadline_us, "end_to_end_deadline_us", positive=True)
        if self.release_model is ReleaseModel.PERIODIC:
            if self.period_us is None:
                raise ValueError("periodic pipelines require period_us")
            _int_us(self.period_us, "period_us", positive=True)
        elif self.minimum_interarrival_us is None:
            raise ValueError("sporadic pipelines require minimum_interarrival_us")
        if self.minimum_interarrival_us is not None:
            _int_us(self.minimum_interarrival_us, "minimum_interarrival_us", positive=True)
        self._validate_dag(set(task_ids))

    def _validate_dag(self, task_ids: set[str]) -> None:
        successors = {task_id: [] for task_id in task_ids}
        indegree = {task_id: 0 for task_id in task_ids}
        seen: set[tuple[str, str]] = set()
        for source, target in self.dependency_edges:
            if source not in task_ids or target not in task_ids:
                raise ValueError(f"dependency edge references unknown task: {source!r} -> {target!r}")
            if source == target:
                raise ValueError("a task cannot depend on itself")
            if (source, target) in seen:
                raise ValueError("duplicate dependency edge")
            seen.add((source, target))
            successors[source].append(target)
            indegree[target] += 1

        queue = sorted(task_id for task_id, degree in indegree.items() if degree == 0)
        visited = 0
        while queue:
            current = queue.pop(0)
            visited += 1
            for successor in successors[current]:
                indegree[successor] -= 1
                if indegree[successor] == 0:
                    queue.append(successor)
                    queue.sort()
        if visited != len(task_ids):
            raise ValueError("pipeline dependency graph must be acyclic")
        if successors[self.sink_task_id]:
            raise ValueError("sink_task_id must have no outgoing dependency edges")
        reverse = {task_id: [] for task_id in task_ids}
        for source, target in self.dependency_edges:
            reverse[target].append(source)
        reaches_sink = {self.sink_task_id}
        pending = [self.sink_task_id]
        while pending:
            current = pending.pop()
            for predecessor in reverse[current]:
                if predecessor not in reaches_sink:
                    reaches_sink.add(predecessor)
                    pending.append(predecessor)
        if reaches_sink != task_ids:
            raise ValueError("every pipeline task must have a path to sink_task_id")

    @property
    def task_by_id(self) -> Mapping[str, TaskSpec]:
        return freeze_mapping({task.task_id: task for task in self.tasks})


@dataclass(frozen=True)
class DeviceSpec(CanonicalHashMixin):
    device_id: str
    cpu_capacity: float
    gpu_capacity: float
    cpu_concurrency: int
    gpu_concurrency: int
    memory_bytes: int
    cpu_speed_factor: float = 1.0
    gpu_speed_factor: float = 1.0
    thermal_time_constant_us: int = 1_000_000
    thermal_derating_factor: float = 1.0
    scheduler: str = "fifo"

    def __post_init__(self) -> None:
        _identifier(self.device_id, "device_id")
        for name in ("cpu_capacity", "gpu_capacity", "cpu_speed_factor", "gpu_speed_factor"):
            _positive_number(getattr(self, name), name, allow_zero=name == "gpu_capacity")
        for name in ("cpu_concurrency", "gpu_concurrency", "memory_bytes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < (0 if name == "gpu_concurrency" else 1):
                raise ValueError(f"{name} has an invalid capacity")
        _int_us(self.thermal_time_constant_us, "thermal_time_constant_us", positive=True)
        _positive_number(self.thermal_derating_factor, "thermal_derating_factor")
        if self.thermal_derating_factor > 1:
            raise ValueError("thermal_derating_factor cannot exceed 1")
        _identifier(self.scheduler, "scheduler")


@dataclass(frozen=True)
class LinkSpec(CanonicalHashMixin):
    source_device_id: str
    target_device_id: str
    bandwidth_bps: int
    base_latency_us: int
    jitter_us: tuple[int, int] = (0, 0)
    loss_probability: float = 0.0
    retry_limit: int = 0
    retry_delay_us: int = 0
    availability_probability: float = 1.0

    def __post_init__(self) -> None:
        _identifier(self.source_device_id, "source_device_id")
        _identifier(self.target_device_id, "target_device_id")
        if self.source_device_id == self.target_device_id:
            raise ValueError("links must connect distinct devices")
        _int_us(self.bandwidth_bps, "bandwidth_bps", positive=True)
        _int_us(self.base_latency_us, "base_latency_us")
        jitter = tuple(self.jitter_us)
        if len(jitter) != 2:
            raise ValueError("jitter_us must contain (minimum_us, maximum_us)")
        _int_us(jitter[0], "jitter_us[0]")
        _int_us(jitter[1], "jitter_us[1]")
        if jitter[1] < jitter[0]:
            raise ValueError("jitter maximum must not precede minimum")
        object.__setattr__(self, "jitter_us", jitter)
        _probability(self.loss_probability, "loss_probability")
        _probability(self.availability_probability, "availability_probability")
        if isinstance(self.retry_limit, bool) or not isinstance(self.retry_limit, int) or self.retry_limit < 0:
            raise ValueError("retry_limit must be a non-negative integer")
        _int_us(self.retry_delay_us, "retry_delay_us")


@dataclass(frozen=True)
class FaultSpec(CanonicalHashMixin):
    fault_id: str
    target_id: str
    onset_us: int
    duration_us: int
    shape: FaultShape
    severity: float
    correlation_group: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.fault_id, "fault_id")
        _identifier(self.target_id, "target_id")
        _int_us(self.onset_us, "onset_us")
        _int_us(self.duration_us, "duration_us", positive=True)
        _probability(self.severity, "severity")
        if not isinstance(self.shape, FaultShape):
            object.__setattr__(self, "shape", FaultShape(self.shape))
        if self.correlation_group is not None:
            _identifier(self.correlation_group, "correlation_group")


@dataclass(frozen=True)
class ScenarioSpec(CanonicalHashMixin):
    scenario_id: str
    duration_us: int
    warmup_us: int
    drain_us: int
    devices: tuple[DeviceSpec, ...]
    links: tuple[LinkSpec, ...]
    pipelines: tuple[PipelineSpec, ...]
    faults: tuple[FaultSpec, ...] = ()
    seed: int = 0
    instrumentation_level: InstrumentationLevel = InstrumentationLevel.STANDARD
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _identifier(self.scenario_id, "scenario_id")
        _identifier(self.schema_version, "schema_version")
        for name in ("duration_us", "warmup_us", "drain_us"):
            _int_us(getattr(self, name), name, positive=name == "duration_us")
        for name in ("devices", "links", "pipelines", "faults"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if not self.devices or not self.pipelines:
            raise ValueError("a scenario requires at least one device and one pipeline")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError("seed must be a non-negative integer")
        if not isinstance(self.instrumentation_level, InstrumentationLevel):
            object.__setattr__(self, "instrumentation_level", InstrumentationLevel(self.instrumentation_level))
        device_ids = [device.device_id for device in self.devices]
        if len(device_ids) != len(set(device_ids)):
            raise ValueError("device IDs must be unique")
        device_set = set(device_ids)
        for link in self.links:
            if link.source_device_id not in device_set or link.target_device_id not in device_set:
                raise ValueError("link endpoint is not in the scenario fleet")
        for fault in self.faults:
            if fault.onset_us + fault.duration_us > self.duration_us + self.drain_us:
                raise ValueError("fault extends beyond the simulation and drain horizon")


@dataclass(frozen=True)
class PolicySpec(CanonicalHashMixin):
    policy_name: str
    policy_version: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _identifier(self.policy_name, "policy_name")
        _identifier(self.policy_version, "policy_version")
        _identifier(self.schema_version, "schema_version")
        object.__setattr__(self, "parameters", freeze_mapping(self.parameters))
        to_canonical_data(self.parameters)


@dataclass(frozen=True)
class ExperimentSpec(CanonicalHashMixin):
    experiment_id: str
    scenarios: tuple[ScenarioSpec, ...]
    policies: tuple[PolicySpec, ...]
    seeds: tuple[int, ...]
    repetitions: int
    metrics: tuple[str, ...]
    output_path: str
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _identifier(self.experiment_id, "experiment_id")
        _identifier(self.output_path, "output_path")
        _identifier(self.schema_version, "schema_version")
        for name in ("scenarios", "policies", "seeds", "metrics"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if not self.scenarios or not self.policies or not self.seeds or not self.metrics:
            raise ValueError("scenarios, policies, seeds, and metrics must not be empty")
        if len(self.seeds) != len(set(self.seeds)):
            raise ValueError("experiment seeds must be unique")
        for seed in self.seeds:
            if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
                raise ValueError("experiment seeds must be non-negative integers")
        if isinstance(self.repetitions, bool) or not isinstance(self.repetitions, int) or self.repetitions < 1:
            raise ValueError("repetitions must be a positive integer")
        for metric in self.metrics:
            _identifier(metric, "metric")


def create_autonomous_ai_pipeline_spec(
    pipeline_id: str = "autonomous_pipeline",
    period_us: int = 50_000,
    end_to_end_deadline_us: int = 50_000,
) -> PipelineSpec:
    """Creates the reference 6-stage autonomous robot/UAV AI pipeline DAG specification."""
    sense = TaskSpec(
        task_id="Sense",
        resource_demands=(ResourceDemand(ResourceKind.CPU, 0.15),),
        relative_deadline_us=20_000,
        wcet_distribution=WcetDistributionSpec("constant", 1_500, 3_000, 3_000),
        criticality=Criticality.HIGH,
        preemption_mode=PreemptionMode.PREEMPTIVE,
        period_us=period_us,
        priority=10,
        exit_points=(
            ExitPointSpec(
                checkpoint_id="Sense_Degraded",
                elapsed_work_interval_us=(0, 3_000),
                checkpoint_overhead_us=100,
                remaining_wcet_us=1_500,
                output_utility=0.85,
            ),
        ),
    )
    obstacle = TaskSpec(
        task_id="ObstacleDetection",
        resource_demands=(ResourceDemand(ResourceKind.CPU, 0.25), ResourceDemand(ResourceKind.GPU, 0.45)),
        relative_deadline_us=20_000,
        wcet_distribution=WcetDistributionSpec("constant", 2_500, 8_000, 8_000),
        criticality=Criticality.HIGH,
        preemption_mode=PreemptionMode.PREEMPTIVE,
        period_us=period_us,
        priority=9,
        offloadable=True,
        request_payload_bytes=8_192,
        exit_points=(
            ExitPointSpec(
                checkpoint_id="Obstacle_Degraded",
                elapsed_work_interval_us=(0, 8_000),
                checkpoint_overhead_us=150,
                remaining_wcet_us=2_500,
                output_utility=0.82,
            ),
        ),
    )
    perception = TaskSpec(
        task_id="Perception",
        resource_demands=(ResourceDemand(ResourceKind.CPU, 0.30), ResourceDemand(ResourceKind.GPU, 0.60)),
        relative_deadline_us=33_000,
        wcet_distribution=WcetDistributionSpec("constant", 5_000, 15_000, 15_000),
        criticality=Criticality.HIGH,
        preemption_mode=PreemptionMode.PREEMPTIVE,
        period_us=period_us,
        priority=8,
        offloadable=True,
        request_payload_bytes=16_384,
        exit_points=(
            ExitPointSpec(
                checkpoint_id="Perception_Degraded",
                elapsed_work_interval_us=(0, 15_000),
                checkpoint_overhead_us=200,
                remaining_wcet_us=5_000,
                output_utility=0.79,
            ),
        ),
    )
    tracking = TaskSpec(
        task_id="Tracking",
        resource_demands=(ResourceDemand(ResourceKind.CPU, 0.25),),
        relative_deadline_us=50_000,
        wcet_distribution=WcetDistributionSpec("constant", 4_000, 12_000, 12_000),
        criticality=Criticality.LOW,
        preemption_mode=PreemptionMode.PREEMPTIVE,
        period_us=period_us,
        priority=6,
        offloadable=True,
        request_payload_bytes=4_096,
        exit_points=(
            ExitPointSpec(
                checkpoint_id="Tracking_Degraded",
                elapsed_work_interval_us=(0, 12_000),
                checkpoint_overhead_us=100,
                remaining_wcet_us=4_000,
                output_utility=0.70,
            ),
        ),
    )
    planning = TaskSpec(
        task_id="PathPlanning",
        resource_demands=(ResourceDemand(ResourceKind.CPU, 0.35), ResourceDemand(ResourceKind.GPU, 0.30)),
        relative_deadline_us=50_000,
        wcet_distribution=WcetDistributionSpec("constant", 4_500, 14_000, 14_000),
        criticality=Criticality.HIGH,
        preemption_mode=PreemptionMode.PREEMPTIVE,
        period_us=period_us,
        priority=7,
        offloadable=True,
        request_payload_bytes=8_192,
        exit_points=(
            ExitPointSpec(
                checkpoint_id="Planning_Degraded",
                elapsed_work_interval_us=(0, 14_000),
                checkpoint_overhead_us=150,
                remaining_wcet_us=4_500,
                output_utility=0.80,
            ),
        ),
    )
    actuation = TaskSpec(
        task_id="Actuation",
        resource_demands=(ResourceDemand(ResourceKind.CPU, 0.10),),
        relative_deadline_us=10_000,
        wcet_distribution=WcetDistributionSpec("constant", 1_000, 2_000, 2_000),
        criticality=Criticality.HIGH,
        preemption_mode=PreemptionMode.PREEMPTIVE,
        period_us=period_us,
        priority=11,
        exit_points=(
            ExitPointSpec(
                checkpoint_id="Actuation_Degraded",
                elapsed_work_interval_us=(0, 2_000),
                checkpoint_overhead_us=50,
                remaining_wcet_us=1_000,
                output_utility=0.90,
            ),
        ),
    )

    edges = (
        ("Sense", "ObstacleDetection"),
        ("ObstacleDetection", "Perception"),
        ("Perception", "Tracking"),
        ("Tracking", "PathPlanning"),
        ("PathPlanning", "Actuation"),
    )

    return PipelineSpec(
        pipeline_id=pipeline_id,
        tasks=(sense, obstacle, perception, tracking, planning, actuation),
        dependency_edges=edges,
        release_model=ReleaseModel.PERIODIC,
        period_us=period_us,
        end_to_end_deadline_us=end_to_end_deadline_us,
        sink_task_id="Actuation",
    )

