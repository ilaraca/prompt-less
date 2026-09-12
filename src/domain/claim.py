"""Claim — afirmação rastreável extraída de fontes."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from src.domain.source_ref import SourceRef


class ClaimOrigin(str, Enum):
    DECLARED = "declared"
    OBSERVED = "observed"
    INFERRED = "inferred"
    DEFAULT = "default"
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"


@dataclass
class Claim:
    id: str
    text: str
    origin: ClaimOrigin
    confidence: float
    sources: list[SourceRef] = field(default_factory=list)
    service_id: str | None = None
    requires_review: bool = False
    chunk_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "origin": self.origin.value,
            "confidence": self.confidence,
            "sources": [s.to_dict() for s in self.sources],
            "service_id": self.service_id,
            "requires_review": self.requires_review,
            "chunk_id": self.chunk_id,
        }
