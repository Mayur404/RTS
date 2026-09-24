from rts_predictive.domain.specs import (
    ExitPointSpec,
    ResourceDemand,
    ResourceKind,
    TaskSpec,
    WcetDistributionSpec,
)
from rts_predictive.simulator.tasks import TaskInstance


def _task_with_exits(*exit_points: ExitPointSpec) -> TaskInstance:
    spec = TaskSpec(
        task_id="vision",
        resource_demands=(ResourceDemand(ResourceKind.CPU, 0.5),),
        relative_deadline_us=30_000,
        period_us=40_000,
        wcet_distribution=WcetDistributionSpec(
            kind="fixed",
            bcet_us=10_000,
            nominal_us=20_000,
            wcet_us=25_000,
        ),
        exit_points=exit_points,
    )
    return TaskInstance.from_task_spec(spec, "vision-1", "robot-1", 0.0)


def test_early_exit_uses_configured_cost_and_utility_without_progress_scaling():
    task = _task_with_exits(
        ExitPointSpec("coarse", (4_000, 8_000), 700, 3_500, 0.72),
    )
    task.remaining_work_ms = 14.0  # Six milliseconds of nominal work executed.

    assert task.apply_degradation(10.0, "risk") is True
    assert task.checkpoint_id == "coarse"
    assert task.remaining_work_ms == 4.2
    assert task.degraded_wcet_ms == 3.5
    assert task.output_utility == 0.72


def test_early_exit_selects_highest_utility_reachable_feasible_checkpoint():
    task = _task_with_exits(
        ExitPointSpec("fast", (0, 20_000), 100, 2_000, 0.55),
        ExitPointSpec("useful", (0, 20_000), 500, 5_000, 0.9),
    )

    assert task.apply_degradation(5.0) is True
    assert task.checkpoint_id == "useful"
    assert task.remaining_work_ms == 5.5


def test_early_exit_rejects_invalid_unreachable_or_deadline_infeasible_points():
    task = _task_with_exits(
        ExitPointSpec("invalid", (0, 20_000), 0, 1_000, 0.9, structurally_valid=False),
        ExitPointSpec("passed", (8_000, 12_000), 0, 1_000, 0.8),
        ExitPointSpec("too_late", (0, 20_000), 1_000, 5_000, 0.7),
    )
    task.remaining_work_ms = 16.0  # Four milliseconds executed; `passed` is unavailable.

    assert task.apply_degradation(25.0) is False
    assert task.is_degraded is False
    assert task.checkpoint_id is None
    assert task.remaining_work_ms == 16.0


def test_early_exit_feasibility_charges_speed_and_interference_bound():
    task = _task_with_exits(
        ExitPointSpec("bounded", (0, 20_000), 500, 4_500, 0.75),
    )
    assert task.apply_degradation(
        15.0, execution_rate=0.5, interference_bound_ms=6.0
    ) is False
    assert task.is_degraded is False


def test_bounded_execution_distribution_is_sampled_once_per_attempt():
    spec = TaskSpec(
        task_id="variable",
        resource_demands=(ResourceDemand(ResourceKind.CPU, 0.2),),
        relative_deadline_us=30_000,
        period_us=40_000,
        wcet_distribution=WcetDistributionSpec(
            kind="bounded_uniform", bcet_us=5_000, nominal_us=10_000, wcet_us=15_000
        ),
    )
    task = TaskInstance.from_task_spec(spec, "variable-1", "robot-1", 0.0)
    import random
    generator = random.Random(7)

    first = task.sample_execution_work(generator)
    state_after_first = generator.getstate()
    second = task.sample_execution_work(generator)

    assert 5.0 <= first <= 15.0
    assert second == first
    assert generator.getstate() == state_after_first
    assert task.remaining_work_ms == first
