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
    Gap,
    OpenQuestion,
    Operation,
    Requirement,
    ResolvedInt,
    SchemaField,
    SpecError,
)
from src.repos.servicos import fold, resolve_service_id
from src.preprocess.engenharia import (
    dehydrate_engenharia,
    detect_nfr_signals,
    layers_from_repos,
    nfr_gaps_from_code,
    select_nfrs,
    validate_engenharia_schema,
)
from src.spec.evidence import bind_code_evidence, questions_from_conflicts

_SUCCESS_STATUS_RE = re.compile(r"\b(2\d{2})\b")
_CONTEXT_SENTINELS = {"default", "_unassigned"}


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


def _keyword_score(text: str, keywords: list[str] | None) -> int:
    """Contagem de keywords (fold) — mesma heurística do mapa de serviços."""
    low = fold(text)
    score = 0
    for kw in keywords or []:
        key = fold(kw)
        if key:
            score += low.count(key)
    return score


def _action_blob(action: dict[str, Any]) -> str:
    return " ".join(
        str(action.get(k) or "")
        for k in ("id", "name", "method", "path", "owner", "service_id", "service")
    )


def _explicit_owner(action: dict[str, Any], mapa: dict[str, Any] | None) -> str | None:
    raw = action.get("owner") or action.get("service_id") or action.get("service")
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if mapa:
        return resolve_service_id(mapa, text) or text
    return text


def _resolve_operation_owner(
    action: dict[str, Any],
    *,
    mapa: dict[str, Any] | None,
    fallback_service_id: str,
) -> str | None:
    """Dono da ação por evidência — nunca herda o contexto só porque a spec é dele."""
    explicit = _explicit_owner(action, mapa)
    if explicit:
        return explicit

    servicos = (mapa or {}).get("servicos") or {}
    if servicos:
        blob = _action_blob(action)
        scored = {
            sid: _keyword_score(blob, list((meta or {}).get("keywords") or []))
            for sid, meta in servicos.items()
        }
        best = max(scored.values()) if scored else 0
        winners = [sid for sid, score in scored.items() if score == best and score > 0]
        if len(winners) == 1:
            return winners[0]
        if best <= 0 and len(servicos) == 1:
            return next(iter(servicos))
        return None

    if fallback_service_id and fallback_service_id not in _CONTEXT_SENTINELS:
        return fallback_service_id
    if fallback_service_id == "default":
        return "default"
    return None


def _slice_context_id(service_id: str) -> str | None:
    return None if service_id in _CONTEXT_SENTINELS else service_id


def _error_blob(err: SpecError) -> str:
    return f"{err.trigger} {err.code or ''}"


def _score_error_for_op(
    err: SpecError, op: Operation, mapa: dict[str, Any] | None
) -> int:
    blob = _error_blob(err)
    score = _keyword_score(blob, [op.name or "", op.path or "", op.id])
    servicos = (mapa or {}).get("servicos") or {}
    if op.owner and op.owner in servicos:
        score += _keyword_score(
            blob, list((servicos[op.owner] or {}).get("keywords") or [])
        )
    return score


def _assign_error_ids(
    operations: list[Operation],
    errors: list[SpecError],
    mapa: dict[str, Any] | None,
) -> None:
    """Ancora ERR-* na operação dona; empate ou zero vira órfão (não copia)."""
    contract_ops = [op for op in operations if op.owner]
    for op in operations:
        op.error_ids = []
    if not errors or not operations:
        return
    for err in errors:
        scored = [(_score_error_for_op(err, op, mapa), op) for op in operations]
        best = max((s for s, _ in scored), default=0)
        winners = [op for s, op in scored if s == best and s > 0]
        if len(winners) == 1:
            winners[0].error_ids.append(err.id)
        elif len(contract_ops) == 1:
            # um único serviço/op no spec: não é cópia entre contextos
            contract_ops[0].error_ids.append(err.id)


def _error_service_candidates(
    err: SpecError, mapa: dict[str, Any] | None
) -> list[str]:
    servicos = (mapa or {}).get("servicos") or {}
    if not servicos:
        return []
    blob = _error_blob(err)
    scored = {
        sid: _keyword_score(blob, list((meta or {}).get("keywords") or []))
        for sid, meta in servicos.items()
    }
    best = max(scored.values()) if scored else 0
    if best <= 0:
        return []
    return [sid for sid, score in scored.items() if score == best]


def _keep_errors_for_spec(
    errors: list[SpecError],
    operations: list[Operation],
    *,
    context_id: str | None,
    mapa: dict[str, Any] | None,
) -> tuple[list[SpecError], list[SpecError]]:
    """Mantém erros ancorados + órfãos verdadeiros; não copia erro de outro serviço."""
    referenced = {eid for op in operations for eid in op.error_ids}
    kept: list[SpecError] = []
    orphans: list[SpecError] = []
    for err in errors:
        if err.id in referenced:
            kept.append(err)
            continue
        owners = _error_service_candidates(err, mapa)
        if context_id and len(owners) == 1 and owners[0] != context_id:
            continue
        kept.append(err)
        orphans.append(err)
    return kept, orphans


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


