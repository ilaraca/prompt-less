"""Cadeia de hash de eventos e selo de artefatos (sem HMAC)."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from src.runtime.atomic_io import TMP_PREFIX, read_json, sha256_of

GENESIS_HASH = "0" * 64


def event_hash(record: dict[str, Any]) -> str:
    """SHA-256 canônico do evento, excluindo o campo `hash`."""
    payload = {k: v for k, v in record.items() if k != "hash"}
    blob = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def verify_event_chain(records: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    prev = GENESIS_HASH
    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            errors.append(f"evento[{i}] não é objeto JSON")
            continue
        if rec.get("prev_hash") != prev:
            errors.append(f"evento[{i}] prev_hash quebrado")
        stored = rec.get("hash")
        expected = event_hash(rec)
        if stored != expected:
            errors.append(f"evento[{i}] hash inválido")
        prev = str(stored or expected)
    return errors


def verify_run_dir(run_dir: Path) -> dict[str, Any]:
    """
    Detecta adulteração da cadeia de eventos e dos artefatos selados.

    Sem HMAC: alteração de um evento histórico quebra a cadeia; alteração de
    um artefato listado em `manifest.integrity.files` diverge do sha256.
    """
    run_dir = Path(run_dir)
    errors: list[str] = []
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
    errors.extend(verify_event_chain(records))

    seen_hashes = [str(r.get("hash") or "") for r in records if isinstance(r, dict)]
    manifest = read_json(run_dir / "manifest.json") or {}
    integrity = manifest.get("integrity") if isinstance(manifest, dict) else {}
    if not isinstance(integrity, dict):
        integrity = {}
    tip = integrity.get("events_tip")
    if tip and tip not in seen_hashes:
        errors.append("events_tip do manifesto não aparece na cadeia")

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
