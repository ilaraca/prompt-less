"""Liga o índice de código ao Canonical Spec — heurística vs observado explícito."""
from __future__ import annotations

import re
from typing import Any

from src.domain.spec import (
    CodeEvidence,
    CurrentState,
    Gap,
    OpenQuestion,
    Operation,
    ResolvedInt,
    SpecError,
)

_ROUTE_RE = re.compile(
    r"^(?:(?P<repo>[^:]+):\s+)?(?P<method>GET|POST|PUT|DELETE|PATCH|ANY|SPEC)\s+"
    r"(?P<path>/\S*)$"
)
_OBSERVED_MIN = 0.7
_NEAR_LINES = 40


def _norm_path(path: str | None) -> str | None:
    if not path:
        return None
    cleaned = "/" + str(path).strip().lstrip("/")
    cleaned = re.sub(r"/{2,}", "/", cleaned)
    if len(cleaned) > 1:
        cleaned = cleaned.rstrip("/")
    return cleaned or "/"


def parse_route(route: str | None) -> tuple[str | None, str | None]:
    """Devolve `(METHOD, /path)` a partir de `POST /x` ou `repo: POST /x`."""
    raw = str(route or "").strip()
    if not raw:
        return None, None
    match = _ROUTE_RE.match(raw)
    if match:
        return match.group("method"), _norm_path(match.group("path"))
    if raw.startswith("/"):
        return None, _norm_path(raw)
    parts = raw.split(None, 1)
    if len(parts) == 2 and parts[1].startswith("/"):
        return parts[0].upper(), _norm_path(parts[1])
    return None, None


def evidence_from_index(indice: dict[str, Any] | None) -> list[CodeEvidence]:
    """Materializa ponteiros do índice (arquivo, símbolo, linha, rota, confiança)."""
    if not indice:
        return []
    hits: list[CodeEvidence] = []
    for raw in indice.get("evidencias") or []:
        if not isinstance(raw, dict):
            continue
        hits.append(CodeEvidence.from_raw(raw))
    if hits:
        return _sorted_hits(hits)

    # índice legado: só listas agregadas — origem heurística, sem arquivo/linha
    for route in indice.get("rotas") or []:
        method, path = parse_route(str(route))
        if not path:
            continue
        hits.append(
            CodeEvidence(
                route=f"{method or 'ANY'} {path}",
                confidence=0.4,
                origin="heuristic",
                kind="route",
            )
        )
    for status in indice.get("status") or []:
        try:
            num = int(status)
        except (TypeError, ValueError):
            continue
        hits.append(
            CodeEvidence(
                status=num,
                confidence=0.4,
                origin="heuristic",
                kind="status",
            )
        )
    for symbol in indice.get("classes") or []:
        hits.append(
            CodeEvidence(
                symbol=str(symbol),
                confidence=0.4,
                origin="heuristic",
                kind="symbol",
            )
        )
    return _sorted_hits(hits)


def _sorted_hits(hits: list[CodeEvidence]) -> list[CodeEvidence]:
    return sorted(
        hits,
        key=lambda e: (
            e.file or "",
            e.line or 0,
            e.route or "",
            e.status or 0,
            e.symbol or "",
        ),
    )


def _pointer(ev: CodeEvidence) -> str:
    parts: list[str] = []
    if ev.file:
        loc = ev.file
        if ev.line:
            loc = f"{loc}:{ev.line}"
        parts.append(f"`{loc}`")
    if ev.symbol:
        parts.append(f"`{ev.symbol}`")
    if ev.route:
        parts.append(f"`{ev.route}`")
    if ev.status is not None:
        parts.append(f"HTTP {ev.status}")
    return " ".join(parts)


