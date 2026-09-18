"""Execução concorrente por ondas + CAS/lock no file backend (ticket 13)."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from src.executors.base import ExecutionResult
from src.executors.scheduler import (
    ScheduledTask,
    TaskRunResult,
    run_plan_waves,
    waves_from_plan,
)
from src.state_store import (
    FileStateBackend,
    StateConflict,
    StateLockTimeout,
    compare_and_set_state,
    file_lock,
    open_state_backend,
    read_state,
    state_version,
    update_state,
)


def _sample_plan() -> dict:
    """Duas ondas: wave0 paralela (api+bff), wave1 sequencial (mfe)."""
    return {
        "plans": [
            {
                "service_id": "ms-demo",
                "reviewed": True,
                "tasks": [
                    {
                        "id": "t-api",
                        "repo": "api-demo",
                        "layer": "api",
                        "service_id": "ms-demo",
                        "changes": ["POST /x"],
                        "depends_on": [],
                    },
                    {
                        "id": "t-bff",
                        "repo": "bff-demo",
                        "layer": "bff",
                        "service_id": "ms-demo",
                        "changes": ["proxy"],
                        "depends_on": [],
                    },
                    {
                        "id": "t-mfe",
                        "repo": "mfe-demo",
                        "layer": "mfe",
                        "service_id": "ms-demo",
                        "changes": ["page"],
                        "depends_on": ["t-api", "t-bff"],
                    },
                ],
                "waves": [["t-api", "t-bff"], ["t-mfe"]],
                "parallelism": {"max_wave_size": 2, "wave_count": 2},
            }
        ],
        "report": {"ready_for_parallel_execution": True},
    }


class FakeParallelAdapter:
    """Adapter fake que mede concorrência real e pode falhar por repo."""

    def __init__(
        self,
        *,
        delay_s: float = 0.08,
        fail_repos: frozenset[str] | set[str] | None = None,
    ) -> None:
        self.delay_s = delay_s
        self.fail_repos = set(fail_repos or ())
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.started: list[str] = []
        self.finished: list[str] = []

    def execute_task(self, task: ScheduledTask) -> ExecutionResult:
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.started.append(task.id)
        try:
            time.sleep(self.delay_s)
            if task.repo in self.fail_repos:
                raise RuntimeError(f"boom:{task.repo}")
            return ExecutionResult(
                run_id=f"fake-{task.id}",
                agent="fake-parallel",
                repository=task.repo,
                layer=task.layer,
                changed_files=[f"src/{task.repo}.py"],
                commands_executed=["pytest -q"],
                tests=[{"name": "ok", "passed": True}],
                approved=True,
            )
        finally:
            with self._lock:
                self.active -= 1
                self.finished.append(task.id)


def test_waves_from_plan_consumes_wave_ids():
    plan = _sample_plan()["plans"][0]
    waves = waves_from_plan(plan)
    assert len(waves) == 2
    assert [t.id for t in waves[0]] == ["t-api", "t-bff"]
    assert [t.id for t in waves[1]] == ["t-mfe"]
    assert waves[0][0].repo == "api-demo"


def test_scheduler_respects_semaphore_and_runs_wave_in_parallel():
    adapter = FakeParallelAdapter(delay_s=0.1)
    report = run_plan_waves(
        _sample_plan(),
        adapter=adapter,
        max_concurrency=2,
    )
    assert report.ok
    assert report.max_concurrency == 2
    # onda 0 tem 2 tasks — com concurrency=2 devem sobrepor
    assert adapter.max_active == 2
    assert sorted(o.task_id for o in report.outcomes) == ["t-api", "t-bff", "t-mfe"]
    assert set(report.by_repository) >= {"api-demo", "bff-demo", "mfe-demo"}
    for outcome in report.outcomes:
        assert outcome.status == "passed"
        assert outcome.execution is not None
        assert outcome.verify is not None
        assert outcome.verify["status"] == "passed"


def test_scheduler_limits_below_wave_size():
    adapter = FakeParallelAdapter(delay_s=0.12)
    report = run_plan_waves(_sample_plan(), adapter=adapter, max_concurrency=1)
    assert report.ok
    assert adapter.max_active == 1


def test_failure_keeps_sibling_results():
    adapter = FakeParallelAdapter(delay_s=0.05, fail_repos={"bff-demo"})
    report = run_plan_waves(_sample_plan(), adapter=adapter, max_concurrency=2)
    assert not report.ok
    assert "t-bff" in report.failed_task_ids

    by_id = {o.task_id: o for o in report.outcomes}
    # irmã da mesma onda sobrevive
    assert by_id["t-api"].status == "passed"
    assert by_id["t-api"].execution is not None
    assert by_id["t-api"].execution["repository"] == "api-demo"
    # a que falhou registra erro sem apagar o slot
    assert by_id["t-bff"].status == "error"
    assert by_id["t-bff"].error is not None
    assert "boom:bff-demo" in by_id["t-bff"].error
    # onda seguinte ainda roda (mfe) — scheduler não aborta o plano inteiro
    assert "t-mfe" in by_id
    assert by_id["t-mfe"].status == "passed"


def test_verify_aggregation_marks_failed_without_dropping_execution():
    def runner(task: ScheduledTask) -> TaskRunResult:
        return TaskRunResult(
            execution=ExecutionResult(
                run_id=f"r-{task.id}",
                agent="fake",
                repository=task.repo,
                layer=task.layer,
                unresolved_items=["gap"] if task.id == "t-api" else [],
            )
        )

    report = run_plan_waves(_sample_plan(), runner=runner, max_concurrency=2)
    by_id = {o.task_id: o for o in report.outcomes}
    assert by_id["t-api"].status == "failed"
    assert by_id["t-api"].execution is not None
    assert by_id["t-api"].verify is not None
    assert by_id["t-api"].verify["status"] == "failed"
    assert by_id["t-bff"].status == "passed"
    assert by_id["t-mfe"].status == "passed"


def test_file_backend_compare_and_set(tmp_path: Path):
    path = tmp_path / "workflow.json"
    backend = FileStateBackend(path)
    v0 = backend.read()
    assert state_version(v0) == 0

    written = backend.compare_and_set(0, {"status": "ready", "step": 1})
    assert state_version(written) == 1
    assert read_state(path)["step"] == 1

    with pytest.raises(StateConflict):
        backend.compare_and_set(0, {"step": 99})

    written2 = backend.compare_and_set(1, {"status": "ready", "step": 2})
    assert state_version(written2) == 2
    assert read_state(path)["step"] == 2


def test_file_lock_blocks_second_holder(tmp_path: Path):
    path = tmp_path / "state.json"
    held = threading.Event()
    release = threading.Event()
    timed_out = threading.Event()

    def holder() -> None:
        with file_lock(path, timeout_s=2.0):
            held.set()
            release.wait(timeout=3.0)

    t = threading.Thread(target=holder)
    t.start()
    assert held.wait(timeout=2.0)

    def contender() -> None:
        try:
            with file_lock(path, timeout_s=0.2):
                pass
        except StateLockTimeout:
            timed_out.set()

    t2 = threading.Thread(target=contender)
    t2.start()
    t2.join(timeout=2.0)
    assert timed_out.is_set()
    release.set()
    t.join(timeout=2.0)


def test_update_state_retries_on_conflict(tmp_path: Path):
    path = tmp_path / "workflow.json"
    compare_and_set_state(0, {"counter": 0}, path)

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def bump() -> None:
        try:
            barrier.wait(timeout=2.0)

            def mutator(current: dict) -> dict:
                return {"counter": int(current.get("counter") or 0) + 1}

            update_state(mutator, path, max_retries=16)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=bump) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)
    assert not errors
    assert read_state(path)["counter"] == 2
    assert state_version(read_state(path)) == 3  # 0→1 init + 2 bumps


def test_scheduler_persists_outcomes_via_cas(tmp_path: Path):
    state_path = tmp_path / "parallel-state.json"
    backend = open_state_backend(backend="file", path=state_path)
    adapter = FakeParallelAdapter(delay_s=0.02, fail_repos={"bff-demo"})
    report = run_plan_waves(
        _sample_plan(),
        adapter=adapter,
        max_concurrency=2,
        state=backend,
    )
    assert not report.ok
    stored = read_state(state_path)
    slot = stored["parallel_exec"]
    assert slot["status"] == "failed"
    assert "t-bff" in slot["failed_task_ids"]
    # irmã preservada no state
    outcome_ids = {o["task_id"] for o in slot["outcomes"]}
    assert "t-api" in outcome_ids
    assert "t-bff" in outcome_ids
    api = next(o for o in slot["outcomes"] if o["task_id"] == "t-api")
    assert api["status"] == "passed"
    assert api["execution"]["repository"] == "api-demo"


def test_open_state_backend_rejects_redis():
    with pytest.raises(ValueError, match="12b"):
        open_state_backend(backend="redis")


def test_parallel_exec_cli_dry_run(tmp_path: Path, capsys):
    from src.parallel_exec import main

    plan_path = tmp_path / "implementation_plan.json"
    plan_path.write_text(
        __import__("json").dumps(_sample_plan()), encoding="utf-8"
    )
    out = tmp_path / "out"
    main(["--plan", str(plan_path), "--dry-run", "--out", str(out), "--max-concurrency", "3"])
    printed = __import__("json").loads(capsys.readouterr().out)
    assert printed["dry_run"] is True
    assert printed["max_concurrency"] == 3
    assert len(printed["waves"]) == 2
    assert (out / "parallel-report.json").is_file()


def test_parallel_exec_cli_stub(tmp_path: Path):
    from src.parallel_exec import main

    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        __import__("json").dumps(_sample_plan()), encoding="utf-8"
    )
    out = tmp_path / "out"
    state = tmp_path / "state.json"
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "--plan",
                str(plan_path),
                "--stub",
                "--max-concurrency",
                "2",
                "--out",
                str(out),
                "--state",
                str(state),
            ]
        )
    # stub marca unresolved → exit 2
    assert exc.value.code == 2
    report = __import__("json").loads((out / "parallel-report.json").read_text())
    assert report["ok"] is False
    assert len(report["outcomes"]) == 3
