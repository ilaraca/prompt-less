"""Evals leves sobre fixtures baseline — métricas de qualidade/custo."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.run import run

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
DEFAULT_CASES = ("happy_path", "access_denied", "two_services", "ambiguous_status")
_HTTP_RE = re.compile(r"(?:HTTP\s+)?\b([1-5]\d{2})\b", re.IGNORECASE)
_ARTIFACT_NAMES = {"historia.md", "prd.md"}


@dataclass
class CaseScore:
    service_match: bool = False
    expected_status_match: bool = False
    signals_present: bool = False
    ownership_match: bool = False
    status_ok: bool = False
    unexpected_inferences: int = 0
    layer_scores: dict[str, Any] = field(default_factory=dict)
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


def _load_specs(output_root: Path | None) -> list[dict[str, Any]]:
    if output_root is None or not output_root.exists():
        return []
    specs: list[dict[str, Any]] = []
    for path in output_root.rglob("canonical-spec.yaml"):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except OSError:
            continue
        if isinstance(data, dict):
            specs.append(data)
    return specs


def _load_final_artifacts(output_root: Path | None) -> list[str]:
    """Só artefatos finais (história/PRD), não provenance/validation/packages."""
    if output_root is None or not output_root.exists():
        return []
    texts: list[str] = []
    for path in output_root.rglob("*"):
        if not path.is_file():
            continue
        if path.name.lower() not in _ARTIFACT_NAMES:
            continue
        try:
            texts.append(path.read_text(encoding="utf-8"))
        except OSError:
            continue
    return texts


def _spec_text_blob(spec: dict[str, Any]) -> str:
    parts: list[str] = []
    for claim in spec.get("claims") or []:
        parts.append(str(claim.get("text") or ""))
    for rf in spec.get("requirements") or []:
        parts.append(str(rf.get("text") or ""))
    for ac in spec.get("acceptance_criteria") or []:
        parts.extend(
            str(ac.get(k) or "") for k in ("given", "when", "then", "id", "requirement_id")
        )
    for err in spec.get("errors") or []:
        parts.append(str(err.get("trigger") or ""))
        parts.append(str(err.get("status") or ""))
        parts.append(str(err.get("code") or ""))
    for q in spec.get("open_questions") or []:
        parts.append(str(q.get("text") or ""))
    for op in spec.get("operations") or []:
        parts.append(str(op.get("name") or ""))
        parts.append(str(op.get("path") or ""))
    return "\n".join(parts).lower()


def collect_spec_statuses(spec: dict[str, Any]) -> set[int]:
    """HTTP statuses declarados no Canonical Spec (errors + textos RF/AC/Q)."""
    found: set[int] = set()
    for error in spec.get("errors") or []:
        if error.get("status") is not None:
            try:
                found.add(int(error["status"]))
            except (TypeError, ValueError):
                continue
    for bucket in (
        spec.get("requirements") or [],
        spec.get("acceptance_criteria") or [],
        spec.get("open_questions") or [],
    ):
        for item in bucket:
            text = " ".join(
                str(item.get(k) or "")
                for k in ("text", "then", "when", "given")
            )
            for match in _HTTP_RE.finditer(text):
                found.add(int(match.group(1)))
    return found


def _collect_resolved_inferences(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """ResolvedValues com origin inferred/default e requires_review=false."""
    unexpected: list[dict[str, Any]] = []
    for op in spec.get("operations") or []:
        status = op.get("success_status")
        if not isinstance(status, dict):
            continue
        origin = str(status.get("origin") or "")
        requires_review = bool(status.get("requires_review"))
        if origin in {"inferred", "default"} and not requires_review:
            unexpected.append(
                {
                    "id": op.get("id"),
                    "field": "success_status",
                    "origin": origin,
                    "requires_review": requires_review,
                }
            )
    return unexpected


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


def _claims_blob_from_result(result: dict[str, Any]) -> str:
    parts: list[str] = []
    for c in result.get("claims") or []:
        parts.append(str(c.get("text") or ""))
    for ctx in result.get("by_context") or []:
        for c in ctx.get("claims") or []:
            parts.append(str(c.get("text") or ""))
    return "\n".join(parts).lower()


def score_case(
    expected: dict[str, Any],
    result: dict[str, Any],
    *,
    output_root: Path | None = None,
) -> CaseScore:
    expect_blocked = bool(expected.get("expect_blocked"))
    status = result.get("status")
    status_ok = (status == "blocked") if expect_blocked else (status == "completed")

    if expect_blocked and status != "blocked":
        status_ok = any(
            (c.get("status") == "blocked") for c in (result.get("by_context") or [])
        ) or status == "blocked"

    expected_services = {str(s) for s in (expected.get("services") or [])}
    found_services = _collect_services(result)
    if expect_blocked and not found_services:
        found_services = set(result.get("contexts") or [])
    service_match = expected_services.issubset(found_services) if expected_services else True

    specs = _load_specs(output_root)
    # blocked runs ainda persistem canonical-spec antes do raise
    actual_statuses: set[int] = set()
    for spec in specs:
        actual_statuses |= collect_spec_statuses(spec)

    expected_statuses = {int(s) for s in (expected.get("http_statuses") or [])}
    # fixture decide: exact (default) | subset
    mode = str(expected.get("http_status_mode") or "subset").lower()
    if not expected_statuses:
        expected_status_match = True
    elif mode == "exact":
        expected_status_match = expected_statuses == actual_statuses
    else:
        expected_status_match = expected_statuses.issubset(actual_statuses)

    # sinais: ingestion (claims) E/OU canonical spec — não provenance/packages
    signals = [str(s).lower() for s in (expected.get("signals") or [])]
    claims_blob = _claims_blob_from_result(result)
    spec_blob = "\n".join(_spec_text_blob(s) for s in specs)
    artifact_blob = "\n".join(t.lower() for t in _load_final_artifacts(output_root))
    if signals:
        ingestion_ok = all(sig in claims_blob for sig in signals)
        spec_ok = all(sig in spec_blob for sig in signals)
        # para casos blocked sem artefato, spec/claims bastam
        if expect_blocked:
            signals_present = ingestion_ok or spec_ok
        else:
            art_ok = all(sig in artifact_blob for sig in signals) if artifact_blob else False
            signals_present = (ingestion_ok or spec_ok) and (art_ok or spec_ok)
    else:
        ingestion_ok = True
        spec_ok = True
        art_ok = True
        signals_present = True

    expected_own = expected.get("ownership") or {}
    found_own = _collect_repos(result)
    ownership_match = True
    if expected_own:
        for sid, repos in expected_own.items():
            got = found_own.get(str(sid)) or set()
            if expect_blocked and not got:
                continue
            if not set(str(r) for r in repos).issubset(got):
                ownership_match = False
                break

    max_unreviewed = int(expected.get("max_unreviewed_inferences") or 0)
    forbidden = [str(x).lower() for x in (expected.get("forbidden_inferences") or [])]
    unexpected_items: list[dict[str, Any]] = []
    for spec in specs:
        unexpected_items.extend(_collect_resolved_inferences(spec))
        blob = _spec_text_blob(spec)
        for phrase in forbidden:
            if phrase and phrase in blob:
                unexpected_items.append({"id": "forbidden", "origin": phrase})

    unexpected_inferences = len(unexpected_items)
    # gate: acima do máximo permitido
    if unexpected_inferences <= max_unreviewed:
        # zera para o gate booleano da CaseScore
        gate_unexpected = 0
    else:
        gate_unexpected = unexpected_inferences

    # requirements traceability no spec
    traceable = True
    for spec in specs:
        claim_ids = {c.get("id") for c in (spec.get("claims") or []) if c.get("id")}
        for rf in spec.get("requirements") or []:
            if rf.get("status") == "baseline":
                continue
            src = list(rf.get("source_claims") or [])
            if not src or any(s not in claim_ids for s in src):
                traceable = False
                break

    layer_scores = {
        "ingestion": {"expected_signals_found": ingestion_ok if signals else True},
        "canonical_spec": {
            "expected_http_statuses": expected_status_match,
            "expected_signals": spec_ok if signals else True,
            "all_requirements_traceable": traceable if specs else expect_blocked,
        },
        "artifacts": {
            "prd_historia_signals": (
                True
                if expect_blocked or not signals
                else all(sig in artifact_blob for sig in signals)
            )
        },
        "provenance": {
            "unexpected_inferences": unexpected_inferences,
            "max_unreviewed_inferences": max_unreviewed,
        },
    }

    return CaseScore(
        service_match=service_match,
        expected_status_match=expected_status_match,
        signals_present=signals_present,
        ownership_match=ownership_match,
        status_ok=status_ok,
        unexpected_inferences=gate_unexpected,
        layer_scores=layer_scores,
        details={
            "expected_services": sorted(expected_services),
            "found_services": sorted(found_services),
            "expected_statuses": sorted(expected_statuses),
            "actual_spec_statuses": sorted(actual_statuses),
            "http_status_mode": mode,
            "signals": signals,
            "unexpected_items": unexpected_items[:20],
            "specs_loaded": len(specs),
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
            tokens = [
                int(c.get("est_tokens") or 0)
                for c in result["by_context"]
                if c.get("est_tokens")
            ]
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
