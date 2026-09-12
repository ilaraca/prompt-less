"""Domínio de proveniência e especificação intermediária."""
from __future__ import annotations

from src.domain.claim import Claim, ClaimOrigin
from src.domain.chunk import ChunkSummary, DocumentChunk
from src.domain.source_ref import SourceRef
from src.domain.spec import AcceptanceCriterion, CanonicalSpec, Requirement

__all__ = [
    "AcceptanceCriterion",
    "CanonicalSpec",
    "Claim",
    "ClaimOrigin",
    "ChunkSummary",
    "DocumentChunk",
    "Requirement",
    "SourceRef",
]
