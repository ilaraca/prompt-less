"""Domínio de proveniência e especificação intermediária."""
from __future__ import annotations

from src.domain.claim import Claim, ClaimOrigin
from src.domain.chunk import ChunkSummary, DocumentChunk
from src.domain.source_ref import SourceRef

__all__ = [
    "Claim",
    "ClaimOrigin",
    "ChunkSummary",
    "DocumentChunk",
    "SourceRef",
]
