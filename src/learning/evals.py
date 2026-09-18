"""Evals leves sobre fixtures baseline — métricas de qualidade/custo."""
from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.run import run
from src.runtime.atomic_io import UnsafePath
from src.runtime.integrity import verify_run_dir
from src.runtime.run_context import InvalidRunId, RunContext, validate_run_id
from src.runtime.run_store import TERMINAL_STATUSES, RunStore

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
DEFAULT_CASES = (
    "happy_path",
    "access_denied",
    "two_services",
    "ambiguous_status",
    "eval_adversarial",
    "eval_multi_context",
)
_HTTP_RE = re.compile(r"(?:HTTP\s+)?\b([1-5]\d{2})\b", re.IGNORECASE)
_ARTIFACT_NAMES = {"historia.md", "prd.md"}
_SPEC_NAME = "canonical-spec.yaml"
_QUALITY_UP = ("claim_recall", "traceability_rate", "pass_rate")
_QUALITY_DOWN = ("unexpected_inferences", "avg_est_tokens", "avg_latency_ms")


@dataclass
class CaseScore:
    service_match: bool = False
    expected_status_match: bool = False
    signals_present: bool = False
    ownership_match: bool = False
    status_ok: bool = False
    unexpected_inferences: int = 0
    claim_recall: float = 0.0
    traceable: bool = True
    critical: bool = False
    selection_ok: bool = True
    artifacts_released: bool = False
    latency_ms: float = 0.0
    layer_scores: dict[str, Any] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        recall_ok = (not self.critical) or self.claim_recall >= 1.0
        trace_ok = (not self.critical) or self.traceable
        return (
            self.selection_ok
            and self.status_ok
            and self.service_match
            and self.expected_status_match
            and self.signals_present
            and self.ownership_match
            and self.unexpected_inferences == 0
            and recall_ok
            and trace_ok
        )

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "passed": self.passed}


@dataclass
class EvalRunSelection:
    """Evidência de uma única run, selecionada só pelo manifesto."""

    run_id: str
    status: str
    specs: list[dict[str, Any]] = field(default_factory=list)
    final_artifacts: list[str] = field(default_factory=list)
    files_used: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    artifacts_released: bool = False

    @property
    def ok(self) -> bool:
        return not self.errors


def _load_expected(case_id: str) -> dict[str, Any]:
    path = FIXTURES / case_id / "expected.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _resolve_eval_root(
    *,
    output_root: Path | None,
    run_dir: Path | str | None,
) -> Path | None:
    if run_dir is not None:
        return Path(run_dir).resolve().parent.parent
    if output_root is not None:
        return Path(output_root)
    return None


def select_run_evidence(
    *,
    root: Path,
    run_id: str,
    verify_integrity_chain: bool = True,
) -> EvalRunSelection:
    """
    Carrega specs/artefatos finais apenas do manifesto de `runs/<run_id>/`.

    Espelhos de compatibilidade (`outputs/`) não entram na seleção. Manifesto
    ausente, `run_id` divergente ou sha256 adulterado reprovam a seleção.
    Run `blocked` pode ser avaliada, mas `artifacts_released` fica falso.
    """
    errors: list[str] = []
    try:
        rid = validate_run_id(run_id)
    except InvalidRunId as exc:
        return EvalRunSelection(run_id=str(run_id), status="", errors=[str(exc)])

    root = Path(root)
    run_path = root / "runs" / rid
    if not run_path.is_dir():
        return EvalRunSelection(
            run_id=rid,
            status="",
            errors=[f"run '{rid}' ausente em {run_path}"],
        )

    store = RunStore(RunContext.create(root=root, objective="eval", run_id=rid))
    manifest = store.read_manifest()
    if not manifest:
        return EvalRunSelection(
            run_id=rid,
            status="",
            errors=[f"manifesto ausente para run '{rid}'"],
        )

    declared = str(manifest.get("run_id") or "")
    if declared and declared != rid:
        errors.append(
            f"run divergente: manifesto declara '{declared}', seleção pediu '{rid}'"
        )

    status = str(manifest.get("status") or "")
    if status not in TERMINAL_STATUSES:
        errors.append(
            f"status da run '{rid}' não é terminal para eval: {status or '<vazio>'!r}"
        )

    entries = store.sealed_file_entries()
    if not entries:
        errors.append(f"manifesto da run '{rid}' sem integrity.files")

    if verify_integrity_chain:
        report = verify_run_dir(run_path)
        if not report.get("ok"):
            for err in report.get("errors") or []:
                msg = str(err)
                if msg not in errors:
                    errors.append(msg)

    specs: list[dict[str, Any]] = []
    finals: list[str] = []
    used: list[str] = []
    for entry in entries:
        rel = str(entry.get("path") or "")
        name = Path(rel).name.lower()
        if name != _SPEC_NAME and name not in _ARTIFACT_NAMES:
            continue
        try:
            path = store.verify_sealed_entry(entry)
        except (UnsafePath, FileNotFoundError, ValueError, OSError) as exc:
            errors.append(str(exc))
            continue
        used.append(rel)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"falha ao ler {rel}: {exc}")
            continue
        if name == _SPEC_NAME:
            try:
                data = yaml.safe_load(text) or {}
            except yaml.YAMLError as exc:
                errors.append(f"canonical-spec inválido ({rel}): {exc}")
                continue
            if isinstance(data, dict):
                specs.append(data)
            else:
                errors.append(f"canonical-spec não-objeto em {rel}")
        else:
            finals.append(text)

    # bloqueada pode ser scoreada; artefatos não liberados p/ implementação
    released = status == "completed" and not errors
    return EvalRunSelection(
        run_id=rid,
        status=status,
        specs=specs,
        final_artifacts=finals,
        files_used=used,
        errors=errors,
        artifacts_released=released,
    )


