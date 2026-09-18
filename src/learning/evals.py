"""Evals leves sobre fixtures baseline — métricas de qualidade/custo."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.domain.spec import ResolvedInt
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
# Hold-out P3: fora da orientação da mudança; regressão/falha crítica veta promoção.
RESERVED_CASES = ("eval_adversarial",)
_ARTIFACT_NAMES = {"historia.md", "prd.md"}
_SPEC_NAME = "canonical-spec.yaml"
# Benefício demonstrável para promoção — latência fica fora (jitter).
_QUALITY_UP = ("claim_recall", "traceability_rate", "pass_rate")
_QUALITY_DOWN = ("unexpected_inferences", "avg_est_tokens")
_REPORTED_ONLY = ("avg_latency_ms", "http_status_match_rate")


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
    # Gates de aprovação (AND obrigatório; diagnóstico fica em layer_scores/details)
    required_gates: dict[str, bool] = field(default_factory=dict)
    fail_reasons: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        if self.required_gates:
            return all(self.required_gates.values())
        # fallback legado (não deve ocorrer após score_case)
        recall_ok = (not self.critical) or self.claim_recall >= 1.0
        return (
            self.selection_ok
            and self.status_ok
            and self.service_match
            and self.expected_status_match
            and self.signals_present
            and self.ownership_match
            and self.unexpected_inferences == 0
            and recall_ok
            and self.traceable
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


def _artifact_filename(name: str) -> str:
    base = str(name).strip().lower()
    if base.endswith(".md"):
        return base
    return f"{base}.md"


def _expected_artifacts_present(
    output_root: Path | None, expected_artifacts: list[str]
) -> tuple[bool, list[str]]:
    """Verifica presença física dos artefatos finais declarados na fixture."""
    if not expected_artifacts:
        return True, []
    if output_root is None or not output_root.exists():
        return False, list(expected_artifacts)
    found_names = {
        p.name.lower()
        for p in output_root.rglob("*")
        if p.is_file() and p.name.lower() in _ARTIFACT_NAMES
    }
    missing = [
        name
        for name in expected_artifacts
        if _artifact_filename(name) not in found_names
    ]
    return not missing, missing


def _blocking_pendencies(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for spec in specs:
        for q in spec.get("open_questions") or []:
            if bool(q.get("blocking")):
                found.append(
                    {
                        "id": q.get("id"),
                        "text": q.get("text"),
                        "service_id": spec.get("service_id"),
                    }
                )
    return found


def _collect_block_reasons(result: dict[str, Any]) -> set[str]:
    reasons: set[str] = set()
    if result.get("reason"):
        reasons.add(str(result["reason"]))
    for ctx in result.get("by_context") or []:
        if ctx.get("reason"):
            reasons.add(str(ctx["reason"]))
    return reasons


def _collect_block_codes(result: dict[str, Any]) -> set[str]:
    codes: set[str] = set()

    def _from_validation(val: Any) -> None:
        if not isinstance(val, dict):
            return
        for issue in val.get("issues") or []:
            if isinstance(issue, dict) and issue.get("code"):
                codes.add(str(issue["code"]))

    _from_validation(result.get("validation"))
    for ctx in result.get("by_context") or []:
        _from_validation(ctx.get("validation"))
    return codes


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


def _source_ref_valid(src: Any) -> bool:
    """SourceRef mínimo: document não vazio; start_line ≤ end_line se ambos existem."""
    if not isinstance(src, dict):
        return False
    if not str(src.get("document") or "").strip():
        return False
    start, end = src.get("start_line"), src.get("end_line")
    if start is not None and end is not None:
        try:
            if int(start) > int(end):
                return False
        except (TypeError, ValueError):
            return False
    return True


def _claim_has_valid_sources(claim: dict[str, Any]) -> bool:
    """Existência do id do claim não basta — exige SourceRef válido."""
    sources = claim.get("sources") or []
    if not sources:
        return False
    return all(_source_ref_valid(s) for s in sources)


def _spec_requirements_traceable(spec: dict[str, Any]) -> bool:
    """
    Rastreabilidade integral: RFs apontam para claims existentes **e** cada
    claim referenciado (e todo claim com id) carrega SourceRef válido.
    """
    claims = [c for c in (spec.get("claims") or []) if isinstance(c, dict)]
    claim_by_id = {str(c["id"]): c for c in claims if c.get("id")}
    for claim in claims:
        if claim.get("id") and not _claim_has_valid_sources(claim):
            return False
    for rf in spec.get("requirements") or []:
        if not isinstance(rf, dict):
            continue
        if rf.get("status") == "baseline":
            continue
        src = list(rf.get("source_claims") or [])
        if not src:
            return False
        for cid in src:
            key = str(cid)
            if key not in claim_by_id or not _claim_has_valid_sources(claim_by_id[key]):
                return False
    return True


def _resolved_success_value(raw: Any) -> int | None:
    """Sucesso tipado só conta quando resolvido — ausente/pendente sem presumir."""
    status = ResolvedInt.from_raw(raw)
    return int(status.value) if status.resolved and status.value is not None else None


def _norm_method(raw: Any) -> str | None:
    text = str(raw or "").strip().upper()
    return text or None


def _norm_path(raw: Any) -> str | None:
    text = str(raw or "").strip()
    return text or None


def collect_operation_contracts(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Contratos HTTP tipados por operação (método, rota, serviço, sucesso, erros).

    Texto livre de RF/AC/perguntas **não** entra — só `operations.success_status`
    resolvido e erros referenciados em `error_ids`.
    """
    errors_by_id = {
        str(err.get("id")): err
        for err in (spec.get("errors") or [])
        if isinstance(err, dict) and err.get("id")
    }
    service_fallback = str(spec.get("service_id") or "") or None
    contracts: list[dict[str, Any]] = []
    for op in spec.get("operations") or []:
        if not isinstance(op, dict):
            continue
        linked: list[int] = []
        for eid in op.get("error_ids") or []:
            err = errors_by_id.get(str(eid))
            if not err or err.get("status") is None:
                continue
            try:
                linked.append(int(err["status"]))
            except (TypeError, ValueError):
                continue
        owner = str(op.get("owner") or "") or service_fallback
        contracts.append(
            {
                "id": op.get("id"),
                "name": op.get("name"),
                "service": owner,
                "method": _norm_method(op.get("method")),
                "path": _norm_path(op.get("path")),
                "success_status": _resolved_success_value(op.get("success_status")),
                "error_statuses": sorted(set(linked)),
            }
        )
    return contracts