def _match_routes(op: Operation, routes: list[CodeEvidence]) -> list[CodeEvidence]:
    if not routes:
        return []
    op_path = _norm_path(op.path)
    op_method = (op.method or "").strip().upper() or None
    if op_path:
        exact = [
            e
            for e in routes
            if parse_route(e.route)[1] == op_path
        ]
        if exact and op_method:
            method_hit = [
                e
                for e in exact
                if (parse_route(e.route)[0] or "ANY") in {op_method, "ANY"}
            ]
            return method_hit or exact
        if exact:
            return exact

    name = re.sub(r"[^a-z0-9]", "", (op.name or "").lower())
    by_symbol: list[CodeEvidence] = []
    if name:
        for e in routes:
            symbol = re.sub(r"[^a-z0-9]", "", (e.symbol or "").lower())
            if symbol and (name in symbol or symbol in name):
                by_symbol.append(e)
        paths = {parse_route(e.route)[1] for e in by_symbol}
        if len(paths) == 1:
            return by_symbol

    unique_paths = {parse_route(e.route)[1] for e in routes if parse_route(e.route)[1]}
    if len(unique_paths) == 1:
        return list(routes)
    return []


def _status_near(
    route_hits: list[CodeEvidence], status_hits: list[CodeEvidence]
) -> list[CodeEvidence]:
    files = {e.file for e in route_hits if e.file}
    if not files:
        return []
    same = [s for s in status_hits if s.file in files]
    lines = [e.line for e in route_hits if e.line]
    if lines:
        near = [
            s
            for s in same
            if s.line and min(abs(s.line - ln) for ln in lines) <= _NEAR_LINES
        ]
        if near:
            return near
    return same


def _refresh_unresolved(op: Operation) -> None:
    unresolved: list[str] = []
    if not op.method:
        unresolved.append("method")
    if not op.path:
        unresolved.append("path")
    status = ResolvedInt.from_raw(op.success_status)
    if not status.resolved:
        unresolved.append("success_status")
    op.unresolved = unresolved