def _load_specs(
    output_root: Path | None,
    *,
    run_id: str | None = None,
    run_dir: Path | str | None = None,
    selection: EvalRunSelection | None = None,
) -> list[dict[str, Any]]:
    """Só specs da run selecionada — sem rglob em outputs/ nem runs antigas."""
    if selection is not None:
        return list(selection.specs)
    if not run_id:
        return []
    root = _resolve_eval_root(output_root=output_root, run_dir=run_dir)
    if root is None:
        return []
    return list(select_run_evidence(root=root, run_id=run_id).specs)


def _load_final_artifacts(
    output_root: Path | None,
    *,
    run_id: str | None = None,
    run_dir: Path | str | None = None,
    selection: EvalRunSelection | None = None,
) -> list[str]:
    """Só história/PRD selados no manifesto da run — espelho fora da seleção."""
    if selection is not None:
        return list(selection.final_artifacts)
    if not run_id:
        return []
    root = _resolve_eval_root(output_root=output_root, run_dir=run_dir)
    if root is None:
        return []
    return list(select_run_evidence(root=root, run_id=run_id).final_artifacts)


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
    run_id: str | None = None,
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

    rid = run_id or (str(result["run_id"]) if result.get("run_id") else None)
    run_dir = result.get("run_dir")
    selection: EvalRunSelection | None = None
    selection_ok = True
    artifacts_released = False
    selection_errors: list[str] = []

    needs_disk = output_root is not None or run_dir is not None or rid is not None
    if needs_disk:
        if not rid:
            selection_ok = False
            selection_errors.append(
                "run_id obrigatório para carregar evidência de eval "
                "(seleção por execução; rglob desativado)"
            )
            specs: list[dict[str, Any]] = []
            artifact_texts: list[str] = []
        else:
            root = _resolve_eval_root(output_root=output_root, run_dir=run_dir)
            if root is None:
                selection_ok = False
                selection_errors.append(
                    "root da run ausente: informe output_root ou result['run_dir']"
                )
                specs = []
                artifact_texts = []
            else:
                selection = select_run_evidence(root=root, run_id=rid)
                selection_ok = selection.ok
                selection_errors = list(selection.errors)
                specs = list(selection.specs)
                # blocked: scoreável, mas artefatos não liberados p/ implementação
                if selection.artifacts_released:
                    artifact_texts = list(selection.final_artifacts)
                    artifacts_released = True
                else:
                    artifact_texts = []
                    artifacts_released = False
                    if selection.status == "blocked" and expect_blocked:
                        # specs da run bloqueada ainda alimentam o score
                        pass
                    elif selection.status == "blocked" and not expect_blocked:
                        selection_ok = False
                        if "run bloqueada sem expect_blocked" not in selection_errors:
                            selection_errors.append(
                                "run bloqueada: artefatos não liberados para implementação"
                            )
    else:
        specs = []
        artifact_texts = []

    # blocked runs ainda persistem canonical-spec antes do raise
    actual_statuses: set[int] = set()
    for spec in specs:
        actual_statuses |= collect_spec_statuses(spec)

    expected_statuses = {int(s) for s in (expected.get("http_statuses") or [])}
    critical = bool(expected.get("critical"))
    explicit_mode = expected.get("http_status_mode")
    if explicit_mode:
        mode = str(explicit_mode).lower()
    elif critical:
        # HTTP crítico exige igualdade, salvo regra explícita na fixture
        mode = "exact"
    else:
        mode = "subset"
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
    artifact_blob = "\n".join(t.lower() for t in artifact_texts)
    combined_blob = f"{claims_blob}\n{spec_blob}"
    if signals:
        hits = sum(1 for sig in signals if sig in combined_blob)
        claim_recall = round(hits / len(signals), 3)
    else:
        claim_recall = 1.0
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
        "ingestion": {
            "expected_signals_found": ingestion_ok if signals else True,
            "claim_recall": claim_recall,
        },
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
            ),
            "released_for_implementation": artifacts_released,
        },
        "provenance": {
            "unexpected_inferences": unexpected_inferences,
            "max_unreviewed_inferences": max_unreviewed,
        },
        "selection": {
            "ok": selection_ok,
            "run_id": rid,
            "status": selection.status if selection else None,
            "errors": selection_errors,
            "files_used": list(selection.files_used) if selection else [],
        },
    }

    return CaseScore(
        service_match=service_match,
        expected_status_match=expected_status_match,
        signals_present=signals_present,
        ownership_match=ownership_match,
        status_ok=status_ok,
        unexpected_inferences=gate_unexpected,
        claim_recall=claim_recall,
        traceable=traceable if specs else expect_blocked,
        critical=critical,
        selection_ok=selection_ok,
        artifacts_released=artifacts_released,
        latency_ms=float(expected.get("_latency_ms") or 0),
        layer_scores=layer_scores,
        details={
            "expected_services": sorted(expected_services),
            "found_services": sorted(found_services),
            "expected_statuses": sorted(expected_statuses),
            "actual_spec_statuses": sorted(actual_statuses),
            "http_status_mode": mode,
            "http_status_mode_explicit": bool(explicit_mode),
            "signals": signals,
            "claim_recall": claim_recall,
            "unexpected_items": unexpected_items[:20],
            "specs_loaded": len(specs),
            "fixture_kind": expected.get("fixture_kind"),
            "run_id": rid,
            "selection_ok": selection_ok,
            "selection_errors": selection_errors,
            "artifacts_released": artifacts_released,
        },
    )


