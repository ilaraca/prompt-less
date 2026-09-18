"""Carrega `config/pipeline.yaml` e faz merge do overlay versionado."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

OVERLAY_NAME = "proposal-overlay.yaml"


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Merge recursivo: chaves do overlay vencem; dicts combinam."""
    out: dict[str, Any] = dict(base)
    for key, value in overlay.items():
        current = out.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            out[key] = deep_merge(current, value)
        else:
            out[key] = value
    return out


def set_dotted(data: dict[str, Any], key: str, value: Any) -> None:
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


def load_merged_cfg(root: Path) -> dict[str, Any]:
    """
    Lê `config/pipeline.yaml` sob `root` e mescla `proposal-overlay.yaml`
    quando existir. Assim baseline/candidate e apply em produção enxergam
    `change.key/value` versionados.
    """
    root = Path(root)
    pipeline = root / "config" / "pipeline.yaml"
    raw = yaml.safe_load(pipeline.read_text(encoding="utf-8")) if pipeline.is_file() else {}
    cfg: dict[str, Any] = dict(raw or {})
    overlay_path = root / "config" / OVERLAY_NAME
    if overlay_path.is_file():
        overlay = yaml.safe_load(overlay_path.read_text(encoding="utf-8")) or {}
        if isinstance(overlay, dict):
            cfg = deep_merge(cfg, overlay)
    return cfg