def _declared_section_link(
    claims: list[Claim],
    *,
    section: str,
    locator: str,
    context: str | None = None,
) -> ClaimLink | None:
    """Vínculo declarado: claim estruturado da mesma seção de regras.yaml.

    Não exige revisão — a evidência é a própria fonte estruturada, não um
    match lexical fraco sobre o texto `block status=…`.
    """
    for c in claims:
        for src in c.sources or []:
            src_section = getattr(src, "section", None) or (
                src.get("section") if isinstance(src, dict) else None
            )
            src_locator = getattr(src, "locator", None) or (
                src.get("locator") if isinstance(src, dict) else None
            )
            if src_section == section or src_locator == locator:
                return ClaimLink(
                    claim_id=c.id,
                    method="declared",
                    score=1.0,
                    requires_review=False,
                    context=context or c.service_id,
                )
    return None


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
    mapa: dict[str, Any] | None = None,
) -> CanonicalSpec:
    eng = dehydrate_engenharia(engenharia or {})
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
        section = f"bloqueios[{i-1}]"
        locator = f"$.bloqueios[{i-1}]"
        declared = _declared_section_link(
            claim_objs, section=section, locator=locator, context=service_id
        )
        if declared is not None:
            src_links = [declared]
        else:
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
                    _synthetic_source(section, locator, text)
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
    context_id = _slice_context_id(service_id)

    owned_actions: list[tuple[int, dict[str, Any], str | None]] = []
    for i, a in enumerate(actions, start=1):
        owner = _resolve_operation_owner(
            a, mapa=mapa, fallback_service_id=service_id
        )
        if context_id and owner and owner != context_id:
            continue
        owned_actions.append((i, a, owner))

    # Sucesso só é resolvido quando a atribuição é inequívoca: uma operação
    # *com dono* e um único 2xx declarado nas decisões. Fora disso `unresolved`.
    owned_count = sum(1 for _, _, owner in owned_actions if owner)
    unique_success = (
        next(iter(success_evidence.items()))
        if owned_count == 1 and len(success_evidence) == 1
        else None
    )

    operations: list[Operation] = []
    for i, a, owner in owned_actions:
        op_id = f"OP-{i:03d}"
        op_name = str(a.get("id") or f"action-{i}")
        method = a.get("method")
        path = a.get("path")
        if unique_success is not None and owner:
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
        if not owner:
            unresolved.append("owner")
        if not method:
            unresolved.append("method")
        if not path:
            unresolved.append("path")
        if not success.resolved:
            unresolved.append("success_status")

        if "owner" in unresolved:
            open_questions.append(
                OpenQuestion(
                    id=f"Q-{qn:03d}",
                    text=(
                        f"Operação {op_id} ({op_name}) sem dono atribuível "
                        "no mapa/UI — não emitir como contrato resolvido"
                    ),
                    blocking=False,
                    source_claims=[],
                )
            )
            qn += 1

        operations.append(
            Operation(
                id=op_id,
                name=op_name,
                owner=owner,
                method=method,
                path=path,
                method_origin="declared" if method else None,
                path_origin="declared" if path else None,
                success_status=success,
                error_ids=[],
                request_schema=_schema_from_ui(op_name, ui.get("inputs") or [], "Request"),
                response_schema=_schema_from_ui(
                    op_name, ui.get("columns") or [], "Response"
                ),
                unresolved=unresolved,
            )
        )

    _assign_error_ids(operations, errors, mapa)
    errors, orphan_errors = _keep_errors_for_spec(
        errors, operations, context_id=context_id, mapa=mapa
    )
    for err in orphan_errors:
        open_questions.append(
            OpenQuestion(
                id=f"Q-{qn:03d}",
                text=(
                    f"Erro {err.id} ({err.trigger}) sem operação dona — "
                    "permanece unresolved, não copiado para outro serviço"
                ),
                blocking=False,
                source_claims=list(err.source_claims),
            )
        )
        qn += 1

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

    repo_list: list[str] = []
    for vals in (repos or {}).values():
        repo_list.extend(vals or [])
    layers = layers_from_repos(repo_list)
    observed_nfr = detect_nfr_signals(indice if isinstance(indice, dict) else None)
    selected = select_nfrs(eng, layers=layers, observed=observed_nfr)
    # anexa seleção no eng para renderers (mesmo IDs que o IR)
    if isinstance(eng, dict):
        eng["_selected_nfrs"] = selected
    nfrs: list[Requirement] = [
        Requirement(
            id=n.id,
            text=n.text,
            source_claims=[],
            status=n.origin,
            origin=n.origin,
            category=n.category,
            layers=list(n.layers),
        )
        for n in selected
    ]
    schema_errs = validate_engenharia_schema(eng)
    for msg in schema_errs:
        open_questions.append(
            OpenQuestion(
                id=f"Q-{qn:03d}",
                text=f"engenharia.yaml inválido: {msg}",
                blocking=False,
                source_claims=[],
            )
        )
        qn += 1

    nfr_gap_dicts = nfr_gaps_from_code(
        selected,
        indice_applied=bool(indice is not None),
        start=len(gaps) + 1,
    )
    for raw_gap in nfr_gap_dicts:
        gaps.append(
            Gap(
                id=str(raw_gap["id"]),
                kind=str(raw_gap["kind"]),
                text=str(raw_gap["text"]),
                origin=str(raw_gap.get("origin") or "heuristic"),
                declared=raw_gap.get("declared"),
                observed=raw_gap.get("observed"),
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
