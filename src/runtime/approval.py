"""Aprovação humana auditável, vinculada à evidência de uma run.

O registro identifica quem decidiu sobre exatamente qual Canonical Spec,
verify-report e `result_commit`. HMAC reusa `seal_hmac` do 19 (fail-closed).
Persistência: `validations/approval.json` por write-temp + `os.replace` (18).

Promote não aplica código (isso é o ticket 14): só marca a run como promovida
quando a aprovação vigente ainda bate com os hashes atuais.
"""
from __future__ import annotations

import hmac
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.runtime.atomic_io import atomic_write_json, read_json, sha256_of
from src.runtime.integrity import (
    MissingIntegrityKey,
    current_kid,
    lookup_integrity_key,
    seal_hmac,
)
from src.runtime.run_context import validate_run_id

APPROVAL_FILENAME = "approval.json"
PROMOTION_FILENAME = "promotion.json"
DECISIONS = frozenset({"requested", "approved", "rejected"})
_UNSIGNED = frozenset({"hmac"})


class ApprovalError(RuntimeError):
    """Falha fail-closed do fluxo de aprovação."""


class ApprovalMissing(ApprovalError):
    """Não há registro (ou pedido pendente) nesta run."""


class ApprovalExpired(ApprovalError):
    """Spec, verify-report ou result_commit mudaram depois da decisão."""


class ApprovalTampered(ApprovalError):
    """HMAC do registro não confere — arquivo adulterado."""


class ApprovalReuse(ApprovalError):
    """Registro pertence a outra run_id."""


