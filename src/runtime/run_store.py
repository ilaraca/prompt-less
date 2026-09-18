"""Persistência de diretório de run, manifest e espelho em outputs/."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.runtime.atomic_io import (
    TMP_PREFIX,
    UnsafePath,
    atomic_copy,
    atomic_write_json,
    read_json,
    resolve_within,
    sha256_of,
)
from src.runtime.event_store import EventStore
from src.runtime.integrity import collect_sealed_files, current_kid, seal_hmac
from src.runtime.run_context import RunContext

# manifesto do espelho: ponto de commit da publicação em outputs/
MIRROR_MANIFEST_NAME = ".mirror-manifest.json"

TERMINAL_STATUSES = frozenset({"completed", "blocked", "failed", "cancelled"})
# "" = manifest ainda não existe
_ALLOWED_TRANSITIONS: dict[str, frozenset] = {
    "": frozenset({"running"}),
    "running": frozenset({"running", "completed", "blocked", "failed", "cancelled"}),
    # retomada de run interrompida ou falha — completed/blocked continuam finais
    "failed": frozenset({"running"}),
    "cancelled": frozenset({"running"}),
}


class RunIdCollision(RuntimeError):
    """Já existe uma run com este `run_id` neste root."""


class RunStateConflict(RuntimeError):
    """O manifest mudou de versão entre a leitura e a escrita."""


class InvalidStatusTransition(RuntimeError):
    """Transição de status não permitida para o estado atual da run."""


class RunStore:
    def __init__(self, ctx: RunContext) -> None:
        self.ctx = ctx
        self.events = EventStore(ctx.events_path)

    # ------------------------------------------------------------------ run

    def bootstrap(self, *, resume: bool = False) -> None:
        """
        Reserva o diretório da run.

        O `mkdir` é exclusivo: se o `run_id` já existe, a run anterior é
        preservada e a nova falha com `RunIdCollision` (fail-closed). Retomada
        explícita usa `resume=True`.
        """
        run_dir = self.ctx.run_dir
        run_dir.parent.mkdir(parents=True, exist_ok=True)
        try:
            run_dir.mkdir()
        except FileExistsError:
            if not resume:
                raise RunIdCollision(
                    f"run_id '{self.ctx.run_id}' já existe em {run_dir}; "
                    "gere um id novo ou use bootstrap(resume=True)"
                ) from None
        for d in (
            self.ctx.artifacts_dir,
            self.ctx.validations_dir,
            self.ctx.checkpoints_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

        existing = self.read_manifest()
        self.set_status(
            "running",
            run_id=self.ctx.run_id,
            started_at=existing.get("started_at") or _now(),
            pipeline_version=self.ctx.pipeline_version,
            objective=self.ctx.objective,
            current_stage="bootstrap",
            resumed=bool(existing) or None,
        )
        self.events.emit(
            "run_started", run_id=self.ctx.run_id, objective=self.ctx.objective
        )

    def finish(self, status: str, result: dict[str, Any] | None = None) -> None:
        if status not in TERMINAL_STATUSES:
            raise InvalidStatusTransition(f"status final inválido: {status!r}")
        self.set_status(
            status,
            finished_at=_now(),
            current_stage="done" if status == "completed" else status,
            result_summary={
                "split": (result or {}).get("split"),
                "contexts": (result or {}).get("contexts"),
                "output": (result or {}).get("output"),
            }
            if result
            else None,
        )
        self.events.emit("run_finished", status=status, run_id=self.ctx.run_id)
        self._write_latest_pointer(status)

    # ------------------------------------------------------------- manifest

    def read_manifest(self) -> dict[str, Any]:
        data = read_json(self.ctx.manifest_path)
        return data if isinstance(data, dict) else {}

    @property
    def manifest_version(self) -> int:
        return int(self.read_manifest().get("version") or 0)

    @property
    def status(self) -> str:
        return str(self.read_manifest().get("status") or "")

    @property
    def is_finished(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def write_manifest(
        self,
        data: dict[str, Any],
        *,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """
        Faz merge em `manifest.json` por write-temp + rename.

        `version` é monotônico; passar `expected_version` aplica controle
        otimista de concorrência (conflito = `RunStateConflict`).
        """
        existing = self.read_manifest()
        current = int(existing.get("version") or 0)
        if expected_version is not None and int(expected_version) != current:
            raise RunStateConflict(
                f"manifest da run '{self.ctx.run_id}' está na versão {current}, "
                f"esperava {expected_version}"
            )
        merged = {**existing, **data}
        merged["version"] = current + 1
        merged["updated_at"] = _now()
        atomic_write_json(self.ctx.manifest_path, merged)
        return merged

    def set_status(
        self,
        status: str,
        *,
        expected_version: int | None = None,
        **fields: Any,
    ) -> dict[str, Any]:
        """Transição de status versionada e auditada em `status_history`."""
        existing = self.read_manifest()
        current_status = str(existing.get("status") or "")
        current_version = int(existing.get("version") or 0)
        if expected_version is not None and int(expected_version) != current_version:
            raise RunStateConflict(
                f"manifest da run '{self.ctx.run_id}' está na versão "
                f"{current_version}, esperava {expected_version}"
            )
        allowed = _ALLOWED_TRANSITIONS.get(current_status)
        if allowed is None or status not in allowed:
            raise InvalidStatusTransition(
                f"transição {current_status or '<nova>'!r} → {status!r} não "
                f"permitida na run '{self.ctx.run_id}'"
            )
        history = list(existing.get("status_history") or [])
        history.append(
            {
                "from": current_status or None,
                "to": status,
                "version": current_version + 1,
                "at": _now(),
            }
        )
        payload = {k: v for k, v in fields.items() if v is not None}
        payload["status"] = status
        payload["status_history"] = history
        return self.write_manifest(payload, expected_version=current_version)

    # ----------------------------------------------------------- provenance

    def write_provenance(
        self,
        *,
        claims: list[dict[str, Any]],
        discarded: list[dict[str, Any]],
    ) -> Path:
        """Persiste claims e relatório de descarte em validations/."""
        report = {
            "run_id": self.ctx.run_id,
            "claims_count": len(claims),
            "discarded_count": len(discarded),
            "claims": claims,
            "discarded": discarded,
        }
        path = self.ctx.validations_dir / "provenance.json"
        atomic_write_json(path, report)
        self.events.emit(
            "provenance_recorded",
            claims=len(claims),
            discarded=len(discarded),
        )
        return path

    def seal_artifacts(self) -> dict[str, Any]:
        """
        Ancora sha256 dos artefatos no manifest com HMAC da ponta da cadeia.

        Não emite evento depois do selo: `events_tip` é o HMAC do último
        evento já gravado (`run_finished` se chamado após `finish`).
        """
        files = collect_sealed_files(
            self.ctx.run_dir, self.ctx.artifacts_dir, self.ctx.validations_dir
        )
        kid = current_kid()
        integrity = {
            "algo": "hmac-sha256",
            "kid": kid,
            "events_tip": self.events.tip,
            "files": files,
            "sealed_at": _now(),
        }
        integrity["hmac"] = seal_hmac(integrity)
        self.write_manifest({"integrity": integrity})
        return integrity

    def sealed_file_entries(self) -> list[dict[str, Any]]:
        """Entradas `integrity.files` do manifesto (registro canônico da run)."""
        integrity = self.read_manifest().get("integrity")
        if not isinstance(integrity, dict):
            return []
        files = integrity.get("files") or []
        return [e for e in files if isinstance(e, dict)]

    def resolve_sealed_path(self, rel: str) -> Path:
        """
        Resolve um caminho relativo listado no selo, contido em `run_dir`.

        Espelhos (`outputs/`) ficam fora deste contrato — só a árvore da run.
        """
        rel = str(rel or "")
        if not rel or rel.startswith("/") or ".." in Path(rel).parts:
            raise UnsafePath(f"caminho de selo inválido: {rel!r}")
        return resolve_within(self.ctx.run_dir, self.ctx.run_dir / rel)

    def verify_sealed_entry(self, entry: dict[str, Any]) -> Path:
        """Confirma existência + sha256 de uma entrada do manifesto."""
        rel = str(entry.get("path") or "")
        path = self.resolve_sealed_path(rel)
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(f"artefato ausente: {rel}")
        expected = str(entry.get("sha256") or "")
        if expected and sha256_of(path) != expected:
            raise ValueError(f"artefato adulterado: {rel}")
        return path

    def write_debugger(self, report: dict[str, Any]) -> Path:
        """Persiste o Agent Debugger em validations/debugger.json."""
        path = self.ctx.validations_dir / "debugger.json"
        atomic_write_json(path, report)
        self.events.emit(
            "debugger_recorded",
            terminal_cause=(report.get("failure") or {}).get("terminal_cause"),
            owner=(report.get("harness_component") or {}).get("probable_owner"),
        )
        return path

    # --------------------------------------------------------------- mirror

    def mirror_artifacts_to_outputs(self, compat_root: Path) -> dict[str, Any] | None:
        """
        Publica `runs/<id>/artifacts` em `<compat_root>/outputs` (Devin/scripts).

        Cada arquivo vai por temp + rename; `.mirror-manifest.json` é o ponto de
        commit da publicação e só depois dele os artefatos obsoletos da
        publicação anterior são removidos.
        """
        src = self.ctx.artifacts_dir
        if not src.exists():
            return None
        dest = Path(compat_root) / "outputs"
        dest.mkdir(parents=True, exist_ok=True)
        dest_root = dest.resolve()
        previous = read_json(dest_root / MIRROR_MANIFEST_NAME) or {}

        files: list[dict[str, Any]] = []
        # followlinks=False: symlink de diretório não é percorrido, symlink de
        # arquivo é ignorado — o espelho só publica arquivo real de artifacts/
        for dirpath, dirnames, filenames in os.walk(str(src), followlinks=False):
            dirnames.sort()
            for name in sorted(filenames):
                path = Path(dirpath) / name
                if path.is_symlink() or not path.is_file():
                    continue
                if name.startswith(TMP_PREFIX):
                    continue
                rel = path.relative_to(src)
                target = resolve_within(dest_root, dest_root / rel)
                atomic_copy(path, target)
                files.append(
                    {
                        "path": rel.as_posix(),
                        "bytes": path.stat().st_size,
                        "sha256": sha256_of(path),
                    }
                )

        manifest = {
            "run_id": self.ctx.run_id,
            "published_at": _now(),
            "source": str(src),
            "files": files,
        }
        atomic_write_json(dest_root / MIRROR_MANIFEST_NAME, manifest)

        removed = self._prune_stale_mirror(
            dest_root, previous, {entry["path"] for entry in files}
        )
        self.events.emit(
            "mirror_published",
            run_id=self.ctx.run_id,
            files=len(files),
            removed=len(removed),
        )
        return manifest

    @staticmethod
    def _prune_stale_mirror(
        dest_root: Path,
        previous: dict[str, Any],
        current: set,
    ) -> list[str]:
        """
        Remove do espelho só o que ele mesmo publicou antes e não publica mais.

        Arquivos que nunca constaram de um manifesto (colocados à mão em
        `outputs/`) nunca são tocados.
        """
        removed: list[str] = []
        for entry in previous.get("files") or []:
            rel = str((entry or {}).get("path") or "")
            if not rel or rel in current:
                continue
            try:
                stale = resolve_within(dest_root, dest_root / rel)
            except UnsafePath:
                continue
            candidate = dest_root / rel
            if candidate.is_symlink() or not stale.is_file():
                continue
            stale.unlink()
            removed.append(rel)
            _prune_empty_dirs(stale.parent, dest_root)
        return removed

    def _write_latest_pointer(self, status: str) -> None:
        latest = self.ctx.runs_dir / "latest.json"
        atomic_write_json(
            latest,
            {
                "run_id": self.ctx.run_id,
                "run_dir": str(self.ctx.run_dir),
                "status": status,
                "version": self.manifest_version,
                "updated_at": _now(),
            },
        )


def _prune_empty_dirs(directory: Path, stop_at: Path) -> None:
    current = directory
    while current != stop_at and stop_at in current.parents:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
