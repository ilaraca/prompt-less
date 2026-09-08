"""Split de docs por microsserviço: marcadores no texto + keywords do mapa."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAPA = ROOT / "inputs" / "mapa-servicos.yaml"

# ## Serviço: ms-cliente  |  [[service:ms-cliente]]  |  <!-- service: ms-cliente -->
MARKER_RE = re.compile(
    r"(?:"
    r"^#{1,6}\s*Servi[cç]o\s*:\s*([^\n#]+)"
    r"|\[\[service:\s*([^\]]+)\]\]"
    r"|<!--\s*service:\s*([^>]+?)-->"
    r")",
    re.I | re.M,
)


def load_mapa(path: Path | None = None) -> dict[str, Any] | None:
    p = path or DEFAULT_MAPA
    if not p.exists():
        return None
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not data.get("servicos"):
        return None
    return data


def list_service_ids(mapa: dict[str, Any]) -> list[str]:
    return list((mapa.get("servicos") or {}).keys())


def resolve_service_id(mapa: dict[str, Any], raw: str) -> str | None:
    """Resolve id canônico a partir de marcador ou alias."""
    key = raw.strip().lower().replace(" ", "-")
    servicos = mapa.get("servicos") or {}
    if key in servicos:
        return key
    for sid, meta in servicos.items():
        aliases = [str(a).lower() for a in (meta.get("aliases") or [])]
        if key == sid.lower() or key in aliases or key == str(meta.get("nome", "")).lower():
            return sid
        # nome slug
        nome_slug = re.sub(r"[^a-z0-9]+", "-", str(meta.get("nome", "")).lower()).strip("-")
        if key == nome_slug:
            return sid
    return None


def get_service(mapa: dict[str, Any], service_id: str) -> dict[str, Any]:
    meta = dict((mapa.get("servicos") or {}).get(service_id) or {})
    meta["id"] = service_id
    meta.setdefault("nome", service_id)
    meta.setdefault("repos", [])
    meta.setdefault("keywords", [])
    return meta


def split_by_markers(text: str, mapa: dict[str, Any]) -> dict[str, str]:
    """Parte o texto em seções por marcador explícito. Chave '' = preâmbulo sem marcador."""
    buckets: dict[str, list[str]] = {"": []}
    current = ""
    last = 0
    for m in MARKER_RE.finditer(text):
        # texto antes do marcador vai para o bucket atual
        buckets.setdefault(current, [])
        buckets[current].append(text[last : m.start()])
        raw = (m.group(1) or m.group(2) or m.group(3) or "").strip()
        sid = resolve_service_id(mapa, raw) or raw.lower().replace(" ", "-")
        current = sid
        buckets.setdefault(current, [])
        last = m.end()
    buckets.setdefault(current, [])
    buckets[current].append(text[last:])
    return {k: "".join(v).strip() for k, v in buckets.items() if "".join(v).strip()}


def _keyword_score(text: str, keywords: list[str]) -> int:
    low = text.lower()
    score = 0
    for kw in keywords:
        k = str(kw).lower()
        if not k:
            continue
        # conta ocorrências simples
        score += low.count(k)
    return score


def assign_unmarked_text(
    text: str,
    mapa: dict[str, Any],
    *,
    lines_per_chunk: int = 40,
) -> dict[str, str]:
    """Classifica texto sem marcador por keywords (chunk → melhor serviço)."""
    from src.doc_compress import chunk_text

    servicos = mapa.get("servicos") or {}
    if not text.strip() or not servicos:
        return {}

    buckets: dict[str, list[str]] = {sid: [] for sid in servicos}
    unassigned: list[str] = []

    for chunk in chunk_text(text, lines_per_chunk=lines_per_chunk):
        best_id = None
        best_score = 0
        for sid, meta in servicos.items():
            sc = _keyword_score(chunk, list(meta.get("keywords") or []))
            if sc > best_score:
                best_score = sc
                best_id = sid
        if best_id and best_score > 0:
            buckets[best_id].append(chunk)
        else:
            unassigned.append(chunk)

    strategy = ((mapa.get("unassigned") or {}).get("strategy") or "bucket").lower()
    out = {sid: "\n".join(parts).strip() for sid, parts in buckets.items() if parts}
    if unassigned:
        joined = "\n".join(unassigned).strip()
        if strategy == "drop":
            pass
        else:
            out["_unassigned"] = joined
    return out


def partition_documents(
    documents: list[dict[str, Any]],
    mapa: dict[str, Any],
    *,
    lines_per_chunk: int = 40,
) -> dict[str, dict[str, Any]]:
    """
    Agrupa docs em baldes por serviço.
    Retorna: { service_id: { "text": str, "meta": service_meta, "sources": [names] } }
    """
    combined: dict[str, list[str]] = {}
    sources: dict[str, list[str]] = {}

    for doc in documents:
        text = doc.get("text") or ""
        name = doc.get("name") or "doc"
        if not text.strip():
            continue

        marked = split_by_markers(text, mapa)
        # preâmbulo sem marcador ('') → keywords
        preamble = marked.pop("", "")
        for sid, body in marked.items():
            # se sid não está no mapa, tentar resolve; senão _unassigned ou manter id
            canon = resolve_service_id(mapa, sid) or (
                sid if sid in (mapa.get("servicos") or {}) else "_unassigned"
            )
            if canon == "_unassigned" and sid not in (mapa.get("servicos") or {}):
                # marcador desconhecido: keyword no body
                for kid, kbody in assign_unmarked_text(
                    body, mapa, lines_per_chunk=lines_per_chunk
                ).items():
                    combined.setdefault(kid, []).append(kbody)
                    sources.setdefault(kid, []).append(name)
            else:
                combined.setdefault(canon, []).append(body)
                sources.setdefault(canon, []).append(name)

        if preamble:
            for kid, kbody in assign_unmarked_text(
                preamble, mapa, lines_per_chunk=lines_per_chunk
            ).items():
                combined.setdefault(kid, []).append(kbody)
                sources.setdefault(kid, []).append(name)

        # doc inteiro sem nenhum marcador: marked só tinha '' 
        if not marked and not preamble:
            for kid, kbody in assign_unmarked_text(
                text, mapa, lines_per_chunk=lines_per_chunk
            ).items():
                combined.setdefault(kid, []).append(kbody)
                sources.setdefault(kid, []).append(name)

    strategy = ((mapa.get("unassigned") or {}).get("strategy") or "bucket").lower()
    result: dict[str, dict[str, Any]] = {}
    for sid, parts in combined.items():
        if sid == "_unassigned" and strategy == "drop":
            continue
        text = "\n\n".join(p for p in parts if p).strip()
        if not text:
            continue
        if sid == "_unassigned":
            meta = {
                "id": "_unassigned",
                "nome": "Não classificado",
                "repos": [],
                "keywords": [],
            }
        else:
            meta = get_service(mapa, sid)
        result[sid] = {
            "text": text,
            "meta": meta,
            "sources": sorted(set(sources.get(sid) or [])),
            "est_tokens_raw": max(1, len(text) // 4),
            "lines": text.count("\n") + 1,
        }
    return result


def docs_for_service(
    documents: list[dict[str, Any]],
    mapa: dict[str, Any],
    service_id: str,
    *,
    lines_per_chunk: int = 40,
) -> list[dict[str, Any]]:
    """Filtra documents[] para um serviço (formato compatível com compress_documents)."""
    parts = partition_documents(documents, mapa, lines_per_chunk=lines_per_chunk)
    bucket = parts.get(service_id)
    if not bucket:
        return []
    return [
        {
            "name": f"{service_id}:" + "+".join(bucket["sources"][:3]),
            "ext": ".txt",
            "lines": bucket["lines"],
            "chars": len(bucket["text"]),
            "est_tokens_raw": bucket["est_tokens_raw"],
            "text": bucket["text"],
        }
    ]
