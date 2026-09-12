"""Referência a trecho de fonte documental."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class SourceRef:
    document: str
    section: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    content_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}
