"""Constrói CanonicalSpec a partir de UI/regras/claims/engenharia."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from src.domain.chunk import content_hash
from src.domain.claim import Claim, ClaimOrigin
from src.domain.provenance import (
    MATCH_REVIEW_THRESHOLD,
    lexical_match_score,
    make_claim_id,
    parse_claim_ref,
)
from src.domain.source_ref import SourceRef
from src.domain.spec import (
    AcceptanceCriterion,
    CanonicalSpec,
    ClaimLink,
    DataSchema,
    OpenQuestion,
    Operation,
    Requirement,
    ResolvedInt,
    SchemaField,
    SpecError,
)
from src.spec.evidence import bind_code_evidence, questions_from_conflicts

_SUCCESS_STATUS_RE = re.compile(r"\b(2\d{2})\b")


def _schema_id(name: str, suffix: str) -> str:
    """ID PascalCase determinístico a partir do nome da ação do IR."""
    parts = [p for p in re.split(r"[^0-9A-Za-z]+", str(name or "")) if p]
    base = "".join(p[:1].upper() + p[1:] for p in parts) or "Operacao"
    return f"{base}{suffix}"


def _schema_from_ui(
    op_name: str, items: list[dict[str, Any]], suffix: str
) -> DataSchema | None:
    """Campos da UI desidratada → schema do IR (tipo inferido exige revisão)."""
    fields: list[SchemaField] = []
    for item in items or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        origin = str(item.get("type_origin") or "inferred")
        fields.append(
            SchemaField(
                name=str(item["name"]),
                type=item.get("type"),
                required=bool(item.get("required")),
                origin=origin,
                requires_review=origin != "declared",
            )
        )
    if not fields:
        return None
    origin = "declared" if all(f.origin == "declared" for f in fields) else "inferred"
    return DataSchema(id=_schema_id(op_name, suffix), fields=fields, origin=origin)


def _parse_confidence(raw: Any, *, default: float) -> float:
    """Preserva 0.0 explícito; só aplica default quando ausente."""
    if raw is None:
        return default
    value = float(raw)
    if value < 0.0 or value > 1.0:
        raise ValueError(f"confidence fora de [0,1]: {value}")
    return value


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
                selected_lines=_selected_lines(s.get("selected_lines")),
                locator=s.get("locator"),
            )
            for s in (c.get("sources") or [])
        ]
        origin = c.get("origin") or "declared"
        try:
            origin_e = ClaimOrigin(origin)
        except ValueError:
            origin_e = ClaimOrigin.INFERRED
        public_id, parsed_ns = parse_claim_ref(str(c.get("id") or ""))
        out.append(
            Claim(
                id=public_id or make_claim_id(len(out) + 1),
                text=str(c.get("text") or ""),
                origin=origin_e,
                confidence=_parse_confidence(c.get("confidence"), default=0.5),
                sources=sources,
                service_id=c.get("service_id"),
                requires_review=bool(c.get("requires_review")),
                chunk_id=c.get("chunk_id"),
            )
        )
    return out


def _selected_lines(raw: Any) -> tuple[int, ...] | None:
    if not raw:
        return None
    return tuple(int(x) for x in raw)


def _match_claim_links(
    text: str, claims: list[Claim], *, context: str | None = None
) -> list[ClaimLink]:
    matched: list[ClaimLink] = []
    for c in claims:
        score = lexical_match_score(c.text, text)
        if score is None:
            continue
        matched.append(
            ClaimLink(
                claim_id=c.id,
                method="lexical",
                score=round(score, 3),
                requires_review=score < MATCH_REVIEW_THRESHOLD,
                context=context or c.service_id,
            )
        )
    return matched


def _ids_from_links(links: list[ClaimLink]) -> list[str]:
    return [link.claim_id for link in links]


def _synthetic_source(section: str, locator: str, text: str) -> SourceRef:
    return SourceRef(
        document="regras.yaml",
        section=section,
        content_hash=content_hash(text),
        locator=locator,
    )


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
            status_declared = True
        except (TypeError, ValueError):
            status_i = None
            status_declared = False
            open_questions.append(
                OpenQuestion(
                    id=f"Q-{qn:03d}",
                    text=(
                        f"Trigger '{trigger}' sem HTTP status válido "
                        f"(recebido: {status!r}) — qual status prevalece?"
                    ),
                    blocking=True,
                    source_claims=[],
                )
            )
            qn += 1

        rf_id = f"RF-{i:03d}"
        ac_id = f"AC-{i:03d}"
        err_id = f"ERR-{i:03d}"
        if status_declared:
            text = f"Validar: {trigger} → HTTP {status_i}"
            then = f"retornar HTTP {status_i}"
        else:
            text = f"Validar: {trigger} → HTTP status a confirmar"
            then = "retornar HTTP status a confirmar"
        src_links = _match_claim_links(
            f"{trigger} {status_i}", claim_objs, context=service_id
        )
        if not src_links:
            synth = Claim(
                id=make_claim_id(i, kind="SYN"),
                text=text,
                origin=ClaimOrigin.DECLARED,
                confidence=1.0,
                service_id=service_id,
                sources=[
                    _synthetic_source(
                        f"bloqueios[{i-1}]", f"$.bloqueios[{i-1}]", text
                    )
                ],
            )
            claim_objs.append(synth)
            src_links = [
                ClaimLink(
                    claim_id=synth.id,
                    method="synthetic",
                    score=1.0,
                    requires_review=False,
                    context=service_id,
                )
            ]
        src = _ids_from_links(src_links)
        requirements.append(
            Requirement(
                id=rf_id,
                text=text,
                source_claims=src,
                status="draft",
                claim_links=src_links,
            )
        )
        acceptance.append(
            AcceptanceCriterion(
                id=ac_id,
                requirement_id=rf_id,
                given="condição de bloqueio",
                when=trigger,
                then=then,
                source_claims=src,
                claim_links=src_links,
            )
        )
        if status_declared and status_i is not None:
            errors.append(
                SpecError(
                    id=err_id,
                    trigger=trigger,
                    status=status_i,
                    code=b.get("code"),
                    source_claims=src,
                    claim_links=src_links,
                )
            )

    # happy path / decisões → RF extras
    success_evidence: dict[int, list[str]] = {}
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
        src_links = _match_claim_links(text, claim_objs, context=service_id)
        if not src_links:
            synth = Claim(
                id=make_claim_id(j, kind="SYND"),
                text=text,
                origin=ClaimOrigin.DECLARED,
                confidence=1.0,
                service_id=service_id,
                sources=[
                    _synthetic_source(
                        f"decisoes[{j-1}]", f"$.decisoes[{j-1}]", text
                    )
                ],
            )
            claim_objs.append(synth)
            src_links = [
                ClaimLink(
                    claim_id=synth.id,
                    method="synthetic",
                    score=1.0,
                    requires_review=False,
                    context=service_id,
                )
            ]
        src = _ids_from_links(src_links)
        requirements.append(
            Requirement(id=rf_id, text=text, source_claims=src, claim_links=src_links)
        )
        acceptance.append(
            AcceptanceCriterion(
                id=f"AC-{i:03d}",
                requirement_id=rf_id,
                given="pré-condições satisfeitas",
                when=when,
                then=then,
                source_claims=src,
                claim_links=src_links,
            )
        )
        for match in _SUCCESS_STATUS_RE.finditer(then):
            success_evidence.setdefault(int(match.group(1)), []).extend(src)

    if not requirements:
        fallback_ids = [c.id for c in claim_objs[:1]]
        fallback_links = [
            ClaimLink(
                claim_id=cid,
                method="declared",
                score=1.0,
                requires_review=False,
                context=service_id,
            )
            for cid in fallback_ids
        ]
        requirements.append(
            Requirement(
                id="RF-001",
                text="Permitir submissão com dados válidos (HTTP status a confirmar)",
                source_claims=fallback_ids,
                claim_links=fallback_links,
            )
        )
        acceptance.append(
            AcceptanceCriterion(
                id="AC-001",
                requirement_id="RF-001",
                given="dados válidos",
                when="submeter",
                then="sucesso com status HTTP a confirmar",
                source_claims=fallback_ids,
                claim_links=fallback_links,
            )
        )

    actions = [a for a in (ui.get("actions") or []) if isinstance(a, dict)]
    # Sucesso só é resolvido quando a atribuição é inequívoca: uma operação e um
    # único 2xx declarado nas decisões. Fora disso permanece `unresolved`.
    unique_success = (
        next(iter(success_evidence.items()))
        if len(actions) == 1 and len(success_evidence) == 1
        else None
    )

    operations: list[Operation] = []
    for i, a in enumerate(actions, start=1):
        op_id = f"OP-{i:03d}"
        op_name = str(a.get("id") or f"action-{i}")
        method = a.get("method")
        path = a.get("path")
        if unique_success is not None:
            status_value, status_claims = unique_success
            success = ResolvedInt(
                value=status_value,
                origin="declared",
                confidence=1.0,
                requires_review=False,
                source_claims=sorted(set(status_claims)),
            )
        else:
            # Não inferir 200/201 sem evidência — default explícito exige review
            success = ResolvedInt(
                value=None, origin="default", confidence=0.4, requires_review=True
            )

        unresolved: list[str] = []
        if not method:
            unresolved.append("method")
        if not path:
            unresolved.append("path")
        if not success.resolved:
            unresolved.append("success_status")

        operations.append(
            Operation(
                id=op_id,
                name=op_name,
                owner=service_id,
                method=method,
                path=path,
                method_origin="declared" if method else None,
                path_origin="declared" if path else None,
                success_status=success,
                error_ids=[e.id for e in errors],
                request_schema=_schema_from_ui(op_name, ui.get("inputs") or [], "Request"),
                response_schema=_schema_from_ui(
                    op_name, ui.get("columns") or [], "Response"
                ),
                unresolved=unresolved,
            )
        )

    indice = None
    if isinstance(svc, dict) and "indice" in svc:
        indice = svc.get("indice") or {}
    current_state, gaps, code_evidence, conflict_texts = bind_code_evidence(
        operations=operations,
        errors=errors,
        indice=indice,
    )

    for op in operations:
        for missing in ("method", "path"):
            if missing in op.unresolved:
                open_questions.append(
                    OpenQuestion(
                        id=f"Q-{qn:03d}",
                        text=(
                            f"Operação {op.id} ({op.name}) sem {missing} declarado "
                            f"na UI — definir antes de gerar contrato"
                        ),
                        blocking=False,
                        source_claims=[],
                    )
                )
                qn += 1
    extra_qs, qn = questions_from_conflicts(conflict_texts, start=qn)
    open_questions.extend(extra_qs)

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
        current_state=current_state,
        gaps=gaps,
        code_evidence=code_evidence,
    )
