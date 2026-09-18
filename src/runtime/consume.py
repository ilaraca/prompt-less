"""Gates de consumo: só run completed e identidade coerente liberam o executor."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from src.runtime.atomic_io import read_json
from src.runtime.run_context import validate_run_id

DISPATCHABLE_STATUS = "completed"


class RunNotReady(RuntimeError):
    """Run não está liberada para despacho ao executor."""

    def __init__(
        self,
        message: str,
        *,
        run_id: str | None = None,
        status: str | None = None,
        reason: str | None = None,
    ) -> None:
        super().__init__(message)
        self.run_id = run_id
        self.status = status
        self.reason = reason


def _reason_from_manifest(manifest: dict[str, Any]) -> str | None:
    summary = manifest.get("result_summary")
    if isinstance(summary, dict) and summary.get("reason"):
        return str(summary["reason"])
    if manifest.get("reason"):
        return str(manifest["reason"])
    return None


def _find_mirror_manifest(start: Path) -> Path | None:
    cursor = Path(start).resolve()
    for _ in range(6):
        candidate = cursor / ".mirror-manifest.json"
        if candidate.is_file():
            return candidate
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    return None


def load_run_manifest(run_dir: Path) -> dict[str, Any]:
    path = Path(run_dir) / "manifest.json"
    data = read_json(path)
    if not isinstance(data, dict) or not data:
        raise RunNotReady(
            f"manifest ausente ou inválido em {path}",
            status=None,
        )
    return data


def assert_run_ready_for_executor(
    run_dir: Path,
    *,
    run_id: str,
    artifacts_dir: Path | str | None = None,
) -> dict[str, Any]:
    """
    Fail-closed antes do despacho: exige manifesto `completed` da mesma run.

    Impede usar run blocked/failed e artefatos/história de outra execução
    (ex.: espelho antigo em `outputs/`).
    """
    expected = validate_run_id(run_id)
    run_dir = Path(run_dir)
    manifest = load_run_manifest(run_dir)
    found_id = str(manifest.get("run_id") or "")
    status = str(manifest.get("status") or "")
    reason = _reason_from_manifest(manifest)

    if found_id != expected:
        raise RunNotReady(
            f"run_id do manifesto ({found_id!r}) diverge do pedido ({expected!r}) "
            "— recusa reutilização de história/artefatos de outra execução",
            run_id=found_id or expected,
            status=status or None,
            reason=reason,
        )

    if status != DISPATCHABLE_STATUS:
        detail = f"status={status!r}"
        if reason:
            detail += f" reason={reason!r}"
        raise RunNotReady(
            f"run {expected!r} não está liberada para o executor ({detail})",
            run_id=expected,
            status=status or None,
            reason=reason,
        )

    if artifacts_dir is not None:
        art = Path(artifacts_dir).resolve()
        expected_art = (run_dir / "artifacts").resolve()
        under_run = art == expected_art or expected_art in art.parents
        if not under_run:
            mirror_path = _find_mirror_manifest(art)
            if mirror_path is None:
                raise RunNotReady(
                    f"artefatos {art} fora de runs/{expected}/artifacts e sem "
                    ".mirror-manifest.json — recusa história órfã/antiga",
                    run_id=expected,
                    status=status,
                    reason=reason,
                )
            mirror_data = read_json(mirror_path) or {}
            mirror_id = str(mirror_data.get("run_id") or "")
            if mirror_id != expected:
                raise RunNotReady(
                    f"espelho run_id={mirror_id!r} ≠ {expected!r} — "
                    "recusa reutilização de história antiga",
                    run_id=mirror_id or expected,
                    status=status,
                    reason=reason,
                )
            mirror_status = str(mirror_data.get("status") or "")
            if mirror_status and mirror_status != DISPATCHABLE_STATUS:
                raise RunNotReady(
                    f"espelho marca status={mirror_status!r}; não despacha",
                    run_id=expected,
                    status=mirror_status,
                    reason=str(mirror_data.get("reason") or reason or ""),
                )

    return manifest


def resolve_run_dir(root: Path, run_id: str) -> Path:
    rid = validate_run_id(run_id)
    return Path(root) / "runs" / rid
