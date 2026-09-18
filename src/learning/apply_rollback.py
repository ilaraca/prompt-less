"""Apply de propostas em config versionada com snapshot e rollback.

Fluxo: gate de risco → snapshot de bytes → apply `change.key/value` →
re-eval → regressão restaura bytes e marca `rejected`.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from src.learning.accept import knowledge_dir, load_history, save_history
from src.learning.evals import DEFAULT_CASES, compare_evals, run_eval_suite
from src.learning.workspaces import snapshot_sha256, workspace_commit
from src.runtime.atomic_io import (
    atomic_copy,
    atomic_write_json,
    atomic_write_text,
    read_json,
    resolve_within,
    sha256_of,
)
from src.runtime.approval import ApprovalError, assert_promotable
from src.runtime.config_load import OVERLAY_NAME, set_dotted

LOW_RISKS = frozenset({"low"})
MISSING_MARKER = ".missing"


class ApplyGateError(RuntimeError):
    """Risco medium+ sem aprovação promotable, ou apply inválido."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def snapshots_dir(root: Path) -> Path:
    d = knowledge_dir(root) / "snapshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def resolve_config_target(root: Path, key: str) -> tuple[Path, str]:
    """
    Mapeia `change.key` para arquivo versionado sob `config/`.

    Se o primeiro segmento corresponde a um YAML existente (ex.:
    `permission_profiles.enforce_deny` → `permission_profiles.yaml`),
    aplica o restante da chave nesse arquivo. Caso contrário grava no
    overlay versionado `proposal-overlay.yaml`.
    """
    root = Path(root)
    config = resolve_within(root, root / "config")
    parts = [p for p in str(key).split(".") if p]
    if not parts:
        raise ApplyGateError("change.key vazio")
    stem = parts[0]
    named = config / f"{stem}.yaml"
    if named.is_file() and stem != "proposal-overlay":
        rest = ".".join(parts[1:]) if len(parts) > 1 else stem
        return named, rest
    return config / OVERLAY_NAME, key


def _rel_under_root(root: Path, path: Path) -> str:
    return path.resolve().relative_to(Path(root).resolve()).as_posix()


@dataclass
class SnapshotRecord:
    snapshot_id: str
    path: Path
    files: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "path": str(self.path),
            "files": list(self.files),
        }


def create_snapshot(
    root: Path,
    targets: list[Path],
    *,
    proposal_ids: list[str] | None = None,
    snapshot_id: str | None = None,
) -> SnapshotRecord:
    """Copia bytes pré-apply para `state/knowledge/snapshots/<id>/`."""
    root = Path(root)
    sid = snapshot_id or f"snap-{uuid4().hex[:12]}"
    dest = resolve_within(snapshots_dir(root), snapshots_dir(root) / sid)
    files_root = dest / "files"
    files_root.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for target in targets:
        target = Path(target)
        rel = _rel_under_root(root, target)
        if rel in seen:
            continue
        seen.add(rel)
        stored = files_root / rel
        stored.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file():
            atomic_copy(target, stored)
            entries.append(
                {
                    "rel": rel,
                    "existed": True,
                    "sha256": sha256_of(target),
                }
            )
        else:
            atomic_write_text(stored.with_suffix(stored.suffix + MISSING_MARKER), "")
            entries.append({"rel": rel, "existed": False, "sha256": None})

    manifest = {
        "snapshot_id": sid,
        "created_at": _now(),
        "proposal_ids": list(proposal_ids or []),
        "files": entries,
    }
    atomic_write_json(dest / "manifest.json", manifest)
    return SnapshotRecord(snapshot_id=sid, path=dest, files=entries)


def restore_snapshot(root: Path, snapshot: SnapshotRecord | Path) -> list[str]:
    """Restaura bytes exactos do snapshot; remove arquivos que não existiam."""
    root = Path(root)
    snap_path = snapshot.path if isinstance(snapshot, SnapshotRecord) else Path(snapshot)
    manifest_path = snap_path / "manifest.json"
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict):
        raise ApplyGateError(f"snapshot inválido: {manifest_path}")
    restored: list[str] = []
    for entry in manifest.get("files") or []:
        rel = str(entry.get("rel") or "")
        if not rel:
            continue
        target = resolve_within(root, root / rel)
        if entry.get("existed"):
            src = snap_path / "files" / rel
            if not src.is_file():
                raise ApplyGateError(f"byte ausente no snapshot: {rel}")
            atomic_copy(src, target)
        else:
            if target.is_file():
                target.unlink()
            # limpa dirs vazios sob config/
            parent = target.parent
            config_root = (root / "config").resolve()
            while parent != config_root and config_root in parent.resolve().parents:
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
        restored.append(rel)
    return restored


def apply_change_to_config(root: Path, key: str, value: Any) -> Path:
    """Aplica um `change.key/value` em arquivo de config versionado."""
    root = Path(root)
    path, local_key = resolve_config_target(root, key)
    resolve_within(root / "config", path)
    raw: dict[str, Any] = {}
    if path.is_file():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            raw = dict(loaded)
    set_dotted(raw, local_key, value)
    atomic_write_text(
        path,
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=True),
    )
    return path


def collect_targets(root: Path, proposals: list[dict[str, Any]]) -> list[Path]:
    targets: list[Path] = []
    for proposal in proposals:
        change = proposal.get("change") or {}
        key = change.get("key")
        if not key:
            continue
        path, _ = resolve_config_target(root, str(key))
        targets.append(path)
    return targets