class ApprovalRejected(ApprovalError):
    """A decisão vigente é uma rejeição persistida."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_approval_id() -> str:
    return f"apr-{uuid4().hex[:12]}"


def approval_path(run_dir: Path) -> Path:
    return Path(run_dir) / "validations" / APPROVAL_FILENAME


def promotion_path(run_dir: Path) -> Path:
    return Path(run_dir) / "validations" / PROMOTION_FILENAME


def _seal(payload: dict[str, Any]) -> dict[str, Any]:
    """Assina o objeto (fail-closed sem chave)."""
    kid = str(payload.get("kid") or current_kid())
    payload["kid"] = kid
    body = {k: v for k, v in payload.items() if k not in _UNSIGNED}
    try:
        key = lookup_integrity_key(kid)
    except MissingIntegrityKey as exc:
        raise ApprovalError(str(exc)) from exc
    payload["hmac"] = seal_hmac(body, key=key)
    return payload


def _verify_seal(payload: dict[str, Any], *, label: str) -> None:
    stored = payload.get("hmac")
    if not stored:
        raise ApprovalTampered(f"{label}: hmac ausente")
    kid = str(payload.get("kid") or current_kid())
    try:
        key = lookup_integrity_key(kid)
    except MissingIntegrityKey as exc:
        raise ApprovalTampered(str(exc)) from exc
    body = {k: v for k, v in payload.items() if k not in _UNSIGNED}
    expected = seal_hmac(body, key=key)
    if not hmac.compare_digest(str(stored), expected):
        raise ApprovalTampered(f"{label}: hmac inválido")


def _rel_to_run(run_dir: Path, path: Path) -> str:
    run_dir = Path(run_dir).resolve()
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(run_dir).as_posix()
    except ValueError:
        return str(resolved)


def _resolve_bound_path(run_dir: Path, stored: str) -> Path:
    candidate = Path(stored)
    if candidate.is_absolute():
        return candidate
    return Path(run_dir) / stored


def extract_result_commit(
    *,
    report: dict[str, Any] | None = None,
    execution: dict[str, Any] | None = None,
) -> str:
    if execution and execution.get("result_commit"):
        return str(execution["result_commit"]).strip()
    report = report or {}
    nested = report.get("execution") if isinstance(report.get("execution"), dict) else {}
    if nested.get("result_commit"):
        return str(nested["result_commit"]).strip()
    hashes = report.get("verify") if isinstance(report.get("verify"), dict) else {}
    evidence = hashes.get("evidence_hashes") if isinstance(hashes, dict) else {}
    if isinstance(evidence, dict) and evidence.get("result_commit"):
        return str(evidence["result_commit"]).strip()
    return ""


def extract_diff_sha256(report: dict[str, Any] | None) -> str | None:
    if not isinstance(report, dict):
        return None
    verify = report.get("verify") if isinstance(report.get("verify"), dict) else {}
    evidence = verify.get("evidence_hashes") if isinstance(verify, dict) else {}
    if isinstance(evidence, dict) and evidence.get("diff_sha256"):
        return str(evidence["diff_sha256"])
    return None


def snapshot_binding(
    run_dir: Path,
    *,
    spec_path: Path,
    verify_report_path: Path,
    result_path: Path | None = None,
) -> dict[str, Any]:
    spec_path = Path(spec_path)
    verify_report_path = Path(verify_report_path)
    if not spec_path.is_file():
        raise ApprovalError(f"Canonical Spec ausente: {spec_path}")
    if not verify_report_path.is_file():
        raise ApprovalError(f"verify-report ausente: {verify_report_path}")

    report = read_json(verify_report_path)
    if not isinstance(report, dict):
        raise ApprovalError(f"verify-report ilegível: {verify_report_path}")

    execution: dict[str, Any] | None = None
    if result_path is not None:
        result_path = Path(result_path)
        if not result_path.is_file():
            raise ApprovalError(f"execution result ausente: {result_path}")
        loaded = read_json(result_path)
        if not isinstance(loaded, dict):
            raise ApprovalError(f"execution result ilegível: {result_path}")
        execution = loaded

    commit = extract_result_commit(report=report, execution=execution)
    if not commit:
        raise ApprovalError("result_commit ausente no result/verify-report")

    binding: dict[str, Any] = {
        "canonical_spec_sha256": sha256_of(spec_path),
        "verify_report_sha256": sha256_of(verify_report_path),
        "result_commit": commit,
        "diff_sha256": extract_diff_sha256(report),
        "paths": {
            "canonical_spec": _rel_to_run(run_dir, spec_path),
            "verify_report": _rel_to_run(run_dir, verify_report_path),
            "execution": _rel_to_run(run_dir, result_path) if result_path else None,
        },
    }
    return binding


def current_binding(run_dir: Path, bound: dict[str, Any]) -> dict[str, Any]:
    """Recalcula o binding a partir dos arquivos apontados pelo registro."""
    paths = bound.get("paths") if isinstance(bound.get("paths"), dict) else {}
    spec = paths.get("canonical_spec")
    report = paths.get("verify_report")
    execution = paths.get("execution")
    if not spec or not report:
        raise ApprovalExpired("registro sem caminhos de spec/verify-report")
    return snapshot_binding(
        run_dir,
        spec_path=_resolve_bound_path(run_dir, str(spec)),
        verify_report_path=_resolve_bound_path(run_dir, str(report)),
        result_path=(
            _resolve_bound_path(run_dir, str(execution)) if execution else None
        ),
    )


def binding_matches(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    mismatches: list[str] = []
    for key in ("canonical_spec_sha256", "verify_report_sha256", "result_commit"):
        if expected.get(key) != actual.get(key):
            mismatches.append(key)
    exp_diff = expected.get("diff_sha256")
    if exp_diff and exp_diff != actual.get("diff_sha256"):
        mismatches.append("diff_sha256")
    return mismatches


def empty_ledger(run_id: str) -> dict[str, Any]:
    return {"run_id": run_id, "history": []}


def load_ledger(run_dir: Path, *, run_id: str) -> dict[str, Any]:
    path = approval_path(run_dir)
    data = read_json(path)
    if data is None:
        return empty_ledger(run_id)
    if not isinstance(data, dict):
        raise ApprovalTampered("approval.json não é um objeto JSON")
    _verify_seal(data, label="ledger de aprovação")
    stored_run = str(data.get("run_id") or "")
    if stored_run and stored_run != run_id:
        raise ApprovalReuse(
            f"aprovação da run {stored_run!r} não pode ser reutilizada em {run_id!r}"
        )
    for i, entry in enumerate(data.get("history") or []):
        if not isinstance(entry, dict):
            raise ApprovalTampered(f"history[{i}] não é objeto")
        _verify_seal(entry, label=f"history[{i}]")
        entry_run = str(entry.get("run_id") or "")
        if entry_run and entry_run != run_id:
            raise ApprovalReuse(
                f"entrada {entry.get('id')!r} pertence à run {entry_run!r}"
            )
    return data


def save_ledger(run_dir: Path, ledger: dict[str, Any]) -> dict[str, Any]:
    sealed_history: list[dict[str, Any]] = []
    for entry in ledger.get("history") or []:
        if not isinstance(entry, dict):
            continue
        sealed_history.append(_seal(dict(entry)))
    document = {
        "run_id": ledger["run_id"],
        "history": sealed_history,
    }
    _seal(document)
    path = approval_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, document)
    return document


def latest_entry(ledger: dict[str, Any]) -> dict[str, Any] | None:
    history = ledger.get("history") or []
    if not history:
        return None
    last = history[-1]
    return last if isinstance(last, dict) else None


def append_decision(
    run_dir: Path,
    *,
    run_id: str,
    decision: str,
    actor: str,
    justification: str,
    origin: str,
    binding: dict[str, Any],
) -> dict[str, Any]:
    if decision not in DECISIONS:
        raise ApprovalError(f"decisão inválida: {decision!r}")
    actor = (actor or "").strip()
    origin = (origin or "").strip()
    justification = (justification or "").strip()
    if decision in {"approved", "rejected"}:
        if not actor:
            raise ApprovalError("ator é obrigatório para approve/reject")
        if not justification:
            raise ApprovalError("justificativa é obrigatória para approve/reject")
        if not origin:
            raise ApprovalError("origem é obrigatória para approve/reject")
    run_id = validate_run_id(run_id)
    ledger = load_ledger(run_dir, run_id=run_id)
    entry = {
        "id": new_approval_id(),
        "run_id": run_id,
        "decision": decision,
        "actor": actor or None,
        "timestamp": _now(),
        "justification": justification or None,
        "origin": origin or "cli",
        "binding": binding,
    }
    history = list(ledger.get("history") or [])
    history.append(entry)
    ledger["run_id"] = run_id
    ledger["history"] = history
    saved = save_ledger(run_dir, ledger)
    return (saved.get("history") or [])[-1]


def default_spec_path(run_dir: Path) -> Path:
    return Path(run_dir) / "artifacts" / "canonical-spec.yaml"


def default_verify_report_path(run_dir: Path) -> Path:
    return Path(run_dir) / "validations" / "verify-report.json"


def default_result_path(run_dir: Path) -> Path | None:
    for candidate in (
        Path(run_dir) / "artifacts" / "execution.json",
        Path(run_dir) / "validations" / "execution.json",
        Path(run_dir) / "execution.json",
    ):
        if candidate.is_file():
            return candidate
    return None


def request_approval(
    run_dir: Path,
    *,
    run_id: str,
    spec_path: Path | None = None,
    verify_report_path: Path | None = None,
    result_path: Path | None = None,
    actor: str = "",
    justification: str = "",
    origin: str = "cli",
) -> dict[str, Any]:
    run_dir = Path(run_dir)
    spec = spec_path or default_spec_path(run_dir)
    report = verify_report_path or default_verify_report_path(run_dir)
    result = result_path if result_path is not None else default_result_path(run_dir)
    binding = snapshot_binding(
        run_dir, spec_path=spec, verify_report_path=report, result_path=result
    )
    return append_decision(
        run_dir,
        run_id=run_id,
        decision="requested",
        actor=actor,
        justification=justification or "pedido de aprovação humana",
        origin=origin or "cli",
        binding=binding,
    )


def _require_pending(ledger: dict[str, Any]) -> dict[str, Any]:
    latest = latest_entry(ledger)
    if latest is None:
        raise ApprovalMissing("nenhum pedido de aprovação nesta run")
    if latest.get("decision") != "requested":
        raise ApprovalError(
            f"não há pedido pendente (último: {latest.get('decision')!r})"
        )
    return latest


def decide(
    run_dir: Path,
    *,
    run_id: str,
    decision: str,
    actor: str,
    justification: str,
    origin: str = "cli",
) -> dict[str, Any]:
    if decision not in {"approved", "rejected"}:
        raise ApprovalError(f"decisão inválida: {decision!r}")
    run_dir = Path(run_dir)
    ledger = load_ledger(run_dir, run_id=run_id)
    pending = _require_pending(ledger)
    bound = pending.get("binding") if isinstance(pending.get("binding"), dict) else {}
    actual = current_binding(run_dir, bound)
    mismatches = binding_matches(bound, actual)
    if mismatches:
        raise ApprovalExpired(
            "pedido expirou — evidência mudou: " + ", ".join(mismatches)
        )
    return append_decision(
        run_dir,
        run_id=run_id,
        decision=decision,
        actor=actor,
        justification=justification,
        origin=origin,
        binding=bound,
    )


def approve(
    run_dir: Path,
    *,
    run_id: str,
    actor: str,
    justification: str,
    origin: str = "cli",
    reject: bool = False,
) -> dict[str, Any]:
    return decide(
        run_dir,
        run_id=run_id,
        decision="rejected" if reject else "approved",
        actor=actor,
        justification=justification,
        origin=origin,
    )


def assert_promotable(run_dir: Path, *, run_id: str) -> dict[str, Any]:
    """Devolve a entrada aprovada vigente ou falha fechado."""
    run_dir = Path(run_dir)
    path = approval_path(run_dir)
    if not path.is_file():
        raise ApprovalMissing("run sem registro de aprovação")
    ledger = load_ledger(run_dir, run_id=run_id)
    latest = latest_entry(ledger)
    if latest is None:
        raise ApprovalMissing("histórico de aprovação vazio")
    decision = latest.get("decision")
    if decision == "rejected":
        raise ApprovalRejected(
            f"run rejeitada por {latest.get('actor')} em {latest.get('timestamp')}"
        )
    if decision != "approved":
        raise ApprovalMissing(
            f"promover exige aprovação vinculada (último: {decision!r})"
        )
    bound = latest.get("binding") if isinstance(latest.get("binding"), dict) else {}
    actual = current_binding(run_dir, bound)
    mismatches = binding_matches(bound, actual)
    if mismatches:
        raise ApprovalExpired(
            "aprovação expirou — evidência mudou: " + ", ".join(mismatches)
        )
    if str(latest.get("run_id") or "") != run_id:
        raise ApprovalReuse(
            f"aprovação da run {latest.get('run_id')!r} não vale para {run_id!r}"
        )
    return latest


def promote(run_dir: Path, *, run_id: str) -> dict[str, Any]:
    run_id = validate_run_id(run_id)
    approved = assert_promotable(run_dir, run_id=run_id)
    record = {
        "run_id": run_id,
        "promoted_at": _now(),
        "approval_id": approved.get("id"),
        "actor": approved.get("actor"),
        "binding": approved.get("binding"),
        "origin": "promote",
    }
    _seal(record)
    dest = promotion_path(run_dir)
    dest.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(dest, record)
    return record


def show_history(run_dir: Path, *, run_id: str) -> dict[str, Any]:
    run_dir = Path(run_dir)
    if not approval_path(run_dir).is_file():
        return empty_ledger(run_id)
    return load_ledger(run_dir, run_id=run_id)
