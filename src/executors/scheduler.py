"""Scheduler de execução por ondas do implementation_plan.

Consome `waves` do plano multi-repo, limita concorrência com semáforo
configurável e agrega `ExecutionResult` + verify por repositório. Falha em
uma task **não** apaga os resultados das irmãs da mesma onda.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from threading import Semaphore
from typing import Any, Callable, Protocol

from src.executors.base import ExecutionResult
from src.state_store import FileStateBackend, StateBackend, update_state

TaskRunner = Callable[["ScheduledTask"], "TaskRunResult"]
VerifyFn = Callable[[ExecutionResult, "ScheduledTask"], dict[str, Any]]


@dataclass(frozen=True)
class ScheduledTask:
    id: str
    repo: str
    layer: str | None
    service_id: str
    changes: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    wave_index: int = 0

    @classmethod
    def from_plan_task(cls, raw: dict[str, Any], *, wave_index: int) -> "ScheduledTask":
        return cls(
            id=str(raw.get("id") or ""),
            repo=str(raw.get("repo") or ""),
            layer=raw.get("layer"),
            service_id=str(raw.get("service_id") or ""),
            changes=list(raw.get("changes") or []),
            depends_on=list(raw.get("depends_on") or []),
            wave_index=wave_index,
        )


@dataclass
class TaskRunResult:
    """Resultado bruto do adapter (antes do verify)."""

    execution: ExecutionResult | None = None
    error: str | None = None


@dataclass
class TaskOutcome:
    task_id: str
    repository: str
    wave_index: int
    status: str  # passed | failed | error
    execution: dict[str, Any] | None = None
    verify: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WaveOutcome:
    wave_index: int
    task_ids: list[str]
    outcomes: list[TaskOutcome]

    def to_dict(self) -> dict[str, Any]:
        return {
            "wave_index": self.wave_index,
            "task_ids": list(self.task_ids),
            "outcomes": [o.to_dict() for o in self.outcomes],
            "failed": [o.task_id for o in self.outcomes if o.status != "passed"],
        }


@dataclass
class ParallelExecutionReport:
    max_concurrency: int
    waves: list[WaveOutcome]
    outcomes: list[TaskOutcome]
    by_repository: dict[str, list[TaskOutcome]]
    failed_task_ids: list[str]
    ok: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_concurrency": self.max_concurrency,
            "ok": self.ok,
            "failed_task_ids": list(self.failed_task_ids),
            "waves": [w.to_dict() for w in self.waves],
            "outcomes": [o.to_dict() for o in self.outcomes],
            "by_repository": {
                repo: [o.to_dict() for o in items]
                for repo, items in self.by_repository.items()
            },
        }


class WaveExecutor(Protocol):
    """Adapter mínimo: recebe task agendada e devolve ExecutionResult."""

    def execute_task(self, task: ScheduledTask) -> ExecutionResult:
        ...


def plans_from_document(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Aceita `{plans: [...]}` ou um único plano com `waves`/`tasks`."""
    if not isinstance(doc, dict):
        raise TypeError("plano deve ser um objeto JSON/YAML")
    plans = doc.get("plans")
    if isinstance(plans, list):
        return [p for p in plans if isinstance(p, dict)]
    if "waves" in doc or "tasks" in doc:
        return [doc]
    raise ValueError("documento sem plans[] nem waves/tasks")


def waves_from_plan(plan: dict[str, Any]) -> list[list[ScheduledTask]]:
    """Materializa ondas do plano: lista de ScheduledTask por wave."""
    tasks_raw = {str(t.get("id")): t for t in (plan.get("tasks") or []) if t.get("id")}
    waves_ids = plan.get("waves") or []
    if not waves_ids and tasks_raw:
        # sem ondas explícitas: uma onda com todas as tasks (ordem estável)
        waves_ids = [sorted(tasks_raw.keys())]

    result: list[list[ScheduledTask]] = []
    for idx, wave in enumerate(waves_ids):
        if not isinstance(wave, list):
            continue
        scheduled: list[ScheduledTask] = []
        for tid in wave:
            raw = tasks_raw.get(str(tid))
            if raw is None:
                scheduled.append(
                    ScheduledTask(
                        id=str(tid),
                        repo="",
                        layer=None,
                        service_id=str(plan.get("service_id") or ""),
                        wave_index=idx,
                    )
                )
            else:
                scheduled.append(ScheduledTask.from_plan_task(raw, wave_index=idx))
        result.append(scheduled)
    return result


