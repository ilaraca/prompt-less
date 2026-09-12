"""Evals leves sobre fixtures baseline — métricas de qualidade/custo."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.run import run

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
DEFAULT_CASES = ("happy_path", "access_denied", "two_services", "ambiguous_status")


@dataclass
class CaseScore:
    service_match: bool = False
    expected_status_match: bool = False
    signals_present: bool = False
    ownership_match: bool = False
    status_ok: bool = False
    unexpected_inferences: int = 0
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return (
            self.status_ok
            and self.service_match
            and self.expected_status_match
            and self.signals_present
            and self.ownership_match
            and self.unexpected_inferences == 0
        )

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "passed": self.passed}


def _load_expected(case_id: str) -> dict[str, Any]:
    path = FIXTURES / case_id / "expected.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _artifact_blob(result: dict[str, Any], output_root: Path) -> str:
    parts: list[str] = []
    for p in output_root.rglob("*"):
        if p.suffix.lower() in {".md", ".yaml", ".yml", ".json", ".txt"} and p.is_file():
            try:
                parts.append(p.read_text(encoding="utf-8"))
            except OSError:
                continue
    # também texto embutido em claims/questions
    for c in result.get("claims") or []:
        parts.append(str(c.get("text") or ""))
    for q in result.get("questions") or []:
        parts.append(str(q))
    for ctx in result.get("by_context") or []:
        for c in ctx.get("claims") or []:
            parts.append(str(c.get("text") or ""))
        for q in ctx.get("questions") or []:
            parts.append(str(q))
        val = ctx.get("validation") or {}
        for issue in val.get("issues") or []:
            parts.append(str(issue.get("message") or ""))
    return "\n".join(parts).lower()


def _collect_services(result: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    if result.get("contexts"):
        found.update(str(s) for s in result["contexts"] if s and s != "_unassigned")
    for ctx in result.get("by_context") or []:
        sid = (ctx.get("servico") or {}).get("id") or ctx.get("context")
        if sid and sid != "_unassigned":
            found.add(str(sid))
    svc = (result.get("servico") or {}).get("id")
    if svc and svc != "_unassigned":
        found.add(str(svc))
    return found


def _collect_repos(result: dict[str, Any]) -> dict[str, set[str]]:
    ownership: dict[str, set[str]] = {}
    for ctx in result.get("by_context") or []:
        sid = (ctx.get("servico") or {}).get("id") or ctx.get("context")
        if not sid:
            continue
        repos = (ctx.get("servico") or {}).get("repos") or []
        ownership[str(sid)] = {str(r) for r in repos}
    return ownership


def score_case(
    expected: dict[str, Any],
    result: dict[str, Any],
    *,
    output_root: Path | None = None,
) -> CaseScore:
    expect_blocked = bool(expected.get("expect_blocked"))
    status = result.get("status")
    status_ok = (status == "blocked") if expect_blocked else (status == "completed")

    # se split bloqueou um contexto, by_context pode ter blocked parcial
    if not expect_blocked and status == "completed":
        status_ok = True
    if expect_blocked and status != "blocked":
        # aceita blocked em qualquer by_context
        status_ok = any(
            (c.get("status") == "blocked") for c in (result.get("by_context") or [])
        ) or status == "blocked"

    expected_services = {str(s) for s in (expected.get("services") or [])}
    found_services = _collect_services(result)
    if expect_blocked and not found_services:
        # run bloqueada cedo ainda pode listar services do expected via contexts
        found_services = set(result.get("contexts") or [])
    service_match = expected_services.issubset(found_services) if expected_services else True

    blob = _artifact_blob(result, output_root) if output_root else ""
    # statuses HTTP: devem aparecer no conteúdo gerado / questions / claims
    expected_statuses = [int(s) for s in (expected.get("http_statuses") or [])]
    if expected_statuses:
        status_hits = sum(1 for s in expected_statuses if str(s) in blob)
        # exige todos os status anotados (gate 100%)
        expected_status_match = status_hits == len(expected_statuses)
    else:
        expected_status_match = True

    signals = [str(s).lower() for s in (expected.get("signals") or [])]
    signals_present = all(sig in blob for sig in signals) if signals else True

    # ownership
    expected_own = expected.get("ownership") or {}
    found_own = _collect_repos(result)
    ownership_match = True
    if expected_own:
        for sid, repos in expected_own.items():
            got = found_own.get(str(sid)) or set()
            # em blocked cedo, ownership pode estar ausente — relaxa se blocked esperado
            if expect_blocked and not got:
                continue
            if not set(str(r) for r in repos).issubset(got):
                ownership_match = False
                break

    return CaseScore(
        service_match=service_match,
        expected_status_match=expected_status_match,
        signals_present=signals_present,
        ownership_match=ownership_match,
        status_ok=status_ok,
        unexpected_inferences=0,
        details={
            "expected_services": sorted(expected_services),
            "found_services": sorted(found_services),
            "expected_statuses": expected_statuses,
            "signals": signals,
        },
    )


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
        expected = _load_expected(case_id)
        score = score_case(expected, result, output_root=out)
        results.append(
            {
                "case_id": case_id,
                "status": result.get("status"),
                "ok": score.passed,
                "expect_blocked": bool(expected.get("expect_blocked")),
                "score": score.to_dict(),
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
