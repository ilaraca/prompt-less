#!/usr/bin/env python3
"""
Executa adapters por ondas do implementation_plan (ticket 13).

Uso:
  python -m src.parallel_exec --plan runs/plan/implementation_plan.json
  python -m src.parallel_exec --plan … --max-concurrency 3 --out runs/parallel/
  python -m src.parallel_exec --plan … --dry-run   # só lista ondas (sem adapter)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.executors.base import ExecutionResult  # noqa: E402
from src.executors.scheduler import (  # noqa: E402
    ScheduledTask,
    TaskRunResult,
    plans_from_document,
    run_plan_waves,
    waves_from_plan,
)
from src.runtime.atomic_io import atomic_write_json  # noqa: E402
from src.state_store import FileStateBackend, open_state_backend  # noqa: E402


def _load_plan(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        raw = yaml.safe_load(text) or {}
    else:
        raw = json.loads(text)
    if not isinstance(raw, dict):
        raise SystemExit(f"plano inválido: {path}")
    return raw


def _dry_run_report(plan_doc: dict[str, Any], max_concurrency: int) -> dict[str, Any]:
    waves_out: list[dict[str, Any]] = []
    for plan in plans_from_document(plan_doc):
        for wave in waves_from_plan(plan):
            waves_out.append(
                {
                    "service_id": plan.get("service_id"),
                    "wave_index": wave[0].wave_index if wave else 0,
                    "tasks": [
                        {"id": t.id, "repo": t.repo, "layer": t.layer} for t in wave
                    ],
                }
            )
    return {
        "dry_run": True,
        "max_concurrency": max_concurrency,
        "ready_for_parallel_execution": (plan_doc.get("report") or {}).get(
            "ready_for_parallel_execution"
        ),
        "waves": waves_out,
    }


def _stub_runner(task: ScheduledTask) -> TaskRunResult:
    """Runner placeholder: não invoca Devin — útil para dry wiring / testes manuais."""
    return TaskRunResult(
        execution=ExecutionResult(
            run_id=f"stub-{task.id}",
            agent="stub",
            repository=task.repo,
            layer=task.layer,
            unresolved_items=["stub_runner: sem adapter real"],
        ),
        error=None,
    )


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        description="Prompt-less — execução concorrente por ondas do plano"
    )
    p.add_argument("--plan", type=Path, required=True, help="implementation_plan.json|.yaml")
    p.add_argument(
        "--max-concurrency",
        type=int,
        default=2,
        help="semáforo: N execuções concorrentes por onda (default: 2)",
    )
    p.add_argument("--out", type=Path, default=None, help="grava parallel-report.json")
    p.add_argument(
        "--state",
        type=Path,
        default=None,
        help="arquivo de state versionado (CAS); default: sem persistência",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="lista ondas do plano sem executar adapters",
    )
    p.add_argument(
        "--stub",
        action="store_true",
        help="usa runner stub (não chama Devin); para smoke do scheduler",
    )
    args = p.parse_args(argv)

    plan_doc = _load_plan(args.plan)
    if args.dry_run:
        report = _dry_run_report(plan_doc, args.max_concurrency)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            atomic_write_json(args.out / "parallel-report.json", report)
        return

    if not args.stub:
        print(
            "paralelismo real com Devin por task ainda exige --stub ou integração "
            "por runner injetado; use --dry-run para inspecionar ondas, ou --stub "
            "para exercitar o scheduler.",
            file=sys.stderr,
        )
        # ainda assim rodamos o stub se não houver adapter wired — fail soft doc
        # Prefer explicit --stub for clarity; without it, exit 2 unless dry-run.
        sys.exit(2)

    state: FileStateBackend | None = None
    if args.state:
        state = open_state_backend(backend="file", path=args.state)

    result = run_plan_waves(
        plan_doc,
        runner=_stub_runner,
        max_concurrency=args.max_concurrency,
        state=state,
    )
    payload = result.to_dict()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        atomic_write_json(args.out / "parallel-report.json", payload)
    if not result.ok:
        sys.exit(2)


if __name__ == "__main__":
    main()
