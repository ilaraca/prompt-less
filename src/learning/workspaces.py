"""Workspaces isolados para eval de baseline vs candidato.

A proposta é materializada só no candidato. O baseline permanece o snapshot
do commit de origem. Apply em produção é o ticket 14 — este módulo não toca
`source_root` além de ler `config/`.
"""
from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.runtime.atomic_io import (
    UnsafePath,
    atomic_copy,
    atomic_write_json,
    atomic_write_text,
    read_json,
    resolve_within,
    sha256_of,
)

OVERLAY_NAME = "proposal-overlay.yaml"
JOURNAL_NAME = "apply-journal.json"
LOCK_NAME = ".apply-lock"

# Política, verificador e dados de eval não podem ser alterados pelo candidato.
PROTECTED_CONFIG_STEMS = frozenset(
    {
        "failure-patterns",
        "playbook",
        "permission_profiles",
    }
)
PROTECTED_CHANGE_PREFIXES = (
    "failure-patterns.",
    "failure_patterns.",
    "playbook.",
    "playbooks.",
    "permission_profiles.",
    "evals.",
    "learning.evals.",
)


class WorkspaceCollision(RuntimeError):
    """O diretório do workspace já existe e não foi pedido resume."""


class ProtectedSurfaceError(RuntimeError):
    """Candidato tentou mutar política, verificador ou dados de avaliação."""


def is_protected_change(key: str) -> bool:
    """True se a chave do playbook tocasse superfície protegida do avaliador."""
    text = str(key or "").strip().lower().replace("_", "-")
    if not text:
        return False
    stem = text.split(".", 1)[0]
    if stem in {s.replace("_", "-") for s in PROTECTED_CONFIG_STEMS}:
        return True
    lowered = str(key or "").strip().lower()
    return any(lowered.startswith(p) for p in PROTECTED_CHANGE_PREFIXES)


