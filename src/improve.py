#!/usr/bin/env python3
"""
Ciclo de melhoria controlada: diagnose → propose → eval → accept/reject.

Uso:
  python -m src.improve --verify-report path/verify-report.json
  python -m src.improve --baseline-eval --out /tmp/improve
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.learning import (  # noqa: E402
    build_proposals,
    compare_evals,
    decide_proposals,
    diagnose_verify_report,
    run_eval_suite,
)


def improve_from_verify(
    verify_report: dict,
    *,
    root: Path,
    eval_root: Path,
) -> dict:
    diagnosis = diagnose_verify_report(verify_report)
    proposals = build_proposals(diagnosis)

    # baseline vs candidate: hoje o harness não muta código; candidate = mesma eval
    # (demonstra gate). Propostas low-risk vão para approved_for_experiment no
    # knowledge store — não afirmam melhoria aplicada.
    baseline = run_eval_suite(output_root=eval_root / "baseline")
    candidate = run_eval_suite(output_root=eval_root / "candidate")
    comparison = compare_evals(baseline, candidate)
    decision = decide_proposals(proposals, comparison, root=root)

    return {
        "diagnosis": diagnosis,
        "proposals": proposals,
        "evals": {"baseline": baseline["summary"], "candidate": candidate["summary"]},
        "decision": decision,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Prompt-less — controlled self-improvement")
    p.add_argument("--verify-report", type=Path, default=None)
    p.add_argument("--out", type=Path, default=ROOT / "state" / "knowledge")
    p.add_argument("--root", type=Path, default=ROOT)
    args = p.parse_args()

    if args.verify_report:
        report = json.loads(args.verify_report.read_text(encoding="utf-8"))
    else:
        # demo: falha de ambiguidade
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
    result = improve_from_verify(report, root=args.root, eval_root=eval_root)
    out_file = args.out / "last-improvement.json"
    args.out.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