def collect_spec_statuses(spec: dict[str, Any]) -> set[int]:
    """HTTP statuses tipados no Canonical Spec (sucesso resolvido + erros da op).

    Números em RF/AC/perguntas **não** provam o contrato. Erros órfãos
    (sem `error_ids` na operação) também não entram.
    """
    found: set[int] = set()
    for contract in collect_operation_contracts(spec):
        success = contract.get("success_status")
        if success is not None:
            found.add(int(success))
        found.update(int(s) for s in (contract.get("error_statuses") or []))
    return found


def _op_identity_key(op: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(op.get("service") or "").strip(),
        str(op.get("method") or "").strip().upper(),
        str(op.get("path") or "").strip(),
    )


def _error_statuses_match(
    expected: set[int], actual: set[int], *, mode: str
) -> bool:
    if mode == "exact":
        return expected == actual
    return expected.issubset(actual)


def match_http_operations(
    expected_ops: list[dict[str, Any]],
    actual_ops: list[dict[str, Any]],
    *,
    mode: str = "subset",
) -> tuple[bool, list[dict[str, Any]]]:
    """Compara expectativas por operação; status noutro serviço/op não compensa."""
    if not expected_ops:
        return True, []
    remaining = list(enumerate(actual_ops))
    mismatches: list[dict[str, Any]] = []
    for exp in expected_ops:
        want_key = _op_identity_key(exp)
        hit_idx: int | None = None
        hit: dict[str, Any] | None = None
        for pos, (orig_i, candidate) in enumerate(remaining):
            if _op_identity_key(candidate) == want_key:
                hit_idx = pos
                hit = candidate
                _ = orig_i
                break
        if hit is None or hit_idx is None:
            mismatches.append(
                {
                    "reason": "operation_not_found",
                    "expected": {
                        "service": exp.get("service"),
                        "method": _norm_method(exp.get("method")),
                        "path": _norm_path(exp.get("path")),
                        "success_status": exp.get("success_status"),
                        "error_statuses": list(exp.get("error_statuses") or []),
                    },
                }
            )
            continue
        remaining.pop(hit_idx)

        exp_success = exp.get("success_status", "__omit__")
        got_success = hit.get("success_status")
        if exp_success != "__omit__":
            want_success = None if exp_success is None else int(exp_success)
            if want_success != got_success:
                mismatches.append(
                    {
                        "reason": "success_status_mismatch",
                        "expected": {
                            "service": exp.get("service"),
                            "method": _norm_method(exp.get("method")),
                            "path": _norm_path(exp.get("path")),
                            "success_status": want_success,
                        },
                        "actual_success_status": got_success,
                    }
                )

        exp_errors = {int(s) for s in (exp.get("error_statuses") or [])}
        got_errors = {int(s) for s in (hit.get("error_statuses") or [])}
        if exp.get("error_statuses") is not None or exp_errors:
            if not _error_statuses_match(exp_errors, got_errors, mode=mode):
                mismatches.append(
                    {
                        "reason": "error_statuses_mismatch",
                        "expected": sorted(exp_errors),
                        "actual": sorted(got_errors),
                        "mode": mode,
                        "operation": {
                            "service": exp.get("service"),
                            "method": _norm_method(exp.get("method")),
                            "path": _norm_path(exp.get("path")),
                        },
                    }
                )
    return (not mismatches), mismatches


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


