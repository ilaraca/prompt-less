"""Decisão humana sobre vínculo claim → RF/AC/erro que exige revisão.

Confiança numérica do match lexical não substitui evidência nem aprovação.
A decisão fica vinculada à versão da spec e ao fingerprint do claim; mudança
incompatível invalida a decisão e reabre a pendência.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

from src.domain.provenance import claim_fingerprint

if TYPE_CHECKING:
    from src.domain.claim import Claim
    from src.domain.spec import ClaimLink

ReviewOutcome = Literal["approved", "rejected"]
DECISIONS = frozenset({"approved", "rejected"})


@dataclass
class ReviewDecision:
    """Registro auditável de revisão obrigatória sobre um ClaimLink."""

    subject_id: str
    claim_id: str
    decision: str  # approved | rejected
    actor: str
    justification: str
    reviewed_spec_version: str
    reviewed_claim_fingerprint: str
    reviewed_link_method: str = "lexical"
    reviewed_link_score: float | None = None
    timestamp: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.reviewed_link_score is None:
            data.pop("reviewed_link_score", None)
        if not self.timestamp:
            data.pop("timestamp", None)
        return data

    @classmethod
    def from_raw(cls, raw: Any) -> "ReviewDecision":
        if isinstance(raw, ReviewDecision):
            return raw
        data = dict(raw or {})
        decision = str(data.get("decision") or "").strip()
        if decision not in DECISIONS:
            raise ValueError(f"decisão de revisão inválida: {decision!r}")
        actor = str(data.get("actor") or "").strip()
        justification = str(data.get("justification") or "").strip()
        if not actor:
            raise ValueError("ator é obrigatório na decisão de revisão")
        if not justification:
            raise ValueError("justificativa é obrigatória na decisão de revisão")
        score_raw = data.get("reviewed_link_score")
        return cls(
            subject_id=str(data.get("subject_id") or ""),
            claim_id=str(data.get("claim_id") or ""),
            decision=decision,
            actor=actor,
            justification=justification,
            reviewed_spec_version=str(data.get("reviewed_spec_version") or ""),
            reviewed_claim_fingerprint=str(
                data.get("reviewed_claim_fingerprint") or ""
            ),
            reviewed_link_method=str(data.get("reviewed_link_method") or "lexical"),
            reviewed_link_score=(
                None if score_raw is None else float(score_raw)
            ),
            timestamp=(
                str(data["timestamp"]) if data.get("timestamp") is not None else None
            ),
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _claim_dict(claim: Any) -> dict[str, Any] | None:
    if claim is None:
        return None
    if hasattr(claim, "to_dict"):
        return claim.to_dict()
    if isinstance(claim, dict):
        return dict(claim)
    return None


def fingerprint_for_claim(claim: Any) -> str:
    payload = _claim_dict(claim)
    if not payload:
        return ""
    return claim_fingerprint(payload)


def _link_fields(link: Any) -> tuple[str, str, float | None]:
    if link is None:
        return "", "lexical", None
    if hasattr(link, "claim_id"):
        claim_id = str(link.claim_id)
        method = str(getattr(link, "method", None) or "lexical")
        score_raw = getattr(link, "score", None)
    else:
        claim_id = str((link or {}).get("claim_id") or "")
        method = str((link or {}).get("method") or "lexical")
        score_raw = (link or {}).get("score")
    score = None if score_raw is None else float(score_raw)
    return claim_id, method, score


def decide_claim_link_review(
    *,
    spec_version: str,
    claim: Claim | dict[str, Any],
    link: ClaimLink | dict[str, Any],
    subject_id: str,
    decision: ReviewOutcome,
    actor: str,
    justification: str,
) -> ReviewDecision:
    """Cria decisão vinculada à evidência atual (spec version + claim fingerprint)."""
    if decision not in DECISIONS:
        raise ValueError(f"decisão de revisão inválida: {decision!r}")
    actor = (actor or "").strip()
    justification = (justification or "").strip()
    if not actor:
        raise ValueError("ator é obrigatório na decisão de revisão")
    if not justification:
        raise ValueError("justificativa é obrigatória na decisão de revisão")

    claim_id, method, score = _link_fields(link)
    return ReviewDecision(
        subject_id=subject_id,
        claim_id=claim_id,
        decision=decision,
        actor=actor,
        justification=justification,
        reviewed_spec_version=str(spec_version),
        reviewed_claim_fingerprint=fingerprint_for_claim(claim),
        reviewed_link_method=method,
        reviewed_link_score=score,
        timestamp=_now(),
    )


def find_review_decision(
    decisions: list[ReviewDecision] | list[dict[str, Any]] | None,
    *,
    subject_id: str,
    claim_id: str,
) -> ReviewDecision | None:
    """Última decisão para o par (subject, claim); None se não houver."""
    if not decisions:
        return None
    latest: ReviewDecision | None = None
    for raw in decisions:
        item = ReviewDecision.from_raw(raw) if not isinstance(raw, ReviewDecision) else raw
        if item.subject_id == subject_id and item.claim_id == claim_id:
            latest = item
    return latest


def decision_matches_evidence(
    decision: ReviewDecision,
    *,
    spec_version: str,
    claim: Claim | dict[str, Any] | None,
    link: ClaimLink | dict[str, Any] | None = None,
) -> bool:
    """True se a decisão ainda cobre a evidência/spec atuais."""
    if decision.reviewed_spec_version != str(spec_version):
        return False
    current_fp = fingerprint_for_claim(claim)
    if not decision.reviewed_claim_fingerprint or (
        decision.reviewed_claim_fingerprint != current_fp
    ):
        return False
    if link is None:
        return True
    _claim_id, method, score = _link_fields(link)
    if decision.reviewed_link_method != method:
        return False
    if decision.reviewed_link_score is not None and score is not None:
        if float(decision.reviewed_link_score) != float(score):
            return False
    return True
