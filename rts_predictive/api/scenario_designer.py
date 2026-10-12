"""Bounded scenario authoring; compile into existing immutable domain contracts."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictBool

from rts_predictive.domain.research import (
    ResearchConfig, ResearchDevice, ResearchFault, default_research_config,
)
from rts_predictive.domain.specs import (
    TaskSpec, ResourceDemand, ResourceKind, WcetDistributionSpec, PipelineSpec,
    ReleaseModel, Criticality, PreemptionMode, ExitPointSpec,
)


class DesignerModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeviceInput(DesignerModel):
    device_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,39}$")
    name: str = Field(min_length=1, max_length=60)
    kind: Literal["drone", "server", "rover", "arm", "station", "chip"]
    cpu_speed_ppm: StrictInt = Field(ge=10_000, le=10_000_000)
    gpu_speed_ppm: StrictInt = Field(ge=10_000, le=10_000_000)
    memory_mb: StrictInt = Field(ge=1, le=131_072)
    bandwidth_mbps: StrictInt = Field(ge=1, le=10_000)


class ExitInput(DesignerModel):
    checkpoint_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,39}$")
    elapsed_work_interval_us: tuple[StrictInt, StrictInt]
    checkpoint_overhead_us: StrictInt = Field(ge=0, le=1_000_000)
    remaining_wcet_us: StrictInt = Field(ge=1, le=1_000_000)
    output_utility: float = Field(ge=0, le=1, allow_inf_nan=False)
    structurally_valid: StrictBool = True


class TaskInput(DesignerModel):
    task_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,39}$")
    resource: Literal["cpu", "gpu"]
    bcet_us: StrictInt = Field(ge=1, le=1_000_000)
    nominal_us: StrictInt = Field(ge=1, le=1_000_000)
    wcet_us: StrictInt = Field(ge=1, le=1_000_000)
    distribution: Literal["constant", "uniform"] = "uniform"
    relative_deadline_us: StrictInt = Field(ge=1, le=1_000_000)
    criticality: Literal["low", "high"] = "high"
    priority: StrictInt = Field(ge=0, le=100)
    offloadable: StrictBool = False
    request_payload_bytes: StrictInt = Field(default=0, ge=0, le=10_000_000)
    result_payload_bytes: StrictInt = Field(default=0, ge=0, le=10_000_000)
    output_utility: float = Field(default=1, ge=0, le=1, allow_inf_nan=False)
    exit_points: list[ExitInput] = Field(default_factory=list, max_length=8)


class WorkflowInput(DesignerModel):
    pipeline_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,39}$")
    period_us: StrictInt = Field(ge=10_000, le=5_000_000)
    end_to_end_deadline_us: StrictInt = Field(ge=1, le=1_000_000)
    sink_task_id: str
    tasks: list[TaskInput] = Field(min_length=1, max_length=16)
    dependency_edges: list[tuple[str, str]] = Field(max_length=120)


class FaultInput(DesignerModel):
    device_id: str
    start_us: StrictInt = Field(ge=0, le=6_000_000)
    end_us: StrictInt = Field(ge=1, le=6_000_000)
    cpu_ppm: StrictInt = Field(default=0, ge=0, le=1_000_000)
    gpu_ppm: StrictInt = Field(default=0, ge=0, le=1_000_000)
    extra_link_us: StrictInt = Field(default=0, ge=0, le=1_000_000)
    loss_ppm: StrictInt = Field(default=0, ge=0, le=1_000_000)


class ScenarioInput(DesignerModel):
    schema_version: Literal["research-designer/1.0"] = "research-designer/1.0"
    seed: StrictInt = Field(default=1000, ge=0, le=2**63-1)
    family: Literal["nominal", "bursty", "thermal", "unreliable"] = "nominal"
    release_end_us: StrictInt = Field(default=1_200_000, ge=100_000, le=5_000_000)
    drain_us: StrictInt = Field(default=300_000, ge=1, le=1_000_000)
    devices: list[DeviceInput] = Field(min_length=1, max_length=8)
    workflows: list[WorkflowInput] = Field(min_length=1, max_length=6)
    faults: list[FaultInput] = Field(default_factory=list, max_length=32)
    layer_count: Literal[4] = 4
    dispatch_cost_us: StrictInt = Field(default=40, ge=0, le=100_000)
    inference_cost_us: StrictInt = Field(default=250, ge=0, le=100_000)
    training_work_us_per_sample: StrictInt = Field(default=120, ge=0, le=100_000)
    aggregation_cost_us: StrictInt = Field(default=1000, ge=0, le=100_000)
    fl_period_us: StrictInt = Field(default=300_000, ge=10_000, le=6_000_000)
    watchdog_period_us: StrictInt = Field(default=2000, ge=500, le=1_000_000)
    base_link_us: StrictInt = Field(default=800, ge=0, le=1_000_000)
    jitter_us: StrictInt = Field(default=400, ge=0, le=1_000_000)
    loss_ppm: StrictInt = Field(default=10_000, ge=0, le=1_000_000)
    retry_limit: StrictInt = Field(default=2, ge=0, le=8)
    margin_us: StrictInt = Field(default=1000, ge=0, le=1_000_000)
    host_inference_budget_us: StrictInt = Field(default=10_000, ge=1, le=1_000_000)
    enforce_host_inference_budget: StrictBool = False

    def compile(self):
        workflows = []
        for w in self.workflows:
            tasks = []
            for t in w.tasks:
                if t.distribution == "constant" and not t.bcet_us == t.nominal_us == t.wcet_us:
                    raise ValueError(f"{t.task_id}: constant demand requires equal execution bounds")
                for p in t.exit_points:
                    lo, hi = p.elapsed_work_interval_us
                    if not 0 <= lo <= hi <= t.wcet_us:
                        raise ValueError(f"{t.task_id}: exit interval must be within declared work")
                    if p.remaining_wcet_us + p.checkpoint_overhead_us > t.wcet_us:
                        raise ValueError(f"{t.task_id}: exit continuation exceeds full budget")
                tasks.append(TaskSpec(
                    task_id=t.task_id, resource_demands=(ResourceDemand(ResourceKind(t.resource), 1),),
                    relative_deadline_us=t.relative_deadline_us,
                    wcet_distribution=WcetDistributionSpec(t.distribution,t.bcet_us,t.nominal_us,t.wcet_us),
                    criticality=Criticality(t.criticality), priority=t.priority, period_us=w.period_us,
                    preemption_mode=PreemptionMode.CHECKPOINT if t.resource == "gpu" else PreemptionMode.PREEMPTIVE,
                    offloadable=t.offloadable, request_payload_bytes=t.request_payload_bytes,
                    result_payload_bytes=t.result_payload_bytes, output_utility=t.output_utility,
                    exit_points=tuple(ExitPointSpec(**p.model_dump()) for p in t.exit_points),
                ))
            workflows.append(PipelineSpec(w.pipeline_id,tuple(tasks),tuple(w.dependency_edges),
                ReleaseModel.PERIODIC,w.end_to_end_deadline_us,w.sink_task_id,period_us=w.period_us))
        values=self.model_dump(exclude={"schema_version","devices","workflows","faults"})
        config=ResearchConfig(**values,devices=tuple(ResearchDevice(**d.model_dump()) for d in self.devices),
            workflows=tuple(workflows),faults=tuple(ResearchFault(**f.model_dump()) for f in self.faults))
        releases=sum(max(0,(config.release_end_us-i*2500+w.period_us-1)//w.period_us)
                     for i,w in enumerate(config.workflows)) * len(config.devices)
        tasks=sum(max(0,(config.release_end_us-i*2500+w.period_us-1)//w.period_us)*len(w.tasks)
                  for i,w in enumerate(config.workflows)) * len(config.devices)
        if tasks > 6000:
            raise ValueError("scenario exceeds the interactive limit of 6000 released task instances")
        return config, {"released_jobs":releases,"released_tasks":tasks}


def template(family):
    config=default_research_config(family=family)
    data=config.to_dict()
    data["schema_version"]="research-designer/1.0"
    data["workflows"]=[{
        "pipeline_id":w.pipeline_id,"period_us":w.period_us,
        "end_to_end_deadline_us":w.end_to_end_deadline_us,"sink_task_id":w.sink_task_id,
        "dependency_edges":w.to_dict()["dependency_edges"],
        "tasks":[{
            "task_id":t.task_id,"resource":"gpu" if any(d.resource is ResourceKind.GPU for d in t.resource_demands) else "cpu",
            "bcet_us":t.wcet_distribution.bcet_us,"nominal_us":t.wcet_distribution.nominal_us,
            "wcet_us":t.wcet_distribution.wcet_us,"distribution":t.wcet_distribution.kind,
            "relative_deadline_us":t.relative_deadline_us,"criticality":t.criticality.value,
            "priority":t.priority,"offloadable":t.offloadable,
            "request_payload_bytes":t.request_payload_bytes,"result_payload_bytes":t.result_payload_bytes,
            "output_utility":t.output_utility,"exit_points":[p.to_dict() for p in t.exit_points],
        } for t in w.tasks],
    } for w in config.workflows]
    return ScenarioInput.model_validate(data).model_dump()