def _budget_reports_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    if isinstance(result.get("budget_report"), dict):
        reports.append(result["budget_report"])
    for ctx in result.get("by_context") or []:
        if isinstance(ctx.get("budget_report"), dict):
            reports.append(ctx["budget_report"])
    return reports


_EXPLICIT_BUDGET_STATUSES = frozenset({"blocked", "split_required"})


def _critical_context_score(
    result: dict[str, Any], *, critical: bool
) -> dict[str, Any]:
    """
    Cobertura crítica no budget: casos critical exigem report sem omissões silenciosas.

    Sem budget_report (runs antigas) → n/a (não falha o gate).
    """
    _ = critical  # fixtures critical continuam no conjunto DEFAULT_CASES
    reports = _budget_reports_from_result(result)
    if not reports:
        return {
            "present": False,
            "complete": True,  # n/a — cobertura crítica permanece via fixtures critical
            "silent_critical_loss": False,
            "statuses": [],
            "explicit_block_or_split": False,
        }
    statuses = [str(r.get("status") or "") for r in reports]
    silent = False
    complete = True
    for r in reports:
        cov = r.get("critical_coverage") or {}
        if cov and not cov.get("complete", True):
            complete = False
        # omissão crítica sem diagnosis/status de split/block = perda silenciosa
        crit_om = r.get("critical_omissions") or []
        status = str(r.get("status") or "")
        if crit_om and status not in _EXPLICIT_BUDGET_STATUSES:
            silent = True
            complete = False
        if status in _EXPLICIT_BUDGET_STATUSES:
            # explícito — não é silencioso; complete=False é esperado
            complete = False
    explicit = bool(statuses) and all(s in _EXPLICIT_BUDGET_STATUSES for s in statuses)
    return {
        "present": True,
        "complete": complete,
        "silent_critical_loss": silent,
        "statuses": statuses,
        "explicit_block_or_split": explicit,
    }


