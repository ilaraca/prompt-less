"""Escrita atômica (write-temp + rename) e contenção de caminho.

Toda publicação de estado da run passa por aqui. O arquivo final só aparece
depois do `os.replace`, então um processo morto no meio da escrita nunca deixa
JSON parcial — no pior caso sobra um temporário oculto no mesmo diretório, que
é removido no tratamento de erro.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

TMP_PREFIX = ".tmp-"


class UnsafePath(ValueError):
    """Caminho de escrita fora do diretório autorizado."""


def resolve_within(base: Path, candidate: Path) -> Path:
    """
    Resolve `candidate` e garante que ele fique sob `base`.

    Resolve os dois lados (segue symlinks) para que nem `..` nem link plantado
    dentro do diretório autorizado consigam escapar.
    """
    base_resolved = Path(base).resolve()
    target = Path(candidate).resolve()
    if target != base_resolved and base_resolved not in target.parents:
        raise UnsafePath(f"caminho fora de {base_resolved}: {target}")
    return target


def _fsync_dir(directory: Path) -> None:
    """Persiste a entrada de diretório criada pelo rename (best-effort)."""
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_bytes(path: Path, payload: bytes) -> Path:
    """Grava `payload` em `path` por temporário + rename atômico."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f"{TMP_PREFIX}{path.name}.", suffix=".part", dir=str(path.parent)
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(str(tmp), str(path))
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    _fsync_dir(path.parent)
    return path


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> Path:
    return atomic_write_bytes(path, text.encode(encoding))


def atomic_write_json(path: Path, data: Any, *, indent: int = 2) -> Path:
    return atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=indent))


def atomic_copy(src: Path, dest: Path) -> Path:
    """Copia `src` para `dest` sem expor conteúdo parcial no destino."""
    src = Path(src)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f"{TMP_PREFIX}{dest.name}.", suffix=".part", dir=str(dest.parent)
    )
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        shutil.copyfile(str(src), str(tmp))
        shutil.copystat(str(src), str(tmp))
        os.replace(str(tmp), str(dest))
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    _fsync_dir(dest.parent)
    return dest


def read_json(path: Path) -> Any:
    """Lê JSON; devolve None se o arquivo não existe ou está ilegível."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()