def _resolve_eval_cfg(
    workspace: Any | None,
    config_root: Path | None,
    cfg: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if cfg is not None:
        return cfg
    from src.runtime.config_load import load_merged_cfg

    path: Path | None = None
    if config_root is not None:
        path = Path(config_root)
    elif workspace is not None:
        to_dict = getattr(workspace, "to_dict", None)
        payload = to_dict() if callable(to_dict) else workspace
        if hasattr(workspace, "path"):
            path = Path(workspace.path)
        elif isinstance(payload, dict) and payload.get("path"):
            path = Path(str(payload["path"]))
    if path is None:
        return None
    config_dir = path / "config"
    if config_dir.is_dir():
        return load_merged_cfg(path)
    return None


def run_eval_suite(
    *,
    cases: tuple[str, ...] | list[str] = DEFAULT_CASES,
    output_root: Path,
    workspace: Any | None = None,
    run_id_prefix: str | None = None,
    config_root: Path | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    to_dict = getattr(workspace, "to_dict", None)
    ws_payload = to_dict() if callable(to_dict) else workspace
    eval_cfg = _resolve_eval_cfg(workspace, config_root, cfg)
    prefix = run_id_prefix or "eval"
    for case_id in cases:
        inputs = FIXTURES / case_id
        if not inputs.is_dir():
            continue
        out = output_root / case_id
        out.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        result = run(
            "historia",
            dry_run=True,
            inputs_dir=inputs,
            output_root=out,
            run_id=f"{prefix}-{case_id}"[:64],
            cfg=eval_cfg,
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
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
        expected = {**expected, "_latency_ms": latency_ms}
        score = score_case(
            expected,
            result,
            output_root=out,
            run_id=str(result.get("run_id") or ""),
        )
        score.latency_ms = latency_ms
        results.append(
            {
                "case_id": case_id,
                "status": result.get("status"),
                "ok": score.passed,
                "critical": bool(expected.get("critical")),
                "fixture_kind": expected.get("fixture_kind"),
                "expect_blocked": bool(expected.get("expect_blocked")),
                "score": score.to_dict(),
                "est_tokens_max": max(tokens) if tokens else 0,
                "claims_count": result.get("claims_count") or 0,
                "claim_recall": score.claim_recall,
                "traceable": score.traceable,
                "unexpected_inferences": score.unexpected_inferences,
                "latency_ms": latency_ms,
            }
        )

    passed = sum(1 for r in results if r["ok"])
    n = max(len(results), 1)
    summary = {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "pass_rate": round(passed / n, 3),
        "avg_est_tokens": round(sum(r["est_tokens_max"] for r in results) / n, 1),
        "claim_recall": round(sum(float(r["claim_recall"]) for r in results) / n, 3),
        "traceability_rate": round(
            sum(1 for r in results if r["traceable"]) / n, 3
        ),
        "unexpected_inferences": int(
            sum(int(r["unexpected_inferences"]) for r in results)
        ),
        "avg_latency_ms": round(sum(float(r["latency_ms"]) for r in results) / n, 1),
        "http_status_match_rate": round(
            sum(1 for r in results if (r.get("score") or {}).get("expected_status_match"))
            / n,
            3,
        ),
    }
    payload: dict[str, Any] = {
        "cases": results,
        "summary": summary,
        "workspace": ws_payload if isinstance(ws_payload, dict) else None,
    }
    return payload


def _case_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(c.get("case_id")): c for c in (report.get("cases") or []) if c.get("case_id")}


def _workspaces_distinct(baseline: dict[str, Any], candidate: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    b = baseline.get("workspace") or {}
    c = candidate.get("workspace") or {}
    info = {"baseline": b, "candidate": c, "distinct": True}
    if not b and not c:
        return True, info
    path_ok = bool(b.get("path") and c.get("path") and b["path"] != c["path"])
    commit_ok = bool(
        b.get("workspace_commit")
        and c.get("workspace_commit")
        and b["workspace_commit"] != c["workspace_commit"]
    )
    # Apply temporal no mesmo root: paths iguais, mas snapshot/commit mudam.
    snap_ok = bool(
        b.get("snapshot_sha256")
        and c.get("snapshot_sha256")
        and b["snapshot_sha256"] != c["snapshot_sha256"]
    )
    distinct = bool(commit_ok and (path_ok or snap_ok))
    info["distinct"] = distinct
    return distinct, info


def _metric_block(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "claim_recall",
        "traceability_rate",
        "unexpected_inferences",
        "pass_rate",
        "avg_est_tokens",
        "avg_latency_ms",
        "http_status_match_rate",
    )
    out: dict[str, Any] = {}
    for key in keys:
        b = float(baseline.get(key) or 0)
        c = float(candidate.get(key) or 0)
        out[key] = {"baseline": b, "candidate": c, "delta": round(c - b, 4)}
    return out


def _improved(metrics: dict[str, Any]) -> bool:
    for key in _QUALITY_UP:
        if float((metrics.get(key) or {}).get("delta") or 0) > 0:
            return True
    for key in _QUALITY_DOWN:
        if float((metrics.get(key) or {}).get("delta") or 0) < 0:
            return True
    return False


def compare_evals(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    b = baseline.get("summary") or {}
    c = candidate.get("summary") or {}
    regression = False
    critical_regression = False
    reasons: list[str] = []
    case_gates: list[dict[str, Any]] = []

    if float(c.get("pass_rate") or 0) < float(b.get("pass_rate") or 0):
        regression = True
        reasons.append("pass_rate_decreased")
    b_tok = float(b.get("avg_est_tokens") or 0)
    c_tok = float(c.get("avg_est_tokens") or 0)
    if b_tok and c_tok > b_tok * 1.25:
        regression = True
        reasons.append("token_budget_regression")

    b_cases = _case_map(baseline)
    c_cases = _case_map(candidate)
    for case_id, b_case in b_cases.items():
        c_case = c_cases.get(case_id)
        if not c_case:
            continue
        critical = bool(b_case.get("critical") or c_case.get("critical"))
        gate = {
            "case_id": case_id,
            "critical": critical,
            "baseline_ok": bool(b_case.get("ok")),
            "candidate_ok": bool(c_case.get("ok")),
        }
        if critical and b_case.get("ok") and not c_case.get("ok"):
            critical_regression = True
            regression = True
            reasons.append(f"critical_case_regressed:{case_id}")
            gate["regressed"] = True
        case_gates.append(gate)

    distinct, ws_info = _workspaces_distinct(baseline, candidate)
    if (baseline.get("workspace") or candidate.get("workspace")) and not distinct:
        regression = True
        reasons.append("workspaces_not_distinct")

    metrics = _metric_block(b, c)
    improved = (not regression) and (not critical_regression) and _improved(metrics)
    reject = regression or critical_regression
    return {
        "regression": regression,
        "critical_regression": critical_regression,
        "improved": improved,
        "reasons": reasons,
        "baseline": b,
        "candidate": c,
        "case_gates": case_gates,
        "metrics": metrics,
        "workspaces": ws_info,
        "decision": "reject" if reject else "accept",
    }
