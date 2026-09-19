"""Estado externo — substitui histórico de conversa no prompt.

Backend default: arquivo (`config/pipeline.yaml` → `state.backend: file`).
Este módulo expõe compare-and-set e lock de transição no file backend —
o requisito de concorrência do `13-parallel-exec` sem Redis (`12b` parqueado).
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Protocol

from src.runtime.atomic_io import atomic_write_json

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / "state" / "workflow.json"

VERSION_KEY = "_version"
LOCK_SUFFIX = ".lock"
DEFAULT_LOCK_TIMEOUT_S = 10.0
DEFAULT_LOCK_POLL_S = 0.05


class StateConflict(RuntimeError):
    """Versão do state divergiu entre leitura e escrita (CAS falhou)."""


class StateLockTimeout(TimeoutError):
    """Não foi possível adquirir o lock do arquivo a tempo."""


class StateBackend(Protocol):
    """Interface comum file/Redis — Redis fica para `12b`."""

    def read(self) -> dict[str, Any]:
        """Lê o documento de estado (inclui `_version` quando versionado)."""

    def compare_and_set(
        self,
        expected_version: int,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Grava só se a versão atual for `expected_version`; senão `StateConflict`."""

    def lock(self, *, timeout_s: float = DEFAULT_LOCK_TIMEOUT_S) -> Any:
        """Context manager de exclusão mútua para transições compostas."""


def read_state(path: Path = DEFAULT_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_state(data: dict[str, Any], path: Path = DEFAULT_PATH) -> dict[str, Any]:
    # só campos relevantes ao workflow (padrão do artigo)
    docs_meta = [
        {"name": d.get("name"), "lines": d.get("lines"), "est_tokens_raw": d.get("est_tokens_raw")}
        for d in (data.get("documents") or [])
    ]
    slim = {
        "tipo": data.get("tipo"),
        "fluxo": (data.get("regras") or {}).get("fluxo"),
        "inputs": [i.get("name") for i in (data.get("ui") or {}).get("inputs", [])],
        "actions": (data.get("ui") or {}).get("actions", []),
        "bloqueios": (data.get("regras") or {}).get("bloqueios", []),
        "engenharia": {
            "version": (data.get("engenharia") or {}).get("version"),
            "stack": (data.get("engenharia") or {}).get("stack"),
            "criticidade": (data.get("engenharia") or {}).get("criticidade"),
            "nfr_ids": [
                n.get("id") if isinstance(n, dict) else getattr(n, "id", n)
                for n in (
                    (data.get("engenharia") or {}).get("nfr_ids")
                    or (data.get("engenharia") or {}).get("_selected_nfrs")
                    or []
                )
            ]
            or None,
            "resiliencia": {
                "timeout_ms": ((data.get("engenharia") or {}).get("resiliencia") or {}).get(
                    "timeout_ms"
                ),
            },
            "observabilidade": {
                "logs": {
                    "formato": (
                        ((data.get("engenharia") or {}).get("observabilidade") or {}).get(
                            "logs"
                        )
                        or {}
                    ).get("formato")
                }
            },
        },
        "documents": docs_meta,  # metadados só — sem texto bruto
        "previous_actions": data.get("previous_actions", []),
        "status": data.get("status", "ready"),
    }
    # write-temp + rename: interrupção nunca deixa state.json parcial
    atomic_write_json(Path(path), slim)
    return slim


def state_version(data: dict[str, Any] | None) -> int:
    if not data:
        return 0
    raw = data.get(VERSION_KEY)
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def _lock_path(path: Path) -> Path:
    return Path(path).with_name(Path(path).name + LOCK_SUFFIX)


@contextmanager
def file_lock(
    path: Path,
    *,
    timeout_s: float = DEFAULT_LOCK_TIMEOUT_S,
    poll_s: float = DEFAULT_LOCK_POLL_S,
) -> Iterator[Path]:
    """Lock exclusivo via `fcntl.flock` num sidecar `.lock` (POSIX)."""
    import fcntl

    target = Path(path)
    lock_file = _lock_path(target)
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_file, "a+", encoding="utf-8")
    deadline = time.monotonic() + max(0.0, timeout_s)
    try:
        while True:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise StateLockTimeout(
                        f"timeout ({timeout_s}s) ao adquirir lock de {target}"
                    ) from None
                time.sleep(poll_s)
        yield lock_file
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        fh.close()


