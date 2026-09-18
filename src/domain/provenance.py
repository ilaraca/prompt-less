"""Identidade e merge de claims (opera em dicts).

Um claim tem um único identificador público: `id` (`CLM-0001`, `CLM-R001`,
`CLM-SYN-001`). Em mais de um contexto esse `id` pode repetir. A chave de
endereçamento é o par `(context, id)` — não existe `uid`.

`resolve_claim` é fail-closed: `id` solto com duas ocorrências não adivinha.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

MATCH_REVIEW_THRESHOLD = 0.6
_NS_RE = re.compile(r"[^A-Za-z0-9_-]+")
_NAMESPACED_ID = re.compile(
    r"^CLM-(?P<ns>[A-Za-z0-9][A-Za-z0-9_-]*?)-"
    r"(?P<rest>R\d{3}|SYN-D\d{3}|SYN-\d{3}|\d{4})$"
)
_COMPOSITE_REF = re.compile(
    r"^(?P<ctx>[A-Za-z0-9][A-Za-z0-9_-]*):(?P<id>CLM-.+)$"
)


class AmbiguousClaimRef(ValueError):
    """`id` de claim aparece em mais de um contexto e a resolução não tem contexto."""


def claim_namespace(value: str | None) -> str:
    """Namespace estável por contexto/serviço — nunca por run_id."""
    raw = str(value or "default").strip() or "default"
    cleaned = _NS_RE.sub("_", raw).strip("_-")
    return (cleaned[:64] or "default")


def make_claim_id(seq: int, *, kind: str = "") -> str:
    """Id público estável. `kind`: '' | 'R' | 'SYN' | 'SYND'."""
    if kind == "R":
        return f"CLM-R{seq:03d}"
    if kind == "SYN":
        return f"CLM-SYN-{seq:03d}"
    if kind == "SYND":
        return f"CLM-SYN-D{seq:03d}"
    return f"CLM-{seq:04d}"


def parse_claim_ref(
    value: str, *, context: str | None = None
) -> tuple[str, str | None]:
    """
    Devolve `(id público, contexto ou None)`.

    Aceita: `CLM-0001`, `ms-cliente:CLM-0001` e o formato namespaced residual
    `CLM-ms-cliente-0001`. Ids customizados (`CLM-Z`, `CLM-low-0001`) passam
    intactos.
    """
    raw = str(value or "").strip()
    if not raw:
        return "", claim_namespace(context) if context else None
    composite = _COMPOSITE_REF.match(raw)
    if composite:
        return composite.group("id"), claim_namespace(composite.group("ctx"))
    match = _NAMESPACED_ID.match(raw)
    if match:
        ns = claim_namespace(match.group("ns"))
        if ns == "default" or ns.startswith("ms-") or "-" in ns:
            return f"CLM-{match.group('rest')}", ns
    return raw, claim_namespace(context) if context else None


def stamp_claim_identity(
    claim: dict[str, Any], *, context: str | None = None
) -> dict[str, Any]:
    """Garante `id` público + `context`. Remove `uid`/`local_id` se existirem."""
    raw_id = str(claim.get("id") or claim.get("local_id") or claim.get("uid") or "")
    public, parsed_ns = parse_claim_ref(raw_id)
    ns = claim_namespace(
        parsed_ns
        or context
        or claim.get("context")
        or claim.get("service_id")
    )
    if not public:
        public = make_claim_id(1)
    claim["id"] = public
    claim["context"] = ns
    claim.pop("uid", None)
    claim.pop("local_id", None)
    return claim


def claim_key(claim: dict[str, Any] | Any) -> tuple[str, str]:
    """Chave de endereçamento: `(context, id)`."""
    if isinstance(claim, dict):
        stamped = stamp_claim_identity(dict(claim))
        return str(stamped["context"]), str(stamped["id"])
    ctx = claim_namespace(getattr(claim, "service_id", None))
    return ctx, str(getattr(claim, "id", ""))


def resolve_claim(
    claims: list[dict[str, Any]],
    ref: str,
    *,
    context: str | None = None,
) -> dict[str, Any] | None:
    """
    Resolve uma referência para no máximo um claim.

    Fail-closed: se `id` ocorrer em dois contextos e `context` não for dado,
    levanta `AmbiguousClaimRef` em vez de escolher.
    """
    public, parsed_ctx = parse_claim_ref(ref, context=context)
    want_ctx = parsed_ctx or (claim_namespace(context) if context else None)
    stamped = [stamp_claim_identity(dict(c)) for c in claims if isinstance(c, dict)]
    if want_ctx:
        hits = [c for c in stamped if c["id"] == public and c["context"] == want_ctx]
    else:
        hits = [c for c in stamped if c["id"] == public]
    if len(hits) > 1:
        ctxs = sorted({str(c["context"]) for c in hits})
        raise AmbiguousClaimRef(
            f"claim {public!r} existe em {ctxs}; informe o contexto"
        )
    return hits[0] if hits else None


def claim_fingerprint(claim: dict[str, Any]) -> str:
    """Identidade completa: context + texto, origin, service_id, chunk_id, sources.

    Carimba antes de hashear: sem `context` no payload, dois contextos com o
    mesmo `service_id` (ou nenhum) colapsavam evidência distinta.
    """
    stamped = stamp_claim_identity(dict(claim))
    payload = {
        "chunk_id": stamped.get("chunk_id"),
        "context": stamped.get("context"),
        "origin": str(stamped.get("origin") or ""),
        "service_id": stamped.get("service_id"),
        "sources": stamped.get("sources") or [],
        "text": str(stamped.get("text") or ""),
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def merge_claims(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedup por fingerprint. `id` público nunca é renomeado."""
    by_fp: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for raw in claims:
        if not isinstance(raw, dict):
            continue
        stamped = stamp_claim_identity(dict(raw))
        fp = claim_fingerprint(stamped)
        if fp in by_fp:
            continue
        by_fp[fp] = stamped
        order.append(fp)
    return [by_fp[fp] for fp in order]


def lexical_match_score(claim_text: str, target_text: str) -> float | None:
    """Score lexical; None se não houver match (menos da metade dos tokens)."""
    tokens = [t for t in re.split(r"\W+", claim_text.lower()) if len(t) > 3][:6]
    if not tokens:
        return None
    blob = target_text.lower()
    hits = sum(1 for t in tokens if t in blob)
    if hits < max(1, len(tokens) // 2):
        return None
    return hits / float(len(tokens))