def bind_code_evidence(
    *,
    operations: list[Operation],
    errors: list[SpecError],
    indice: dict[str, Any] | None,
) -> tuple[CurrentState, list[Gap], list[CodeEvidence], list[str]]:
    """
    Resolve method/path/status com origem `observed` quando o índice aponta
    inequívoco; conflito regra × código vira texto de pergunta aberta.
    """
    if indice is None:
        return CurrentState(applied=False), [], [], []

    hits = evidence_from_index(indice)
    routes = [e for e in hits if e.kind == "route" and e.route]
    statuses = [e for e in hits if e.kind == "status" and e.status is not None]
    symbols = [e for e in hits if e.kind == "symbol" and e.symbol]
    state = CurrentState(
        applied=True,
        routes=routes[:40],
        statuses=statuses[:40],
        symbols=symbols[:20],
    )
    gaps: list[Gap] = []
    questions: list[str] = []
    gn = 1

    def _gap(**kwargs: Any) -> None:
        nonlocal gn
        gaps.append(Gap(id=f"GAP-{gn:03d}", **kwargs))
        gn += 1

    for op in operations:
        matched = _match_routes(op, routes)
        observed_methods = []
        observed_paths = []
        for ev in matched:
            method, path = parse_route(ev.route)
            if path:
                observed_paths.append((path, ev))
            if method and method != "ANY":
                observed_methods.append((method, ev))

        unique_paths = {p for p, _ in observed_paths}
        unique_methods = {m for m, _ in observed_methods}

        if not op.path and len(unique_paths) == 1:
            path, ev = observed_paths[0]
            if ev.origin == "observed" and ev.confidence >= _OBSERVED_MIN:
                op.path = path
                op.path_origin = "observed"
        elif op.path and unique_paths and _norm_path(op.path) not in unique_paths:
            ev = observed_paths[0][1]
            observed = sorted(unique_paths)[0]
            _gap(
                kind="conflict",
                text=(
                    f"Operação {op.id}: path declarado `{op.path}` diverge do "
                    f"código `{observed}`"
                ),
                origin=ev.origin,
                evidence=[ev],
                related_operation=op.id,
                declared=op.path,
                observed=observed,
            )
            questions.append(
                f"Operação {op.id} ({op.name}): regra declara path `{op.path}` "
                f"mas o código observa `{observed}`"
                + (f" em {_pointer(ev)}" if _pointer(ev) else "")
                + " — qual prevalece?"
            )

        if not op.method and len(unique_methods) == 1:
            method, ev = observed_methods[0]
            if ev.origin == "observed" and ev.confidence >= _OBSERVED_MIN:
                op.method = method
                op.method_origin = "observed"
        elif op.method and unique_methods:
            declared = op.method.strip().upper()
            if declared not in unique_methods:
                ev = observed_methods[0][1]
                observed = sorted(unique_methods)[0]
                _gap(
                    kind="conflict",
                    text=(
                        f"Operação {op.id}: método declarado `{declared}` diverge "
                        f"do código `{observed}`"
                    ),
                    origin=ev.origin,
                    evidence=[ev],
                    related_operation=op.id,
                    declared=declared,
                    observed=observed,
                )
                questions.append(
                    f"Operação {op.id} ({op.name}): regra declara `{declared}` "
                    f"mas o código observa `{observed}`"
                    + (f" em {_pointer(ev)}" if _pointer(ev) else "")
                    + " — qual prevalece?"
                )

        near = [
            s
            for s in _status_near(matched, statuses)
            if s.status is not None and 200 <= s.status < 300
        ]
        observed_2xx = [
            s
            for s in near
            if s.origin == "observed" and s.confidence >= _OBSERVED_MIN
        ]
        status = ResolvedInt.from_raw(op.success_status)
        observed_status_vals = [s.status for s in observed_2xx if s.status is not None]
        if not status.resolved and len(set(observed_status_vals)) == 1:
            ev = observed_2xx[0]
            op.success_status = ResolvedInt(
                value=int(observed_status_vals[0]),
                origin="observed",
                confidence=ev.confidence,
                requires_review=False,
            )
        elif (
            status.resolved
            and observed_status_vals
            and status.value not in set(observed_status_vals)
        ):
            ev = observed_2xx[0]
            observed = str(sorted(observed_status_vals)[0])
            _gap(
                kind="conflict",
                text=(
                    f"Operação {op.id}: sucesso declarado HTTP {status.value} "
                    f"diverge do código HTTP {observed}"
                ),
                origin=ev.origin,
                evidence=[ev],
                related_operation=op.id,
                declared=str(status.value),
                observed=observed,
            )
            questions.append(
                f"Operação {op.id} ({op.name}): regra declara HTTP {status.value} "
                f"mas o código observa HTTP {observed}"
                + (f" em {_pointer(ev)}" if _pointer(ev) else "")
                + " — qual status de sucesso prevalece?"
            )
        _refresh_unresolved(op)

    observed_status_nums = {int(s.status) for s in statuses if s.status is not None}
    declared_status_nums = {int(e.status) for e in errors}
    for op in operations:
        resolved = op.resolved_success_status()
        if resolved is not None:
            declared_status_nums.add(int(resolved))

    for err in errors:
        if int(err.status) in observed_status_nums:
            continue
        related = [
            s for s in statuses if s.status is not None and int(s.status) == int(err.status)
        ]
        origin = "heuristic"
        evidence = related[:3]
        if not evidence:
            # sem ponteiro de arquivo: marca heurística explícita
            evidence = [
                CodeEvidence(
                    status=int(err.status),
                    confidence=0.4,
                    origin="heuristic",
                    kind="status",
                )
            ]
        _gap(
            kind="missing_in_code",
            text=(
                f"Regra `{err.id}` declara HTTP {err.status} ({err.trigger}) "
                "e o código não evidencia esse status"
            ),
            origin=origin,
            evidence=evidence,
            source_claims=list(err.source_claims),
            declared=str(err.status),
        )

    extras = sorted(
        observed_status_nums - declared_status_nums - {200, 201, 204}
    )
    for num in extras:
        related = [s for s in statuses if s.status == num]
        ev = related[0] if related else CodeEvidence(
            status=num, confidence=0.4, origin="heuristic", kind="status"
        )
        _gap(
            kind="extra_in_code",
            text=(
                f"HTTP {num} aparece no código sem regra correspondente no spec"
            ),
            origin=ev.origin,
            evidence=[ev],
            observed=str(num),
        )

    return state, gaps, hits, questions


def questions_from_conflicts(
    texts: list[str], *, start: int
) -> tuple[list[OpenQuestion], int]:
    questions: list[OpenQuestion] = []
    qn = start
    for text in texts:
        questions.append(
            OpenQuestion(id=f"Q-{qn:03d}", text=text, blocking=False, source_claims=[])
        )
        qn += 1
    return questions, qn
