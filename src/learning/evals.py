"""Evals leves sobre fixtures baseline — métricas de qualidade/custo."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from src.run import run

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
DEFAULT_CASES = ("happy_path", "access_denied", "two_services", "ambiguous_status")


def run_eval_suite(
    *,
    cases: tuple[str, ...] | list[str] = DEFAULT_CASES,
    output_root: Path,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for case_id in cases:
        inputs = FIXTURES / case_id
        if not inputs.is_dir():
            continue
        out = output_root / case_id
        out.mkdir(parents=True, exist_ok=True)
        result = run(
            "historia",
            dry_run=True,
            inputs_dir=inputs,
            output_root=out,
            run_id=f"eval-{case_id}",
        )
        tokens = []
        if result.get("by_context"):
            tokens = [int(c.get("est_tokens") or 0) for c in result["by_context"] if c.get("est_tokens")]
        elif result.get("est_tokens"):
            tokens = [int(result["est_tokens"])]
        expect_blocked = case_id == "ambiguous_status"
        ok = (result.get("status") == "blocked") if expect_blocked else (result.get("status") == "completed")
        results.append(
            {
                "case_id": case_id,
                "status": result.get("status"),
                "ok": ok,
                "expect_blocked": expect_blocked,
                "est_tokens_max": max(tokens) if tokens else 0,
                "claims_count": result.get("claims_count") or 0,
            }
        )

    passed = sum(1 for r in results if r["ok"])
    return {
        "cases": results,
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "pass_rate": round(passed / max(len(results), 1), 3),
            "avg_est_tokens": round(
                sum(r["est_tokens_max"] for r in results) / max(len(results), 1), 1
            ),
        },
    }


def compare_evals(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    b = baseline.get("summary") or {}
    c = candidate.get("summary") or {}
    regression = False
    reasons: list[str] = []
    if float(c.get("pass_rate") or 0) < float(b.get("pass_rate") or 0):
        regression = True
        reasons.append("pass_rate_decreased")
    # estabilidade de custo: não permitir estouro > 25%
    b_tok = float(b.get("avg_est_tokens") or 0)
    c_tok = float(c.get("avg_est_tokens") or 0)
    if b_tok and c_tok > b_tok * 1.25:
        regression = True
        reasons.append("token_budget_regression")
    return {
        "regression": regression,
        "reasons": reasons,
        "baseline": b,
        "candidate": c,
        "decision": "reject" if regression else "accept",
    }