def _critical_coverage_gate(crit: dict[str, Any]) -> bool:
    """
    Perda crítica / cobertura incompleta reprova run concluída.

    Bloqueio ou split explícito (`blocked` / `split_required`) permanece permitido.
    Ausência de budget_report (runs antigas) → n/a (passa).
    """
    if not crit.get("present"):
        return True
    if crit.get("silent_critical_loss"):
        return False
    if crit.get("complete"):
        return True
    # incomplete esperado só com tratamento explícito de block/split
    return bool(crit.get("explicit_block_or_split"))


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
    actual_contracts: list[dict[str, Any]] = []
    actual_statuses: set[int] = set()
    for spec in specs:
        contracts = collect_operation_contracts(spec)
        actual_contracts.extend(contracts)
        actual_statuses |= collect_spec_statuses(spec)

    expected_ops_raw = expected.get("http_operations")
    expected_ops: list[dict[str, Any]] = (
        [dict(op) for op in expected_ops_raw]
        if isinstance(expected_ops_raw, list)
        else []
    )
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

    op_mismatches: list[dict[str, Any]] = []
    if expected_ops:
        expected_status_match, op_mismatches = match_http_operations(
            expected_ops, actual_contracts, mode=mode
        )
    elif not expected_statuses:
        expected_status_match = True
    elif mode == "exact":
        expected_status_match = expected_statuses == actual_statuses
    else:
        expected_status_match = expected_statuses.issubset(actual_statuses)

    # sinais: diagnóstico por camada — aprovação NÃO permite compensação entre elas
    signals = [str(s).lower() for s in (expected.get("signals") or [])]
    claims_blob = _claims_blob_from_result(result)
    spec_blob = "\n".join(_spec_text_blob(s) for s in specs)
    artifact_blob = "\n".join(t.lower() for t in artifact_texts)
    expected_artifact_names = [str(a) for a in (expected.get("artifacts") or [])]
    if selection is not None:
        found_names = {Path(rel).name.lower() for rel in selection.files_used}
        missing_artifacts = [
            name
            for name in expected_artifact_names
            if _artifact_filename(name) not in found_names
        ]
        artifacts_present = not missing_artifacts
        # run bloqueada / não liberada: artefatos não contam para implementação
        if expected_artifact_names and not artifacts_released and not expect_blocked:
            artifacts_present = False
    else:
        artifacts_present, missing_artifacts = _expected_artifacts_present(
            output_root, expected_artifact_names
        )
    if signals:
        hits = sum(1 for sig in signals if sig in f"{claims_blob}\n{spec_blob}")
        claim_recall = round(hits / len(signals), 3)
        ingestion_ok = all(sig in claims_blob for sig in signals)
        spec_ok = all(sig in spec_blob for sig in signals)
        art_ok = (
            all(sig in artifact_blob for sig in signals) if artifact_blob else False
        )
    else:
        claim_recall = 1.0
        ingestion_ok = True
        spec_ok = True
        art_ok = True

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

    # requirements + SourceRef (id sozinho não basta; manifesto íntegro não compensa)
    traceable = True
    for spec in specs:
        if not _spec_requirements_traceable(spec):
            traceable = False
            break

    if not specs:
        # run completa sem spec não é rastreável; bloqueio esperado pode não emitir
        traceable = bool(expect_blocked)

    blocking = _blocking_pendencies(specs)
    no_blocking_pendencies = True if expect_blocked else (len(blocking) == 0)

    # causa esperada em casos de bloqueio
    actual_reasons = _collect_block_reasons(result)
    actual_codes = _collect_block_codes(result)
    expected_reason = expected.get("expected_reason") or expected.get("block_reason")
    expected_codes = {
        str(c) for c in (expected.get("expected_block_codes") or expected.get("block_codes") or [])
    }
    if expect_blocked:
        reason_ok = (
            True
            if not expected_reason
            else str(expected_reason) in actual_reasons
        )
        codes_ok = (
            True if not expected_codes else expected_codes.issubset(actual_codes)
        )
        block_cause_ok = reason_ok and codes_ok
    else:
        block_cause_ok = True

    # --- gates de aprovação (AND; uma dimensão falsa nunca compensa outra) ---
    needs_artifact_files = bool(expected_artifact_names) and not expect_blocked
    needs_artifact_signals = bool(signals) and needs_artifact_files
    needs_spec_signals = bool(signals) and bool(specs or not expect_blocked)

    gate_spec_signals = (not needs_spec_signals) or spec_ok
    gate_artifacts_present = (not needs_artifact_files) or artifacts_present
    gate_artifact_signals = (not needs_artifact_signals) or art_ok
    # spec presente: run completa exige canonical-spec carregado
    gate_spec_present = True if expect_blocked else bool(specs)
    gate_recall = (not critical) or claim_recall >= 1.0
    gate_unexpected_ok = gate_unexpected == 0
    critical_context = _critical_context_score(result, critical=critical)
    gate_critical_coverage = _critical_coverage_gate(critical_context)

    required_gates: dict[str, bool] = {
        "selection_ok": selection_ok,
        "status_ok": status_ok,
        "service_match": service_match,
        "expected_status_match": expected_status_match,
        "ownership_match": ownership_match,
        "unexpected_inferences_ok": gate_unexpected_ok,
        "spec_present": gate_spec_present,
        "spec_signals": gate_spec_signals,
        "artifacts_present": gate_artifacts_present,
        "artifact_signals": gate_artifact_signals,
        "traceable": traceable,
        "no_blocking_pendencies": no_blocking_pendencies,
        "claim_recall_ok": gate_recall,
        "block_cause_ok": block_cause_ok,
        "critical_coverage_ok": gate_critical_coverage,
    }

    fail_reasons = [name for name, ok in required_gates.items() if not ok]
    # signals_present: agregado diagnóstico (sem compensação spec→artefato)
    if expect_blocked:
        signals_present = (not signals) or (ingestion_ok or spec_ok)
    elif not signals:
        signals_present = True
    else:
        signals_present = gate_spec_signals and (
            gate_artifact_signals if needs_artifact_signals else True
        )

    layer_scores = {
        "ingestion": {
            "expected_signals_found": ingestion_ok if signals else True,
            "claim_recall": claim_recall,
        },
        "canonical_spec": {
            "expected_http_statuses": expected_status_match,
            "expected_signals": spec_ok if signals else True,
            "all_requirements_traceable": traceable,
            "spec_present": gate_spec_present,
        },
        "artifacts": {
            "prd_historia_signals": (
                True
                if expect_blocked or not signals
                else art_ok
            ),
            "expected_artifacts_present": gate_artifacts_present,
            "missing_artifacts": missing_artifacts,
            "released_for_implementation": artifacts_released,
        },
        "provenance": {
            "unexpected_inferences": unexpected_inferences,
            "max_unreviewed_inferences": max_unreviewed,
            "blocking_pendencies": len(blocking),
        },
        "block": {
            "expect_blocked": expect_blocked,
            "cause_ok": block_cause_ok,
            "actual_reasons": sorted(actual_reasons),
            "actual_codes": sorted(actual_codes),
        },
        "selection": {
            "ok": selection_ok,
            "run_id": rid,
            "status": selection.status if selection else None,
            "errors": selection_errors,
            "files_used": list(selection.files_used) if selection else [],
        },
        "critical_context": critical_context,
    }

    return CaseScore(
        service_match=service_match,
        expected_status_match=expected_status_match,
        signals_present=signals_present,
        ownership_match=ownership_match,
        status_ok=status_ok,
        unexpected_inferences=gate_unexpected,
        claim_recall=claim_recall,
        traceable=traceable,
        critical=critical,
        selection_ok=selection_ok,
        artifacts_released=artifacts_released,
        latency_ms=float(expected.get("_latency_ms") or 0),
        layer_scores=layer_scores,
        required_gates=required_gates,
        fail_reasons=fail_reasons,
        details={
            "expected_services": sorted(expected_services),
            "found_services": sorted(found_services),
            "expected_statuses": sorted(expected_statuses),
            "actual_spec_statuses": sorted(actual_statuses),
            "expected_http_operations": expected_ops,
            "actual_http_operations": actual_contracts,
            "http_operation_mismatches": op_mismatches[:20],
            "http_status_mode": mode,
            "http_status_mode_explicit": bool(explicit_mode),
            "signals": signals,
            "claim_recall": claim_recall,
            "unexpected_items": unexpected_items[:20],
            "specs_loaded": len(specs),
            "fixture_kind": expected.get("fixture_kind"),
            "missing_artifacts": missing_artifacts,
            "blocking_pendencies": blocking[:10],
            "expected_reason": expected_reason,
            "expected_block_codes": sorted(expected_codes),
            "actual_block_reasons": sorted(actual_reasons),
            "actual_block_codes": sorted(actual_codes),
            "fail_reasons": fail_reasons,
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
    """Benefício demonstrável — latência/jitter não conta para promoção."""
    for key in _QUALITY_UP:
        if float((metrics.get(key) or {}).get("delta") or 0) > 0:
            return True
    for key in _QUALITY_DOWN:
        if float((metrics.get(key) or {}).get("delta") or 0) < 0:
            return True
    return False


def _tolerance_index(
    tolerances: list[dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """Índice case_id → tolerância explícita (justificativa obrigatória)."""
    out: dict[str, dict[str, Any]] = {}
    for raw in tolerances or []:
        if not isinstance(raw, dict):
            continue
        case_id = str(raw.get("case_id") or "").strip()
        justification = str(raw.get("justification") or raw.get("reason") or "").strip()
        if not case_id or not justification:
            continue
        out[case_id] = {
            "case_id": case_id,
            "justification": justification,
            "dimension": raw.get("dimension"),
            "recorded": True,
        }
    return out


def _required_gates_of(case: dict[str, Any]) -> dict[str, bool]:
    score = case.get("score") or {}
    gates = score.get("required_gates") if isinstance(score, dict) else None
    if isinstance(gates, dict):
        return {str(k): bool(v) for k, v in gates.items()}
    return {}


def _dimension_regressions(
    b_case: dict[str, Any], c_case: dict[str, Any]
) -> list[str]:
    """Dimensões True→False; uma dimensão nunca compensa outra."""
    b_gates = _required_gates_of(b_case)
    c_gates = _required_gates_of(c_case)
    if not b_gates or not c_gates:
        return []
    flipped: list[str] = []
    for name, was_ok in b_gates.items():
        if was_ok and name in c_gates and not c_gates[name]:
            flipped.append(name)
    return flipped


def _comparable_sets(
    b_ids: set[str], c_ids: set[str]
) -> tuple[bool, list[str], list[str], list[str]]:
    missing_in_candidate = sorted(b_ids - c_ids)
    extra_in_candidate = sorted(c_ids - b_ids)
    reasons: list[str] = []
    if missing_in_candidate:
        reasons.append(
            "incomparable_missing_cases:" + ",".join(missing_in_candidate)
        )
    if extra_in_candidate:
        reasons.append(
            "incomparable_extra_cases:" + ",".join(extra_in_candidate)
        )
    return (not reasons), missing_in_candidate, extra_in_candidate, reasons


def partition_cases(
    cases: tuple[str, ...] | list[str],
    *,
    reserved: tuple[str, ...] | list[str] | None = None,
) -> dict[str, tuple[str, ...]]:
    """Separa suíte de comparação vs casos reservados (hold-out P3)."""
    reserved_set = set(reserved if reserved is not None else RESERVED_CASES)
    ordered = tuple(str(c) for c in cases)
    eval_cases = tuple(c for c in ordered if c not in reserved_set)
    reserved_cases = tuple(c for c in ordered if c in reserved_set)
    return {"eval_cases": eval_cases, "reserved_cases": reserved_cases}


def build_experiment_record(
    *,
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    comparison: dict[str, Any],
    diff: str = "",
    conditions: dict[str, Any] | None = None,
    reserved_cases: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    """Registro P3: referência, candidato, diff, condições e hold-out."""
    ws = comparison.get("workspaces") or {}
    return {
        "reference": ws.get("baseline") or baseline.get("workspace"),
        "candidate": ws.get("candidate") or candidate.get("workspace"),
        "diff": diff or str(comparison.get("diff") or ""),
        "conditions": dict(conditions or {}),
        "reserved_cases": list(
            reserved_cases if reserved_cases is not None else RESERVED_CASES
        ),
        "comparable": bool(comparison.get("comparable", True)),
        "decision": comparison.get("decision"),
        "reasons": list(comparison.get("reasons") or []),
        "tolerances_applied": list(comparison.get("tolerances_applied") or []),
        "metrics": comparison.get("metrics") or {},
    }


def compare_evals(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    tolerances: list[dict[str, Any]] | None = None,
    reserved_cases: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    """
    Compara evals com gate por caso/dimensão — sem compensação silenciosa.

    Pass→fail em qualquer caso marca regressão (mesmo com pass_rate igual).
    Crítico bloqueia; tolerância não crítica exige justificativa explícita.
    Conjuntos de casos distintos → comparação não conclusiva (reject).
    """
    b = baseline.get("summary") or {}
    c = candidate.get("summary") or {}
    regression = False
    critical_regression = False
    comparable = True
    reasons: list[str] = []
    case_gates: list[dict[str, Any]] = []
    tolerances_applied: list[dict[str, Any]] = []
    tol_idx = _tolerance_index(tolerances)

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
    comparable, missing, extra, set_reasons = _comparable_sets(
        set(b_cases), set(c_cases)
    )
    if set_reasons:
        reasons.extend(set_reasons)
        # conjunto incompatível / caso removido: não é comparação conclusiva
        regression = True

    shared_ids = sorted(set(b_cases) & set(c_cases))
    for case_id in shared_ids:
        b_case = b_cases[case_id]
        c_case = c_cases[case_id]
        critical = bool(b_case.get("critical") or c_case.get("critical"))
        baseline_ok = bool(b_case.get("ok"))
        candidate_ok = bool(c_case.get("ok"))
        dim_regs = _dimension_regressions(b_case, c_case)
        pass_to_fail = baseline_ok and not candidate_ok
        regressed = pass_to_fail or bool(dim_regs)
        gate: dict[str, Any] = {
            "case_id": case_id,
            "critical": critical,
            "baseline_ok": baseline_ok,
            "candidate_ok": candidate_ok,
            "regressed": regressed,
            "dimension_regressions": dim_regs,
            "tolerated": False,
        }
        if regressed:
            if critical:
                critical_regression = True
                regression = True
                if pass_to_fail:
                    reasons.append(f"critical_case_regressed:{case_id}")
                for dim in dim_regs:
                    reasons.append(f"critical_dimension_regressed:{case_id}:{dim}")
            else:
                tol = tol_idx.get(case_id)
                # tolerância não crítica: explícita + justificada + registrada
                if tol:
                    gate["tolerated"] = True
                    gate["tolerance"] = tol
                    tolerances_applied.append(
                        {**tol, "dimension_regressions": dim_regs}
                    )
                else:
                    regression = True
                    if pass_to_fail:
                        reasons.append(f"case_regressed:{case_id}")
                    for dim in dim_regs:
                        reasons.append(f"dimension_regressed:{case_id}:{dim}")
        case_gates.append(gate)

    # casos só no baseline (já em missing) — marcar gate explícito
    for case_id in missing:
        b_case = b_cases[case_id]
        case_gates.append(
            {
                "case_id": case_id,
                "critical": bool(b_case.get("critical")),
                "baseline_ok": bool(b_case.get("ok")),
                "candidate_ok": None,
                "regressed": True,
                "missing_in_candidate": True,
                "dimension_regressions": [],
                "tolerated": False,
            }
        )
    for case_id in extra:
        c_case = c_cases[case_id]
        case_gates.append(
            {
                "case_id": case_id,
                "critical": bool(c_case.get("critical")),
                "baseline_ok": None,
                "candidate_ok": bool(c_case.get("ok")),
                "regressed": True,
                "extra_in_candidate": True,
                "dimension_regressions": [],
                "tolerated": False,
            }
        )

    distinct, ws_info = _workspaces_distinct(baseline, candidate)
    if (baseline.get("workspace") or candidate.get("workspace")) and not distinct:
        regression = True
        reasons.append("workspaces_not_distinct")

    metrics = _metric_block(b, c)
    # promoção: benefício real (sem latência), conjuntos comparáveis, sem regressão
    improved = (
        comparable
        and (not regression)
        and (not critical_regression)
        and _improved(metrics)
    )

    reject = regression or critical_regression or (not comparable)
    decision = "reject" if reject else "accept"
    reserved = list(reserved_cases if reserved_cases is not None else RESERVED_CASES)
    return {
        "regression": regression,
        "critical_regression": critical_regression,
        "comparable": comparable,
        "improved": improved,
        "reasons": reasons,
        "baseline": b,
        "candidate": c,
        "case_gates": case_gates,
        "metrics": metrics,
        "workspaces": ws_info,
        "tolerances_applied": tolerances_applied,
        "reserved_cases": reserved,
        "reported_only_metrics": list(_REPORTED_ONLY),
        "decision": decision,
    }


def apply_reserved_gate(
    comparison: dict[str, Any],
    reserved_baseline: dict[str, Any],
    reserved_candidate: dict[str, Any],
    *,
    tolerances: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Veta promoção se o hold-out regredir — sem misturar hold-out na orientação.

    A comparação de desenvolvimento (`comparison`) permanece a fonte de
    `metrics` / `improved` / `case_gates`. Casos reservados entram só como
    gate de promoção: regressão crítica (ou não crítica sem tolerância
    explícita) e conjuntos incomparáveis forçam `decision=reject`.
    """
    holdout = compare_evals(
        reserved_baseline,
        reserved_candidate,
        tolerances=tolerances,
        reserved_cases=(),
    )
    # Paths reserved/* são distintos dos evals de desenvolvimento; o distinct
    # relevante já foi medido no conjunto de orientação.
    raw_reasons = [
        r
        for r in (holdout.get("reasons") or [])
        if r != "workspaces_not_distinct"
    ]
    critical = bool(holdout.get("critical_regression"))
    comparable = bool(holdout.get("comparable", True))
    untolerated = [
        g
        for g in (holdout.get("case_gates") or [])
        if g.get("regressed") and not g.get("tolerated")
    ]
    blocks = critical or (not comparable) or bool(untolerated) or bool(raw_reasons)
    prefixed = [f"reserved:{r}" for r in raw_reasons]

    out = dict(comparison)
    out["reserved_case_gates"] = list(holdout.get("case_gates") or [])
    reserved_tols = [
        {**t, "scope": "reserved"} for t in (holdout.get("tolerances_applied") or [])
    ]
    out["reserved_comparison"] = {
        "regression": blocks,
        "critical_regression": critical,
        "comparable": comparable,
        "reasons": prefixed,
        "tolerances_applied": reserved_tols,
        "decision": "reject" if blocks else "accept",
    }
    if reserved_tols:
        out["tolerances_applied"] = list(comparison.get("tolerances_applied") or []) + (
            reserved_tols
        )

    if blocks:
        out["regression"] = True
        if critical:
            out["critical_regression"] = True
        merged = list(comparison.get("reasons") or [])
        for r in prefixed:
            if r not in merged:
                merged.append(r)
        out["reasons"] = merged
        out["improved"] = False
        out["decision"] = "reject"
    return out