def _default_verify(execution: ExecutionResult, task: ScheduledTask) -> dict[str, Any]:
    """Verify mínimo quando o caller não injeta close_loop/verify_execution."""
    unresolved = list(execution.unresolved_items or [])
    status = "failed" if unresolved else "passed"
    return {
        "status": status,
        "errors": len(unresolved),
        "warnings": 0,
        "issues": [
            {
                "code": "UNRESOLVED_ITEMS",
                "severity": "error",
                "message": f"Itens não resolvidos: {unresolved}",
            }
        ]
        if unresolved
        else [],
        "coverage": dict(execution.requirement_traceability or {}),
        "task_id": task.id,
        "repository": task.repo,
    }


def _run_one(
    task: ScheduledTask,
    *,
    runner: TaskRunner,
    verify_fn: VerifyFn | None,
    semaphore: Semaphore,
) -> TaskOutcome:
    with semaphore:
        try:
            run_result = runner(task)
        except Exception as exc:  # noqa: BLE001 — isolar falha da irmã
            return TaskOutcome(
                task_id=task.id,
                repository=task.repo,
                wave_index=task.wave_index,
                status="error",
                error=f"{type(exc).__name__}: {exc}",
            )

        if run_result.error and run_result.execution is None:
            return TaskOutcome(
                task_id=task.id,
                repository=task.repo,
                wave_index=task.wave_index,
                status="error",
                error=run_result.error,
            )

        execution = run_result.execution
        assert execution is not None
        try:
            verify = (verify_fn or _default_verify)(execution, task)
        except Exception as exc:  # noqa: BLE001
            return TaskOutcome(
                task_id=task.id,
                repository=task.repo,
                wave_index=task.wave_index,
                status="error",
                execution=execution.to_dict(),
                error=f"verify:{type(exc).__name__}: {exc}",
            )

        # só "passed" fecha a task; needs_approval/failed exigem humano/repair
        verify_status = str((verify or {}).get("status") or "failed")
        outcome_status = "passed" if verify_status == "passed" else "failed"

        return TaskOutcome(
            task_id=task.id,
            repository=task.repo or execution.repository,
            wave_index=task.wave_index,
            status=outcome_status,
            execution=execution.to_dict(),
            verify=verify,
            error=run_result.error,
        )


def _adapter_as_runner(adapter: WaveExecutor) -> TaskRunner:
    def _run(task: ScheduledTask) -> TaskRunResult:
        try:
            execution = adapter.execute_task(task)
            return TaskRunResult(execution=execution)
        except Exception as exc:  # noqa: BLE001
            return TaskRunResult(error=f"{type(exc).__name__}: {exc}")

    return _run


def run_plan_waves(
    plan_doc: dict[str, Any],
    *,
    runner: TaskRunner | None = None,
    adapter: WaveExecutor | None = None,
    verify_fn: VerifyFn | None = None,
    max_concurrency: int = 2,
    state: StateBackend | None = None,
    state_key: str = "parallel_exec",
) -> ParallelExecutionReport:
    """
    Executa todas as ondas de todos os planos do documento.

    Ondas avançam em série; dentro de cada onda até `max_concurrency`
    tasks correm em paralelo. Resultados das irmãs sobrevivem a falhas.
    """
    if max_concurrency < 1:
        raise ValueError("max_concurrency deve ser >= 1")
    if runner is None and adapter is None:
        raise ValueError("passe runner= ou adapter=")
    if runner is None:
        assert adapter is not None
        runner = _adapter_as_runner(adapter)

    semaphore = Semaphore(max_concurrency)
    all_outcomes: list[TaskOutcome] = []
    wave_reports: list[WaveOutcome] = []

    if state is not None:
        _init_state_slot(state, state_key, max_concurrency)

    for plan in plans_from_document(plan_doc):
        for wave_tasks in waves_from_plan(plan):
            if not wave_tasks:
                continue
            wave_index = wave_tasks[0].wave_index
            wave_outcomes = _execute_wave(
                wave_tasks,
                runner=runner,
                verify_fn=verify_fn,
                semaphore=semaphore,
                max_concurrency=max_concurrency,
            )
            # falha de uma não remove as outras — todas entram no relatório
            wave_reports.append(
                WaveOutcome(
                    wave_index=wave_index,
                    task_ids=[t.id for t in wave_tasks],
                    outcomes=list(wave_outcomes),
                )
            )
            all_outcomes.extend(wave_outcomes)
            if state is not None:
                _persist_wave(state, state_key, wave_reports[-1])

    by_repo: dict[str, list[TaskOutcome]] = {}
    for outcome in all_outcomes:
        by_repo.setdefault(outcome.repository or "", []).append(outcome)

    failed = [o.task_id for o in all_outcomes if o.status != "passed"]
    report = ParallelExecutionReport(
        max_concurrency=max_concurrency,
        waves=wave_reports,
        outcomes=all_outcomes,
        by_repository=by_repo,
        failed_task_ids=failed,
        ok=not failed,
    )
    if state is not None:
        _persist_final(state, state_key, report)
    return report


