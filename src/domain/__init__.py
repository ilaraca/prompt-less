"""Domínio de proveniência e especificação intermediária."""
from __future__ import annotations

from src.domain.claim import Claim, ClaimOrigin
from src.domain.chunk import ChunkSummary, DocumentChunk
from src.domain.provenance import (
    MATCH_REVIEW_THRESHOLD,
    claim_fingerprint,
    claim_namespace,
    make_claim_id,
    merge_claims,
)
from src.domain.source_ref import SourceRef
from src.domain.spec import (
    AcceptanceCriterion,
    CanonicalSpec,
    ClaimLink,
    Requirement,
    ResolvedInt,
)

__all__ = [
    "AcceptanceCriterion",
    "CanonicalSpec",
    "Claim",
    "ClaimLink",
    "ClaimOrigin",
    "ChunkSummary",
    "DocumentChunk",
    "MATCH_REVIEW_THRESHOLD",
    "Requirement",
    "ResolvedInt",
    "SourceRef",
    "claim_fingerprint",
    "claim_namespace",
    "make_claim_id",
    "merge_claims",
]
