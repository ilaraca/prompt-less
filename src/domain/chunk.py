"""Chunks documentais com metadados de proveniência."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any


def content_hash(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"


@dataclass
class DocumentChunk:
    id: str
    document: str
    section: str | None
    start_line: int
    end_line: int
    raw_text: str
    content_hash: str
    service_id: str | None = None
    signals: list[str] = field(default_factory=list)
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["raw_text"] = self.raw_text[:500]
        return data


@dataclass
class ChunkSummary:
    chunk_id: str
    summary: str
    selected_lines: list[int]
    signals: list[str]
    discarded: bool
    reason: str | None = None
    recoverable: bool = True
    document: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    content_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}