def source_commit(root: Path) -> str:
    """HEAD do repositório de origem; `unknown` se não houver git."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "unknown"
    if proc.returncode != 0:
        return "unknown"
    return (proc.stdout or "").strip() or "unknown"


def snapshot_sha256(directory: Path) -> str:
    """Hash estável do conteúdo de um diretório (arquivos regulares)."""
    digest = hashlib.sha256()
    directory = Path(directory)
    if not directory.exists():
        return digest.hexdigest()
    files = sorted(
        p for p in directory.rglob("*") if p.is_file() and p.name != LOCK_NAME
    )
    for path in files:
        rel = path.relative_to(directory).as_posix().encode("utf-8")
        digest.update(rel)
        digest.update(b"\0")
        digest.update(sha256_of(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def workspace_commit(*, origin: str, snapshot: str, diff: str = "") -> str:
    """Identidade do workspace: distinta do HEAD de origem após um apply."""
    payload = f"{origin}\n{snapshot}\n{diff}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:40]


def _set_dotted(data: dict[str, Any], key: str, value: Any) -> None:
    parts = [p for p in str(key).split(".") if p]
    if not parts:
        return
    cur: dict[str, Any] = data
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _copy_config(source_root: Path, dest: Path) -> None:
    src = Path(source_root) / "config"
    target = dest / "config"
    target.mkdir(parents=True, exist_ok=True)
    if not src.is_dir():
        return
    for path in sorted(p for p in src.rglob("*") if p.is_file()):
        rel = path.relative_to(src)
        atomic_copy(path, target / rel)


def _unified_diff(baseline: Path, candidate: Path) -> str:
    import difflib

    chunks: list[str] = []
    b_root = baseline / "config"
    c_root = candidate / "config"
    names: set[str] = set()
    if b_root.exists():
        names.update(p.relative_to(b_root).as_posix() for p in b_root.rglob("*") if p.is_file())
    if c_root.exists():
        names.update(p.relative_to(c_root).as_posix() for p in c_root.rglob("*") if p.is_file())
    for name in sorted(names):
        b_path = b_root / name
        c_path = c_root / name
        b_lines = b_path.read_text(encoding="utf-8").splitlines(True) if b_path.is_file() else []
        c_lines = c_path.read_text(encoding="utf-8").splitlines(True) if c_path.is_file() else []
        if b_lines == c_lines:
            continue
        diff = difflib.unified_diff(
            b_lines,
            c_lines,
            fromfile=f"baseline/config/{name}",
            tofile=f"candidate/config/{name}",
        )
        chunks.append("".join(diff))
    return "".join(chunks)


@dataclass
class EvalWorkspace:
    role: str
    path: Path
    source_commit: str
    workspace_commit: str
    snapshot_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "path": str(self.path),
            "source_commit": self.source_commit,
            "workspace_commit": self.workspace_commit,
            "snapshot_sha256": self.snapshot_sha256,
        }

    def refresh(self, *, diff: str = "") -> EvalWorkspace:
        snap = snapshot_sha256(self.path)
        self.snapshot_sha256 = snap
        self.workspace_commit = workspace_commit(
            origin=self.source_commit, snapshot=snap, diff=diff
        )
        return self


@dataclass
class WorkspacePair:
    baseline: EvalWorkspace
    candidate: EvalWorkspace
    source_commit: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_commit": self.source_commit,
            "baseline": self.baseline.to_dict(),
            "candidate": self.candidate.to_dict(),
            "distinct": (
                self.baseline.path != self.candidate.path
                and self.baseline.workspace_commit != self.candidate.workspace_commit
            ),
        }


@dataclass
class ApplyResult:
    status: str
    applied_ids: list[str] = field(default_factory=list)
    diff: str = ""
    baseline: dict[str, Any] = field(default_factory=dict)
    candidate: dict[str, Any] = field(default_factory=dict)
    reason: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "applied_ids": list(self.applied_ids),
            "diff": self.diff,
            "baseline": dict(self.baseline),
            "candidate": dict(self.candidate),
            "reason": list(self.reason),
        }


def _identity(role: str, path: Path, origin: str, *, diff: str = "") -> EvalWorkspace:
    snap = snapshot_sha256(path)
    return EvalWorkspace(
        role=role,
        path=path,
        source_commit=origin,
        workspace_commit=workspace_commit(origin=origin, snapshot=snap, diff=diff),
        snapshot_sha256=snap,
    )


def materialize_eval_workspaces(
    *,
    source_root: Path,
    eval_root: Path,
    resume: bool = False,
) -> WorkspacePair:
    """Cria baseline e candidate sob `eval_root/workspaces/`, cópia só de config/."""
    source_root = Path(source_root)
    eval_root = Path(eval_root)
    eval_root.mkdir(parents=True, exist_ok=True)
    base = resolve_within(eval_root, eval_root / "workspaces")
    baseline_path = resolve_within(eval_root, base / "baseline")
    candidate_path = resolve_within(eval_root, base / "candidate")
    if baseline_path == candidate_path:
        raise UnsafePath("baseline e candidate não podem coincidir")

    origin = source_commit(source_root)
    for path in (baseline_path, candidate_path):
        try:
            path.mkdir(parents=True)
        except FileExistsError:
            if not resume:
                raise WorkspaceCollision(
                    f"workspace já existe em {path}; use resume=True"
                ) from None
        _copy_config(source_root, path)

    pair = WorkspacePair(
        baseline=_identity("baseline", baseline_path, origin),
        candidate=_identity("candidate", candidate_path, origin),
        source_commit=origin,
    )
    atomic_write_json(baseline_path / "identity.json", pair.baseline.to_dict())
    atomic_write_json(candidate_path / "identity.json", pair.candidate.to_dict())
    return pair


def apply_journal(workspace: Path) -> dict[str, Any] | None:
    data = read_json(Path(workspace) / JOURNAL_NAME)
    return data if isinstance(data, dict) else None


def is_fully_applied(workspace: Path) -> bool:
    journal = apply_journal(workspace)
    return journal is not None and journal.get("status") == "applied"


def apply_proposals_to_candidate(
    proposals: list[dict[str, Any]],
    pair: WorkspacePair,
) -> ApplyResult:
    """Aplica as propostas só no workspace candidato (overlay atômico)."""
    candidate = pair.candidate.path
    baseline = pair.baseline.path
    resolve_within(candidate.parent.parent, candidate)
    if candidate == baseline:
        return ApplyResult(
            status="failed",
            reason=["baseline_and_candidate_same_path"],
            baseline=pair.baseline.to_dict(),
            candidate=pair.candidate.to_dict(),
        )

    if not proposals:
        pair.candidate.refresh()
        return ApplyResult(
            status="skipped",
            reason=["no_proposals"],
            baseline=pair.baseline.to_dict(),
            candidate=pair.candidate.to_dict(),
        )

    lock = candidate / LOCK_NAME
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise WorkspaceCollision(f"apply concorrente em {candidate}") from exc

    try:
        atomic_write_json(
            candidate / JOURNAL_NAME,
            {
                "status": "in_progress",
                "proposal_ids": [p.get("id") for p in proposals],
            },
        )
        overlay: dict[str, Any] = {}
        applied_ids: list[str] = []
        for proposal in proposals:
            change = proposal.get("change") or {}
            key = change.get("key")
            if not key:
                continue
            if is_protected_change(str(key)):
                raise ProtectedSurfaceError(
                    f"candidato não pode alterar superfície protegida: {key}"
                )
            _set_dotted(overlay, str(key), change.get("value"))
            applied_ids.append(str(proposal["id"]))
            proposal["status"] = "applied_to_candidate"

        overlay_path = candidate / "config" / OVERLAY_NAME
        atomic_write_text(
            overlay_path,
            yaml.safe_dump(overlay, allow_unicode=True, sort_keys=True),
        )
        diff = _unified_diff(baseline, candidate)
        pair.candidate.refresh(diff=diff)
        atomic_write_json(candidate / "identity.json", pair.candidate.to_dict())
        atomic_write_json(
            candidate / JOURNAL_NAME,
            {
                "status": "applied",
                "proposal_ids": applied_ids,
                "diff": diff,
                "workspace_commit": pair.candidate.workspace_commit,
            },
        )
        return ApplyResult(
            status="applied" if applied_ids else "skipped",
            applied_ids=applied_ids,
            diff=diff,
            baseline=pair.baseline.to_dict(),
            candidate=pair.candidate.to_dict(),
            reason=[] if applied_ids else ["no_applyable_change"],
        )
    except BaseException:
        try:
            atomic_write_json(
                candidate / JOURNAL_NAME,
                {
                    "status": "failed",
                    "proposal_ids": [p.get("id") for p in proposals],
                },
            )
        except OSError:
            pass
        for proposal in proposals:
            if proposal.get("status") == "applied_to_candidate":
                proposal["status"] = "proposed"
        raise
    finally:
        try:
            lock.rmdir()
        except OSError:
            pass