def compare_and_set_state(
    expected_version: int,
    data: dict[str, Any],
    path: Path = DEFAULT_PATH,
    *,
    timeout_s: float = DEFAULT_LOCK_TIMEOUT_S,
) -> dict[str, Any]:
    """
    Compare-and-set versionado no file backend.

    Sob lock: lê a versão atual; se divergir de `expected_version`, levanta
    `StateConflict`; senão grava `data` com `_version = expected + 1`.
    """
    target = Path(path)
    with file_lock(target, timeout_s=timeout_s):
        current = read_state(target) if target.exists() else {}
        current_version = state_version(current)
        if int(expected_version) != current_version:
            raise StateConflict(
                f"state em {target} está na versão {current_version}, "
                f"esperava {expected_version}"
            )
        payload = dict(data)
        payload[VERSION_KEY] = current_version + 1
        atomic_write_json(target, payload)
        return payload


def update_state(
    mutator: Any,
    path: Path = DEFAULT_PATH,
    *,
    timeout_s: float = DEFAULT_LOCK_TIMEOUT_S,
    max_retries: int = 8,
) -> dict[str, Any]:
    """
    Aplica `mutator(current) -> new_data` com retry em conflito CAS.

    `mutator` recebe o dict atual (sem exigir `_version` no retorno).
    """
    target = Path(path)
    last_conflict: StateConflict | None = None
    for _ in range(max(1, max_retries)):
        current = read_state(target) if target.exists() else {}
        expected = state_version(current)
        proposed = mutator(dict(current))
        if not isinstance(proposed, dict):
            raise TypeError("mutator deve devolver dict")
        try:
            return compare_and_set_state(
                expected, proposed, target, timeout_s=timeout_s
            )
        except StateConflict as exc:
            last_conflict = exc
            time.sleep(DEFAULT_LOCK_POLL_S)
    assert last_conflict is not None
    raise last_conflict


class FileStateBackend:
    """Backend de arquivo com CAS + lock — default do pipeline."""

    def __init__(
        self,
        path: Path = DEFAULT_PATH,
        *,
        lock_timeout_s: float = DEFAULT_LOCK_TIMEOUT_S,
    ) -> None:
        self.path = Path(path)
        self.lock_timeout_s = lock_timeout_s

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {VERSION_KEY: 0}
        data = read_state(self.path)
        if VERSION_KEY not in data:
            data = {**data, VERSION_KEY: 0}
        return data

    def compare_and_set(
        self,
        expected_version: int,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        return compare_and_set_state(
            expected_version,
            data,
            self.path,
            timeout_s=self.lock_timeout_s,
        )

    @contextmanager
    def lock(self, *, timeout_s: float | None = None) -> Iterator[Path]:
        with file_lock(
            self.path,
            timeout_s=self.lock_timeout_s if timeout_s is None else timeout_s,
        ) as lock_file:
            yield lock_file


def open_state_backend(
    *,
    backend: str = "file",
    path: Path | str | None = None,
) -> FileStateBackend:
    """Factory: só `file` é suportado enquanto `12b` estiver parqueado."""
    kind = (backend or "file").strip().lower()
    if kind != "file":
        raise ValueError(
            f"state backend {kind!r} não implementado — use 'file' "
            "(Redis é o ticket 12b, parqueado)"
        )
    return FileStateBackend(Path(path) if path else DEFAULT_PATH)


# Evita import circular acidental em testes que mockam open.
__all__ = [
    "DEFAULT_PATH",
    "VERSION_KEY",
    "FileStateBackend",
    "StateBackend",
    "StateConflict",
    "StateLockTimeout",
    "compare_and_set_state",
    "file_lock",
    "open_state_backend",
    "read_state",
    "state_version",
    "update_state",
    "write_state",
]
