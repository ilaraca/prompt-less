#!/usr/bin/env python3
"""
Fecha o ciclo: carrega ExecutionResult + Canonical Spec → verify → repair opcional.

Uso:
  python -m src.close_loop --spec path/canonical-spec.yaml --result path/execution.json
  python -m src.close_loop --spec ... --result ... --approve
  python -m src.close_loop --spec ... --result ... --attempt 1
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
from src.domain.source_ref import SourceRef  # noqa: E402
from src.domain.spec import (  # noqa: E402
    AcceptanceCriterion,
    CanonicalSpec,
    OpenQuestion,
    Operation,
    Requirement,
    ResolvedInt,
    SpecError,
)
from src.executors import DevinAdapter, build_repair_request, verify_execution  # noqa: E402
from src.executors.base import ExecutionResult  # noqa: E402


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
    operations = []
    for o in raw.get("operations") or []:
        op_data = dict(o)
        if "success_status" in op_data:
            op_data["success_status"] = ResolvedInt.from_raw(op_data["success_status"])
        operations.append(Operation(**op_data))
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
    )


def close_loop(
    *,
    spec_path: Path,
    result_path: Path,
    approve: bool = False,
    attempt: int = 1,
    layer: str | None = None,
    out_dir: Path | None = None,
) -> dict:
    spec = _load_spec(spec_path)
    adapter = DevinAdapter(result_path=result_path)
    execution = adapter.collect_result()
    if approve:
        execution.approved = True
    elif execution.approved is None:
        execution.approved = False

    verify = verify_execution(execution, spec, layer=layer)
    repair = None
    if verify.has_errors and verify.status != "needs_approval":
        repair = build_repair_request(verify, execution, attempt=attempt)
    elif verify.status == "needs_approval":
        repair = {
            "status": "awaiting_approval",
            "message": "Use --approve após revisão humana",
            "issues": [i.to_dict() for i in verify.issues],
        }

    report = {
        "run_id": execution.run_id,
        "verify": verify.to_dict(),
        "repair": repair,
        "execution": execution.to_dict(),
    }
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "verify-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return report


def main() -> None:
    p = argparse.ArgumentParser(description="Prompt-less — close executor loop")
    p.add_argument("--spec", required=True, type=Path, help="canonical-spec.yaml")
    p.add_argument("--result", required=True, type=Path, help="execution result JSON")
    p.add_argument("--approve", action="store_true", help="marca execução como aprovada")
    p.add_argument("--attempt", type=int, default=1)
    p.add_argument("--layer", default=None)
    p.add_argument("--out", type=Path, default=None, help="diretório para verify-report.json")
    args = p.parse_args()
    report = close_loop(
        spec_path=args.spec,
        result_path=args.result,
        approve=args.approve,
        attempt=args.attempt,
        layer=args.layer,
        out_dir=args.out,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["verify"]["status"] != "passed":
        sys.exit(2)


if __name__ == "__main__":
    main()