def risk_requires_approval(proposals: list[dict[str, Any]]) -> bool:
    return any((p.get("risk") or "low") not in LOW_RISKS for p in proposals)


def _identity_payload(root: Path, *, role: str) -> dict[str, Any]:
    snap = snapshot_sha256(root / "config")
    return {
        "role": role,
        "path": str(root),
        "source_commit": "production",
        "workspace_commit": workspace_commit(origin="production", snapshot=snap),
        "snapshot_sha256": snap,
    }


def apply_proposals_with_rollback(
    proposals: list[dict[str, Any]],
    *,
    root: Path,
    eval_root: Path | None = None,
    cases: list[str] | tuple[str, ...] | None = None,
    run_dir: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """
    Aplica propostas em `root/config`, re-avalia e faz rollback se regressão.

    Risco `medium+` exige `assert_promotable` em `run_dir`/`run_id`.
    """
    root = Path(root)
    if not proposals:
        return {
            "status": "skipped",
            "reason": ["no_proposals"],
            "applied_ids": [],
            "rejected": [],
            "accepted": [],
        }

    if risk_requires_approval(proposals):
        if run_dir is None or not run_id:
            raise ApplyGateError(
                "risco medium+ exige aprovação via src.approval "
                "(informe --run-dir e --run-id com promote/assert_promotable)"
            )
        try:
            approval = assert_promotable(Path(run_dir), run_id=str(run_id))
        except ApprovalError as exc:
            raise ApplyGateError(str(exc)) from exc
    else:
        approval = None

    targets = collect_targets(root, proposals)
    if not targets:
        return {
            "status": "skipped",
            "reason": ["no_applyable_change"],
            "applied_ids": [],
            "rejected": [],
            "accepted": [],
        }

    suite_cases = cases if cases is not None else DEFAULT_CASES
    out = Path(eval_root) if eval_root is not None else knowledge_dir(root) / "evals" / "apply"
    out.mkdir(parents=True, exist_ok=True)

    baseline_id = _identity_payload(root, role="baseline")
    baseline = run_eval_suite(
        output_root=out / "baseline",
        cases=suite_cases,
        config_root=root,
        workspace=baseline_id,
        run_id_prefix="apply-b",
    )

    proposal_ids = [str(p.get("id") or "") for p in proposals if p.get("id")]
    snapshot = create_snapshot(root, targets, proposal_ids=proposal_ids)

    applied_ids: list[str] = []
    touched: list[str] = []
    try:
        for proposal in proposals:
            change = proposal.get("change") or {}
            key = change.get("key")
            if not key:
                continue
            path = apply_change_to_config(root, str(key), change.get("value"))
            applied_ids.append(str(proposal["id"]))
            touched.append(_rel_under_root(root, path))
            proposal["status"] = "applied"

        candidate_id = _identity_payload(root, role="candidate")
        candidate = run_eval_suite(
            output_root=out / "candidate",
            cases=suite_cases,
            config_root=root,
            workspace=candidate_id,
            run_id_prefix="apply-c",
        )
        comparison = compare_evals(baseline, candidate)
        reject = (
            comparison.get("decision") == "reject"
            or comparison.get("regression")
            or comparison.get("critical_regression")
        )

        history = load_history(root)
        now = _now()
        if reject:
            restore_snapshot(root, snapshot)
            rejected_items = []
            for proposal in proposals:
                item = {
                    **proposal,
                    "status": "rejected",
                    "reason": list(comparison.get("reasons") or ["eval_regression"]),
                    "decided_at": now,
                    "snapshot_id": snapshot.snapshot_id,
                    "metrics": comparison.get("metrics") or {},
                    "rolled_back": True,
                }
                proposal["status"] = "rejected"
                rejected_items.append(item)
                history["rejected"].append(item)
            save_history(root, history)
            return {
                "status": "rejected",
                "applied_ids": [],
                "accepted": [],
                "rejected": rejected_items,
                "snapshot": snapshot.to_dict(),
                "restored": True,
                "comparison": comparison,
                "approval_id": (approval or {}).get("id"),
                "touched_files": touched,
            }

        accepted_items = []
        for proposal in proposals:
            if str(proposal.get("id") or "") not in applied_ids:
                continue
            item = {
                **proposal,
                "status": "accepted",
                "reason": [],
                "decided_at": now,
                "snapshot_id": snapshot.snapshot_id,
                "metrics": comparison.get("metrics") or {},
                "applied_to_production": True,
            }
            proposal["status"] = "accepted"
            accepted_items.append(item)
            history["accepted"].append(item)
        save_history(root, history)
        return {
            "status": "accepted",
            "applied_ids": applied_ids,
            "accepted": accepted_items,
            "rejected": [],
            "snapshot": snapshot.to_dict(),
            "restored": False,
            "comparison": comparison,
            "approval_id": (approval or {}).get("id"),
            "touched_files": touched,
        }
    except BaseException:
        try:
            restore_snapshot(root, snapshot)
        except OSError:
            pass
        raise


def cleanup_snapshot(snapshot: SnapshotRecord | Path) -> None:
    """Remove diretório de snapshot (uso em testes)."""
    path = snapshot.path if isinstance(snapshot, SnapshotRecord) else Path(snapshot)
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