def _execute_wave(
    tasks: list[ScheduledTask],
    *,
    runner: TaskRunner,
    verify_fn: VerifyFn | None,
    semaphore: Semaphore,
    max_concurrency: int,
) -> list[TaskOutcome]:
    """Roda a onda; coleta **todos** os futures mesmo se um falhar."""
    outcomes: list[TaskOutcome] = []
    workers = min(max_concurrency, len(tasks))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _run_one,
                task,
                runner=runner,
                verify_fn=verify_fn,
                semaphore=semaphore,
            ): task
            for task in tasks
        }
        for fut in as_completed(futures):
            task = futures[fut]
            try:
                outcomes.append(fut.result())
            except Exception as exc:  # noqa: BLE001 — nunca engolir irmãs
                outcomes.append(
                    TaskOutcome(
                        task_id=task.id,
                        repository=task.repo,
                        wave_index=task.wave_index,
                        status="error",
                        error=f"future:{type(exc).__name__}: {exc}",
                    )
                )
    # ordem estável por task_id para asserts determinísticos
    order = {t.id: i for i, t in enumerate(tasks)}
    outcomes.sort(key=lambda o: order.get(o.task_id, 10_000))
    return outcomes


def _init_state_slot(
    state: StateBackend, key: str, max_concurrency: int
) -> None:
    def mutate(current: dict[str, Any]) -> dict[str, Any]:
        payload = dict(current)
        payload[key] = {
            "status": "running",
            "max_concurrency": max_concurrency,
            "waves": [],
            "outcomes": [],
        }
        return payload

    if isinstance(state, FileStateBackend):
        update_state(mutate, state.path, timeout_s=state.lock_timeout_s)
        return
    current = state.read()
    from src.state_store import state_version

    state.compare_and_set(state_version(current), mutate(current))


def _persist_wave(state: StateBackend, key: str, wave: WaveOutcome) -> None:
    def mutate(current: dict[str, Any]) -> dict[str, Any]:
        payload = dict(current)
        slot = dict(payload.get(key) or {})
        waves = list(slot.get("waves") or [])
        waves.append(wave.to_dict())
        outcomes = list(slot.get("outcomes") or [])
        outcomes.extend(o.to_dict() for o in wave.outcomes)
        slot["waves"] = waves
        slot["outcomes"] = outcomes
        slot["status"] = "running"
        payload[key] = slot
        return payload

    if isinstance(state, FileStateBackend):
        update_state(mutate, state.path, timeout_s=state.lock_timeout_s)
        return
    current = state.read()
    from src.state_store import state_version

    state.compare_and_set(state_version(current), mutate(current))


def _persist_final(
    state: StateBackend, key: str, report: ParallelExecutionReport
) -> None:
    def mutate(current: dict[str, Any]) -> dict[str, Any]:
        payload = dict(current)
        slot = dict(payload.get(key) or {})
        slot["status"] = "completed" if report.ok else "failed"
        slot["report"] = report.to_dict()
        slot["failed_task_ids"] = list(report.failed_task_ids)
        payload[key] = slot
        return payload

    if isinstance(state, FileStateBackend):
        update_state(mutate, state.path, timeout_s=state.lock_timeout_s)
        return
    current = state.read()
    from src.state_store import state_version

    state.compare_and_set(state_version(current), mutate(current))
