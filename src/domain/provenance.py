"""Identidade, namespace e merge de claims (opera em dicts)."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

MATCH_REVIEW_THRESHOLD = 0.6
_NS_RE = re.compile(r"[^A-Za-z0-9_-]+")


def claim_namespace(value: str | None) -> str:
    """Namespace estável por contexto/serviço — nunca por run_id."""
    raw = str(value or "default").strip() or "default"
    cleaned = _NS_RE.sub("_", raw).strip("_-")
    return (cleaned[:64] or "default")


def make_claim_id(namespace: str, seq: int, *, kind: str = "") -> str:
    ns = claim_namespace(namespace)
    if kind:
        return f"CLM-{ns}-{kind}-{seq:04d}"
    return f"CLM-{ns}-{seq:04d}"


def claim_fingerprint(claim: dict[str, Any]) -> str:
    """Identidade completa: texto, origin, service_id, chunk_id, sources."""
    payload = {
        "chunk_id": claim.get("chunk_id"),
        "origin": str(claim.get("origin") or ""),
        "service_id": claim.get("service_id"),
        "sources": claim.get("sources") or [],
        "text": str(claim.get("text") or ""),
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def merge_claims(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Dedup por fingerprint. Colisão de id com fingerprint distinto: rename
    fail-safe, preservando `local_id` e `context`.
    """
    by_fp: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    used_ids: set[str] = set()

    for raw in claims:
        if not isinstance(raw, dict):
            continue
        fp = claim_fingerprint(raw)
        if fp in by_fp:
            continue
        claim = dict(raw)
        ns = claim_namespace(
            claim.get("context") or claim.get("service_id") or "default"
        )
        local_id = str(claim.get("id") or claim.get("local_id") or "")
        if not local_id:
            local_id = make_claim_id(ns, len(used_ids) + 1)
        claim.setdefault("local_id", local_id)
        claim.setdefault("context", ns)
        cid = str(claim.get("id") or local_id)
        if cid in used_ids:
            n = 2
            renamed = f"{cid}--{n}"
            while renamed in used_ids:
                n += 1
                renamed = f"{cid}--{n}"
            claim["id"] = renamed
        else:
            claim["id"] = cid
        used_ids.add(str(claim["id"]))
        by_fp[fp] = claim
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
