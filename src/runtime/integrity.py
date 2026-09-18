"""Cadeia HMAC-SHA256 de eventos e selo de artefatos.

Fail-closed: sem `PROMPTLESS_INTEGRITY_KEY` a trilha não é assinada nem
verificada. SHA-256 do payload permanece no campo `hash` (auditoria); a
autenticidade está em `hmac` = HMAC(key, prev_hmac || hash).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any

from src.runtime.atomic_io import TMP_PREFIX, read_json, sha256_of

GENESIS_HASH = "0" * 64
INTEGRITY_KEY_ENV = "PROMPTLESS_INTEGRITY_KEY"
_MIN_KEY_LEN = 16
_UNSIGNED_FIELDS = frozenset({"hash", "hmac", "prev_hmac"})


class MissingIntegrityKey(RuntimeError):
    """Chave HMAC ausente ou curta demais — a trilha não pode ser assinada."""


def load_integrity_key() -> bytes:
    value = os.environ.get(INTEGRITY_KEY_ENV, "").strip()
    if len(value) < _MIN_KEY_LEN:
        raise MissingIntegrityKey(
            f"{INTEGRITY_KEY_ENV} é obrigatória (≥{_MIN_KEY_LEN} chars) para "
            "assinar a trilha; gere um segredo e exporte antes de rodar"
        )
    return value.encode("utf-8")


def event_hash(record: dict[str, Any]) -> str:
    """SHA-256 canônico do evento, excluindo hash/hmac."""
    payload = {k: v for k, v in record.items() if k not in _UNSIGNED_FIELDS}
    blob = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def event_hmac(prev_hmac: str, content_hash: str, *, key: bytes | None = None) -> str:
    secret = key if key is not None else load_integrity_key()
    msg = f"{prev_hmac}:{content_hash}".encode("utf-8")
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


def _canonical_hmac(payload: dict[str, Any], *, key: bytes | None = None) -> str:
    secret = key if key is not None else load_integrity_key()
    blob = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hmac.new(secret, blob.encode("utf-8"), hashlib.sha256).hexdigest()


def seal_hmac(integrity: dict[str, Any], *, key: bytes | None = None) -> str:
    """HMAC do selo, excluindo o próprio campo `hmac`."""
    body = {k: v for k, v in integrity.items() if k != "hmac"}
    return _canonical_hmac(body, key=key)


def verify_event_chain(
    records: list[dict[str, Any]], *, key: bytes | None = None
) -> list[str]:
    errors: list[str] = []
    try:
        secret = key if key is not None else load_integrity_key()
    except MissingIntegrityKey as exc:
        return [str(exc)]
    prev_hash = GENESIS_HASH
    prev_mac = GENESIS_HASH
    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            errors.append(f"evento[{i}] não é objeto JSON")
            continue
        if rec.get("prev_hash") != prev_hash:
            errors.append(f"evento[{i}] prev_hash quebrado")
        if rec.get("prev_hmac") != prev_mac:
            errors.append(f"evento[{i}] prev_hmac quebrado")
        content = event_hash(rec)
        stored_hash = rec.get("hash")
        if stored_hash != content:
            errors.append(f"evento[{i}] hash inválido")
        stored_mac = rec.get("hmac")
        expected_mac = event_hmac(prev_mac, content, key=secret)
        if not stored_mac or not hmac.compare_digest(str(stored_mac), expected_mac):
            errors.append(f"evento[{i}] hmac inválido")
        prev_hash = str(stored_hash or content)
        prev_mac = str(stored_mac or expected_mac)
    return errors


def verify_run_dir(run_dir: Path) -> dict[str, Any]:
    """
    Detecta adulteração da cadeia HMAC e dos artefatos selados.

    Fail-closed sem `PROMPTLESS_INTEGRITY_KEY`. Evento forjado com
    `prev_hash` correto falha o `hmac`. Artefato listado em
    `manifest.integrity.files` com sha256 divergente ou selo HMAC inválido
    também falha.
    """
    run_dir = Path(run_dir)
    errors: list[str] = []
    try:
        secret = load_integrity_key()
    except MissingIntegrityKey as exc:
        return {
            "ok": False,
            "errors": [str(exc)],
            "events_checked": 0,
            "files_checked": 0,
        }
    events_path = run_dir / "events.jsonl"
    records: list[dict[str, Any]] = []
    if events_path.is_file() and events_path.stat().st_size > 0:
        for line in events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                errors.append("events.jsonl contém linha ilegível")
                rec = {}
            records.append(rec if isinstance(rec, dict) else {})
    errors.extend(verify_event_chain(records, key=secret))

    seen_macs = [str(r.get("hmac") or "") for r in records if isinstance(r, dict)]
    manifest = read_json(run_dir / "manifest.json") or {}
    integrity = manifest.get("integrity") if isinstance(manifest, dict) else {}
    if not isinstance(integrity, dict):
        integrity = {}
    tip = integrity.get("events_tip")
    if tip and tip not in seen_macs:
        errors.append("events_tip do manifesto não aparece na cadeia HMAC")

    stored_seal = integrity.get("hmac")
    if not stored_seal:
        errors.append("selo HMAC do manifesto ausente")
    else:
        expected_seal = seal_hmac(integrity, key=secret)
        if not hmac.compare_digest(str(stored_seal), expected_seal):
            errors.append("selo HMAC do manifesto inválido")

    files_checked = 0
    for entry in integrity.get("files") or []:
        if not isinstance(entry, dict):
            continue
        rel = str(entry.get("path") or "")
        if not rel or rel.startswith("/") or ".." in Path(rel).parts:
            errors.append(f"caminho de selo inválido: {rel!r}")
            continue
        path = run_dir / rel
        files_checked += 1
        if not path.is_file():
            errors.append(f"artefato ausente: {rel}")
            continue
        expected = str(entry.get("sha256") or "")
        actual = sha256_of(path)
        if expected and actual != expected:
            errors.append(f"artefato adulterado: {rel}")

    return {
        "ok": not errors,
        "errors": errors,
        "events_checked": len(records),
        "files_checked": files_checked,
    }


def collect_sealed_files(run_dir: Path, *folders: Path) -> list[dict[str, Any]]:
    """Lista arquivos reais sob as pastas, com sha256 relativo a `run_dir`."""
    run_dir = Path(run_dir).resolve()
    files: list[dict[str, Any]] = []
    for folder in folders:
        folder = Path(folder)
        if not folder.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(
            str(folder), followlinks=False
        ):
            dirnames.sort()
            for name in sorted(filenames):
                path = Path(dirpath) / name
                if path.is_symlink() or not path.is_file():
                    continue
                if name.startswith(TMP_PREFIX):
                    continue
                rel = path.resolve().relative_to(run_dir)
                files.append(
                    {
                        "path": rel.as_posix(),
                        "bytes": path.stat().st_size,
                        "sha256": sha256_of(path),
                    }
                )
    return files
