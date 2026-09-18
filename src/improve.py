#!/usr/bin/env python3
"""
Ciclo de melhoria controlada: diagnose → propose → apply no candidato → eval → accept/reject.

Uso:
  python -m src.improve --verify-report path/verify-report.json
  python -m src.improve --out /tmp/improve
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.learning import (  # noqa: E402
    apply_proposals_to_candidate,
    build_proposals,
    compare_evals,
    decide_proposals,
    diagnose_verify_report,
    materialize_eval_workspaces,
    run_eval_suite,
)
from src.learning.evals import DEFAULT_CASES  # noqa: E402
from src.runtime.atomic_io import atomic_write_json  # noqa: E402


def improve_from_verify(
    verify_report: dict,
    *,
    root: Path,
    eval_root: Path,
    source_root: Path | None = None,
    cases: list[str] | tuple[str, ...] | None = None,
) -> dict:
    diagnosis = diagnose_verify_report(verify_report)
    proposals = build_proposals(diagnosis)

    origin = Path(source_root) if source_root is not None else Path(root)
    pair = materialize_eval_workspaces(
        source_root=origin, eval_root=eval_root, resume=True
    )
    applied = apply_proposals_to_candidate(proposals, pair)
    suite_cases = cases if cases is not None else DEFAULT_CASES

    baseline = run_eval_suite(
        output_root=eval_root / "baseline",
        workspace=pair.baseline,
        cases=suite_cases,
        run_id_prefix="eval-b",
    )
    candidate = run_eval_suite(
        output_root=eval_root / "candidate",
        workspace=pair.candidate,
        cases=suite_cases,
        run_id_prefix="eval-c",
    )
    comparison = compare_evals(baseline, candidate)
    comparison["diff"] = applied.diff
    decision = decide_proposals(
        proposals,
        comparison,
        root=root,
        apply_result=applied.to_dict(),
    )

    return {
        "diagnosis": diagnosis,
        "proposals": proposals,
        "workspaces": pair.to_dict(),
        "applied": applied.to_dict(),
        "evals": {"baseline": baseline["summary"], "candidate": candidate["summary"]},
        "decision": decision,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Prompt-less — controlled self-improvement")
    p.add_argument("--verify-report", type=Path, default=None)
    p.add_argument("--out", type=Path, default=ROOT / "state" / "knowledge")
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument(
        "--cases",
        default="",
        help="casos de eval separados por vírgula (default: suíte completa)",
    )
    args = p.parse_args()

    if args.verify_report:
        report = json.loads(args.verify_report.read_text(encoding="utf-8"))
    else:
        report = {
            "verify": {
                "status": "failed",
                "issues": [
                    {
                        "code": "AMBIGUOUS_HTTP_STATUS",
                        "severity": "error",
                        "message": "status ambíguo",
                    }
                ],
            }
        }

    eval_root = args.out / "evals"
    eval_root.mkdir(parents=True, exist_ok=True)
    cases = tuple(c.strip() for c in str(args.cases).split(",") if c.strip()) or None
    result = improve_from_verify(
        report, root=args.root, eval_root=eval_root, cases=cases
    )
    out_file = args.out / "last-improvement.json"
    args.out.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out_file, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
