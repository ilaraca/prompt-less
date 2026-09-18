#!/usr/bin/env python3
"""
Fecha o ciclo: carrega ExecutionResult + Canonical Spec → verify (Git + logs) → repair.

Cada invocação reexecuta verify completo antes de montar o pedido de reparo.
`build_repair_request` reaplica a política da camada (profile + raiz do repo)
a cada `--attempt`. Tentativas além do limite terminam `exhausted` / unresolved.

Uso:
  python -m src.close_loop --spec path/canonical-spec.yaml --result path/execution.json --repo path/checkout
  python -m src.close_loop --spec ... --result ... --repo ... --adapter-log path/adapter-log.jsonl
  python -m src.close_loop --spec ... --result ... --repo ... --attempt 1

Aprovação humana: python -m src.approval request-approval|approve|promote
(--approve neste comando foi removido; não marca approved=True).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.domain.claim import Claim, ClaimOrigin  # noqa: E402
from src.domain.review import ReviewDecision  # noqa: E402
from src.domain.source_ref import SourceRef  # noqa: E402
from src.domain.spec import (  # noqa: E402
    AcceptanceCriterion,
    CanonicalSpec,
    OpenQuestion,
    Operation,
    Requirement,
    SpecError,
)
from src.hardening.debugger import build_debugger_report  # noqa: E402
from src.executors import DevinAdapter, build_repair_request, verify_execution  # noqa: E402
from src.executors.base import ExecutionResult  # noqa: E402
from src.executors.policy import load_profiles  # noqa: E402
from src.runtime.atomic_io import atomic_write_json  # noqa: E402


def _parse_confidence(raw, *, default: float = 1.0) -> float:
    if raw is None:
        return default
    value = float(raw)
    if value < 0.0 or value > 1.0:
        raise ValueError(f"confidence fora de [0,1]: {value}")
    return value


def _load_spec(path: Path) -> CanonicalSpec:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    svc = raw.get("service") or {}
    claims = []
    for c in raw.get("claims") or []:
        claims.append(
            Claim(
                id=c["id"],
                text=c.get("text") or "",
                origin=ClaimOrigin(c.get("origin") or "declared"),
                confidence=_parse_confidence(c.get("confidence"), default=1.0),
                sources=[
                    SourceRef(**{k: v for k, v in s.items() if k in SourceRef.__dataclass_fields__})
                    for s in (c.get("sources") or [])
                ],
            )
        )
    operations = [Operation.from_raw(o) for o in (raw.get("operations") or [])]
    review_decisions = [
        ReviewDecision.from_raw(item) for item in (raw.get("review_decisions") or [])
    ]
    return CanonicalSpec(
        version=str(raw.get("spec_version") or "1.0"),
        service_id=str((svc.get("id") or "default")),
        service_name=svc.get("nome"),
        repositories=dict(svc.get("repositories") or {}),
        claims=claims,
        requirements=[Requirement(**r) for r in (raw.get("requirements") or [])],
        acceptance_criteria=[
            AcceptanceCriterion(**a) for a in (raw.get("acceptance_criteria") or [])
        ],
        operations=operations,
        errors=[SpecError(**e) for e in (raw.get("errors") or [])],
        nfrs=[Requirement(**n) for n in (raw.get("nfrs") or [])],
        open_questions=[OpenQuestion(**q) for q in (raw.get("open_questions") or [])],
        review_decisions=review_decisions,
    )


def _default_adapter_log(result_path: Path, execution: ExecutionResult) -> Path | None:
    if execution.adapter_log:
        declared = Path(execution.adapter_log)
        if not declared.is_absolute():
            declared = result_path.parent / declared
        return declared
    sibling = result_path.parent / "adapter-log.jsonl"
    return sibling if sibling.is_file() else None


def close_loop(
    *,
    spec_path: Path,
    result_path: Path,
    attempt: int = 1,
    layer: str | None = None,
    out_dir: Path | None = None,
    repo_path: Path | None = None,
    adapter_log: Path | None = None,
) -> dict:
    import time

    from src.task_metrics import build_task_metrics

    spec = _load_spec(spec_path)
    adapter = DevinAdapter(result_path=result_path)
    execution = adapter.collect_result()

    log_path = adapter_log or _default_adapter_log(result_path, execution)
    t0 = time.perf_counter()
    # Sempre re-verify completo (também após cada tentativa de reparo).
    verify = verify_execution(
        execution,
        spec,
        layer=layer,
        repo_path=repo_path,
        adapter_log=log_path,
    )
    validation_ms = int((time.perf_counter() - t0) * 1000)
    repair = None
    repair_ms = 0
    if verify.has_errors and verify.status != "needs_approval":
        t1 = time.perf_counter()
        profiles = load_profiles()
        layer_name = layer or execution.layer
        profile = profiles.get(layer_name) if layer_name else None
        repair = build_repair_request(
            verify,
            execution,
            attempt=attempt,
            profile=profile,
            layer=layer_name,
            repo_root=repo_path,
        )
        repair_ms = int((time.perf_counter() - t1) * 1000)
    elif verify.status == "needs_approval":
        repair = {
            "status": "awaiting_approval",
            "message": (
                "Use python -m src.approval request-approval / approve "
                "após revisão humana"
            ),
            "issues": [i.to_dict() for i in verify.issues],
        }

    exec_usage = None
    if isinstance(execution.to_dict(), dict):
        exec_usage = (execution.to_dict().get("meta") or {}).get("token_usage")
    task_metrics = build_task_metrics(
        attempts=max(1, int(attempt)),
        duration_ms={
            "validation_ms": validation_ms,
            "repair_ms": repair_ms,
            "total_ms": validation_ms + repair_ms,
        },
        token_usage=exec_usage if isinstance(exec_usage, dict) else None,
        phases={
            "validation_ms": validation_ms,
            "repair_ms": repair_ms,
            "total_ms": validation_ms + repair_ms,
        },
    )

    report = {
        "run_id": execution.run_id,
        "verify": verify.to_dict(),
        "repair": repair,
        "execution": execution.to_dict(),
        "task_metrics": task_metrics,
    }
    debugger = build_debugger_report(
        verify=verify,
        execution=execution,
        repair=repair,
        stage="close_loop",
        run_status=verify.status,
    )
    report["debugger"] = debugger
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(out_dir / "verify-report.json", report)
        atomic_write_json(out_dir / "debugger.json", debugger)
    return report


def main() -> None:
    p = argparse.ArgumentParser(description="Prompt-less — close executor loop")
    p.add_argument("--spec", required=True, type=Path, help="canonical-spec.yaml")
    p.add_argument("--result", required=True, type=Path, help="execution result JSON")
    p.add_argument(
        "--approve",
        action="store_true",
        help="removido: use python -m src.approval (não marca approved=True)",
    )
    p.add_argument("--attempt", type=int, default=1)
    p.add_argument("--layer", default=None)
    p.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="checkout Git da execução (diff real; obrigatório)",
    )
    p.add_argument(
        "--adapter-log",
        type=Path,
        default=None,
        help="JSONL estruturado do adapter (default: <result>/adapter-log.jsonl)",
    )
    p.add_argument("--out", type=Path, default=None, help="diretório para verify-report.json")
    args = p.parse_args()
    if args.approve:
        print(
            "close_loop --approve foi removido: não é atalho para approved=True. "
            "Use python -m src.approval request-approval / approve / promote.",
            file=sys.stderr,
        )
        sys.exit(2)
    report = close_loop(
        spec_path=args.spec,
        result_path=args.result,
        attempt=args.attempt,
        layer=args.layer,
        out_dir=args.out,
        repo_path=args.repo,
        adapter_log=args.adapter_log,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["verify"]["status"] != "passed":
        sys.exit(2)


if __name__ == "__main__":
    main()
