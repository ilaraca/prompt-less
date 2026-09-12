"""Constrói CanonicalSpec a partir de UI/regras/claims/engenharia."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from src.domain.claim import Claim, ClaimOrigin
from src.domain.source_ref import SourceRef
from src.domain.spec import (
    AcceptanceCriterion,
    CanonicalSpec,
    OpenQuestion,
    Operation,
    Requirement,
    SpecError,
)


def _claims_from_dicts(raw: list[dict[str, Any]]) -> list[Claim]:
    out: list[Claim] = []
    for c in raw:
        sources = [
            SourceRef(
                document=s.get("document") or "unknown",
                section=s.get("section"),
                start_line=s.get("start_line"),
                end_line=s.get("end_line"),
                content_hash=s.get("content_hash"),
            )
            for s in (c.get("sources") or [])
        ]
        origin = c.get("origin") or "declared"
        try:
            origin_e = ClaimOrigin(origin)
        except ValueError:
            origin_e = ClaimOrigin.INFERRED
        out.append(
            Claim(
                id=str(c.get("id") or f"CLM-{len(out)+1:04d}"),
                text=str(c.get("text") or ""),
                origin=origin_e,
                confidence=float(c.get("confidence") or 0.5),
                sources=sources,
                service_id=c.get("service_id"),
                requires_review=bool(c.get("requires_review")),
                chunk_id=c.get("chunk_id"),
            )
        )
    return out


def _match_claim_ids(text: str, claims: list[Claim]) -> list[str]:
    blob = text.lower()
    matched: list[str] = []
    for c in claims:
        tokens = [t for t in re.split(r"\W+", c.text.lower()) if len(t) > 3][:6]
        if tokens and sum(1 for t in tokens if t in blob) >= max(1, len(tokens) // 2):
            matched.append(c.id)
    return matched


def build_canonical_spec(
    *,
    ui: dict[str, Any],
    regras: dict[str, Any],
    engenharia: dict[str, Any] | None = None,
    claims: list[dict[str, Any]] | None = None,
    servico: dict[str, Any] | None = None,
) -> CanonicalSpec:
    eng = engenharia or {}
    svc = servico or {}
    claim_objs = _claims_from_dicts(claims or [])
    service_id = str(svc.get("id") or "default")
    service_name = svc.get("nome")
    repos = {"all": list(svc.get("repos") or [])} if svc.get("repos") else {}

    requirements: list[Requirement] = []
    acceptance: list[AcceptanceCriterion] = []
    errors: list[SpecError] = []
    open_questions: list[OpenQuestion] = []

    # Ambiguity: mesmo trigger com status distintos
    by_trigger: dict[str, set[int]] = defaultdict(set)
    for b in regras.get("bloqueios") or []:
        if not isinstance(b, dict):
            continue
        trigger = str(b.get("trigger") or "").strip().lower()
        try:
            status = int(b.get("status"))
        except (TypeError, ValueError):
            continue
        if trigger:
            by_trigger[trigger].add(status)

    qn = 1
    for trigger, statuses in by_trigger.items():
        if len(statuses) > 1:
            sorted_s = sorted(statuses)
            open_questions.append(
                OpenQuestion(
                    id=f"Q-{qn:03d}",
                    text=f"Trigger '{trigger}' declara HTTP {sorted_s} — qual status prevalece?",
                    blocking=True,
                    source_claims=[],
                )
            )
            qn += 1

    for i, b in enumerate(regras.get("bloqueios") or [], start=1):
        if not isinstance(b, dict):
            continue
        trigger = str(b.get("trigger") or f"bloqueio-{i}")
        status = b.get("status")
        try:
            status_i = int(status)
        except (TypeError, ValueError):
            status_i = 422
        rf_id = f"RF-{i:03d}"
        ac_id = f"AC-{i:03d}"
        err_id = f"ERR-{i:03d}"
        text = f"Validar: {trigger} → HTTP {status_i}"
        src = _match_claim_ids(f"{trigger} {status_i}", claim_objs)
        if not src:
            synth = Claim(
                id=f"CLM-SYN-{i:03d}",
                text=text,
                origin=ClaimOrigin.DECLARED,
                confidence=1.0,
                sources=[SourceRef(document="regras.yaml", section=f"bloqueios[{i-1}]")],
            )
            claim_objs.append(synth)
            src = [synth.id]
        requirements.append(
            Requirement(id=rf_id, text=text, source_claims=src, status="draft")
        )
        acceptance.append(
            AcceptanceCriterion(
                id=ac_id,
                requirement_id=rf_id,
                given="condição de bloqueio",
                when=trigger,
                then=f"retornar HTTP {status_i}",
                source_claims=src,
            )
        )
        errors.append(
            SpecError(
                id=err_id,
                trigger=trigger,
                status=status_i,
                code=b.get("code"),
                source_claims=src,
            )
        )

    # happy path / decisões → RF extras
    base = len(requirements)
    for j, d in enumerate(regras.get("decisoes") or [], start=1):
        i = base + j
        rf_id = f"RF-{i:03d}"
        if isinstance(d, dict):
            text = f"Decisão: quando {d.get('quando')} → então {d.get('entao')}"
            when = str(d.get("quando") or "fluxo")
            then = str(d.get("entao") or "sucesso")
        else:
            text = f"Decisão: {d}"
            when = str(d)
            then = "sucesso"
        src = _match_claim_ids(text, claim_objs)
        if not src:
            synth = Claim(
                id=f"CLM-SYN-D{j:03d}",
                text=text,
                origin=ClaimOrigin.DECLARED,
                confidence=1.0,
                sources=[SourceRef(document="regras.yaml", section=f"decisoes[{j-1}]")],
            )
            claim_objs.append(synth)
            src = [synth.id]
        requirements.append(Requirement(id=rf_id, text=text, source_claims=src))
        acceptance.append(
            AcceptanceCriterion(
                id=f"AC-{i:03d}",
                requirement_id=rf_id,
                given="pré-condições satisfeitas",
                when=when,
                then=then,
                source_claims=src,
            )
        )

    if not requirements:
        requirements.append(
            Requirement(
                id="RF-001",
                text="Permitir submissão com dados válidos (HTTP 200)",
                source_claims=[c.id for c in claim_objs[:1]],
            )
        )
        acceptance.append(
            AcceptanceCriterion(
                id="AC-001",
                requirement_id="RF-001",
                given="dados válidos",
                when="submeter",
                then="sucesso 200",
                source_claims=[c.id for c in claim_objs[:1]],
            )
        )

    operations: list[Operation] = []
    for i, a in enumerate(ui.get("actions") or [], start=1):
        operations.append(
            Operation(
                id=f"OP-{i:03d}",
                name=str(a.get("id") or f"action-{i}"),
                owner=service_id,
                method=a.get("method"),
                path=a.get("path"),
                success_status=200,
                error_ids=[e.id for e in errors],
            )
        )

    nfrs: list[Requirement] = []
    if eng.get("resiliencia"):
        nfrs.append(
            Requirement(
                id="NFR-R-001",
                text=f"Resiliência baseline: {eng.get('resiliencia')}",
                source_claims=[],
                status="baseline",
            )
        )
    if (eng.get("observabilidade") or {}).get("logs"):
        nfrs.append(
            Requirement(
                id="NFR-O-001",
                text="Logs estruturados com correlation_id sem PII",
                source_claims=[],
                status="baseline",
            )
        )

    return CanonicalSpec(
        version="1.0",
        service_id=service_id,
        service_name=service_name,
        repositories=repos,
        claims=claim_objs,
        requirements=requirements,
        acceptance_criteria=acceptance,
        operations=operations,
        errors=errors,
        nfrs=nfrs,
        open_questions=open_questions,
    )
