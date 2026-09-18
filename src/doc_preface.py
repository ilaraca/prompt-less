"""
Prefácio operacional + índice de salto para specs longas.

Substitui Grep linear (O(n) por consulta, repetido) por:

  1. um passe O(n) que indexa o arquivo;
  2. lookup O(1) por id de slice / âncora;
  3. lookup O(k) por termo via índice invertido (k = postings do termo);
  4. vizinhança O(V+E) no DAG de tickets (V típico ~20).

O prefácio cabe no início do markdown (tabela de roteamento). O corpo permanece
no disco. Agentes leem o prefácio e depois `Read(offset, limit)` — não concatenam
o arquivo nem mandam 3000 linhas ao modelo.

  python -m src.doc_preface docs/propostas-melhoria-limites-atuais.md
  python -m src.doc_preface FILE.md --apply
  python -m src.doc_preface FILE.md --lookup "história gaps"
  python -m src.doc_preface FILE.md --show 22-code-evidence-spec
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.domain.chunk import content_hash
from src.servicos import fold

ROOT = Path(__file__).resolve().parents[1]

PREFACE_START = "<!-- PREFACE:START -->"
PREFACE_END = "<!-- PREFACE:END -->"

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
TICKET_ID_RE = re.compile(r"^(\d+[a-z]?-[a-z0-9-]+)(?:\s|$)")
TICKET_REF_RE = re.compile(r"`(\d+[a-z]?(?:-[a-z0-9-]+)?)`|(\d+[a-z]?-[a-z0-9-]+)")
KANBAN_RE = re.compile(r"\*\*Kanban:\*\*\s*([^\n*]+)", re.I)
BLOCKED_RE = re.compile(r"\*\*Blocked by:\*\*\s*([^\n]+)", re.I)
BLOQUEADO_RE = re.compile(
    r"(?:bloquead[oa]s?|bloquear)\s+por\s+(.+?)(?:\.|$)",
    re.I,
)
GENERIC_HEADINGS = {
    "aceite",
    "comportamento entregue",
    "metrica de sucesso",
    "metricas de sucesso",
}
GLOSSARY_CELL_RE = re.compile(r"^\|\s*\*?\*?([A-Za-z0-9][A-Za-z0-9_ /.-]{1,40})\*?\*?\s*\|")
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,}", re.I)

STOPWORDS = {
    "para", "como", "este", "esta", "isso", "aquele", "aquela", "sobre", "entre",
    "quando", "onde", "porque", "pode", "podem", "deve", "devem", "cada", "todo",
    "todos", "todas", "pelo", "pela", "pelos", "pelas", "mais", "menos", "muito",
    "muita", "pouco", "depois", "antes", "tambem", "apenas", "ainda", "assim",
    "sem", "com", "nao", "uma", "umas", "uns", "das", "dos", "que", "qual",
    "quais", "ser", "sao", "foi", "era", "ter", "tem", "the", "and", "for",
    "from", "with", "this", "that", "are", "was", "not", "but", "into", "via",
    "por", "seu", "sua", "seus", "suas", "ele", "ela", "eles", "deles", "dela",
    "nos", "nas", "num", "numa", "ao", "aos", "do", "da", "de", "em", "um",
    "no", "na", "os", "as", "se", "ou", "e", "a", "o", "to", "of", "in", "on",
    "atual", "atuais", "proposta", "propostas", "documento", "secao", "arquivo",
    "adicionar", "entregue",
}

INTENT_LEXICON: dict[str, list[str]] = {
    "historia": [
        "historia", "bdd", "aceite", "gap", "estado", "nfr", "requisito",
        "evidencia", "codigo", "canonical", "spec",
    ],
    "prd": [
        "prd", "requisito", "handoff", "sdd", "rf", "canonical", "spec", "nfr",
    ],
    "openapi": [
        "openapi", "schema", "path", "status", "contrato", "ir", "canonical", "mermaid",
    ],
    "mermaid": [
        "mermaid", "sequencia", "fluxo", "openapi", "ir",
    ],
    "executor": [
        "devin", "executor", "verify", "repair", "sandbox", "aprovacao", "evidencia",
    ],
    "planning": [
        "grafo", "onda", "frontier", "paralelo", "blocked", "dependencia", "planejamento",
    ],
    "runtime": [
        "run_id", "runtime", "storage", "atomico", "retomada", "stages", "redis",
    ],
    "provenance": [
        "claim", "provenance", "source", "rastreabilidade", "tamper", "hash",
    ],
    "evals": [
        "eval", "candidate", "baseline", "regressao", "improve", "rollback",
    ],
}

MAX_PREFACE_TERMS = 40
MAX_ROUTE_HITS = 6


@dataclass
class Section:
    id: str
    heading: str
    level: int
    start_line: int
    end_line: int
    text: str
    ticket_id: str | None = None
    kanban: str | None = None
    blocked_by_raw: list[str] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)
    dependents: list[str] = field(default_factory=list)

    @property
    def est_tokens(self) -> int:
        return max(1, len(self.text) // 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "heading": self.heading,
            "level": self.level,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "est_tokens": self.est_tokens,
            "ticket_id": self.ticket_id,
            "kanban": self.kanban,
            "blocked_by": list(self.blocked_by),
            "dependents": list(self.dependents),
        }


@dataclass
class DocIndex:
    path: str
    body_hash: str
    sections: list[Section]
    tickets: dict[str, Section]
    inverted: dict[str, list[str]]
    idf: dict[str, float]
    adjacency: dict[str, list[str]]
    frontier: list[str]
    waves: list[list[str]]
    routes: dict[str, list[dict[str, Any]]]
    glossary: list[str]
    preface_lines: tuple[int, int] | None = None

    def by_id(self) -> dict[str, Section]:
        return {s.id: s for s in self.sections}


def strip_preface(text: str) -> str:
    start = text.find(PREFACE_START)
    end = text.find(PREFACE_END)
    if start == -1 or end == -1 or end < start:
        return text
    end_at = end + len(PREFACE_END)
    before = text[:start].rstrip()
    after = text[end_at:].lstrip("\n")
    if before and after:
        return before + "\n\n" + after
    return (before + "\n" + after).strip("\n") + ("\n" if text.endswith("\n") else "")


def split_title(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    if not lines or not re.match(r"^#\s+[^#]", lines[0]):
        return "", text
    return lines[0], "\n".join(lines[1:]).lstrip("\n")


def _slug(heading: str, used: set[str]) -> str:
    ticket = TICKET_ID_RE.match(heading.strip())
    if ticket:
        base = ticket.group(1)
    else:
        folded = fold(heading)
        base = re.sub(r"[^a-z0-9]+", "-", folded).strip("-")[:80] or "secao"
    slug = base
    n = 2
    while slug in used:
        slug = f"{base}-{n}"
        n += 1
    used.add(slug)
    return slug


def _extract_ticket_refs(blob: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for m in TICKET_REF_RE.finditer(blob):
        raw = (m.group(1) or m.group(2) or "").strip()
        if not raw or raw in seen:
            continue
        seen.add(raw)
        found.append(raw)
    return found


def _first_lines(text: str, n: int = 20) -> str:
    return "\n".join(text.splitlines()[:n])


def parse_sections(body: str) -> list[Section]:
    lines = body.splitlines()
    heads: list[tuple[int, int, str]] = []
    for i, ln in enumerate(lines):
        m = HEADING_RE.match(ln)
        if m:
            heads.append((i, len(m.group(1)), m.group(2).strip()))
    if not heads:
        text = body.strip("\n")
        if not text.strip():
            return []
        return [
            Section(
                id="corpo",
                heading="(sem títulos)",
                level=1,
                start_line=1,
                end_line=max(1, len(lines)),
                text=text,
            )
        ]

    used: set[str] = set()
    sections: list[Section] = []
    if heads[0][0] > 0:
        pre = "\n".join(lines[: heads[0][0]]).strip("\n")
        if pre.strip():
            sections.append(
                Section(
                    id="preambulo",
                    heading="(preâmbulo)",
                    level=1,
                    start_line=1,
                    end_line=heads[0][0],
                    text=pre,
                )
            )

    for pos, (start, level, heading) in enumerate(heads):
        end = len(lines)
        for j in range(pos + 1, len(heads)):
            if heads[j][1] <= level:
                end = heads[j][0]
                break
        block_lines = lines[start:end]
        text = "\n".join(block_lines).strip("\n")
        ticket_m = TICKET_ID_RE.match(heading)
        ticket_id = ticket_m.group(1) if ticket_m else None
        kanban = None
        blocked_raw: list[str] = []
        if ticket_id:
            head_blob = _first_lines(text, 25)
            kanban_m = KANBAN_RE.search(head_blob)
            if kanban_m:
                kanban = kanban_m.group(1).strip()
            blocked_blob = ""
            blocked_m = BLOCKED_RE.search(head_blob)
            if blocked_m:
                blocked_blob = blocked_m.group(1)
            else:
                bloq = BLOQUEADO_RE.search(head_blob)
                if bloq:
                    blocked_blob = bloq.group(1)
            if blocked_blob:
                blocked_raw = _extract_ticket_refs(blocked_blob)
        sections.append(
            Section(
                id=_slug(heading, used),
                heading=heading,
                level=level,
                start_line=start + 1,
                end_line=max(start + 1, end),
                text=text,
                ticket_id=ticket_id,
                kanban=kanban,
                blocked_by_raw=blocked_raw,
            )
        )
    return sections


def extract_glossary(sections: list[Section]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for sec in sections:
        head = fold(sec.heading) + " " + fold(sec.id)
        if not any(k in head for k in ("gloss", "sigla", "termo")):
            continue
        for ln in sec.text.splitlines():
            stripped = ln.strip()
            if stripped.startswith("| ---") or stripped.startswith("|---") or "---|" in stripped[:12]:
                continue
            m = GLOSSARY_CELL_RE.match(ln)
            if not m:
                continue
            term = m.group(1).strip().strip("*")
            if fold(term) in {"sigla", "termo", "significado", "neste projeto", "em portugues"}:
                continue
            if len(term) > 40:
                continue
            key = fold(term)
            if key in seen or len(key) < 2:
                continue
            seen.add(key)
            terms.append(term)
    return terms


def resolve_ticket_ref(raw: str, tickets: dict[str, Section]) -> str | None:
    raw = raw.strip().strip("`")
    raw = re.sub(r"\s*\(.*\)\s*$", "", raw).strip()
    if raw in tickets:
        return raw
    m = re.fullmatch(r"(\d+[a-z]?)", raw)
    if not m:
        return None
    prefix = m.group(1)
    exact = [tid for tid in tickets if tid == prefix or tid.startswith(prefix + "-")]
    if len(exact) == 1:
        return exact[0]
    # 12 casa 12a/12b/12-ci — não adivinha
    return None


def _done_ref(raw: str) -> bool:
    return bool(re.search(r"\(\s*done\s*\)", raw, re.I))


def link_graph(sections: list[Section]) -> dict[str, Section]:
    tickets = {s.ticket_id: s for s in sections if s.ticket_id}
    for sec in tickets.values():
        resolved: list[str] = []
        for raw in sec.blocked_by_raw:
            tid = resolve_ticket_ref(raw, tickets)
            if tid and tid not in resolved:
                resolved.append(tid)
        sec.blocked_by = resolved
        sec.dependents = []
    for sec in tickets.values():
        for dep in sec.blocked_by:
            parent = tickets.get(dep)
            if parent and sec.ticket_id and sec.ticket_id not in parent.dependents:
                parent.dependents.append(sec.ticket_id)
    return tickets


def topological_waves(tickets: dict[str, Section]) -> tuple[list[str], list[list[str]]]:
    ids = sorted(tickets)
    indegree = {tid: 0 for tid in ids}
    children: dict[str, list[str]] = defaultdict(list)
    for tid in ids:
        for dep in tickets[tid].blocked_by:
            if dep not in tickets:
                continue
            indegree[tid] += 1
            children[dep].append(tid)

    ready = deque(sorted(tid for tid, d in indegree.items() if d == 0))
    waves: list[list[str]] = []
    seen = 0
    while ready:
        wave = list(ready)
        waves.append(wave)
        ready.clear()
        for tid in wave:
            seen += 1
            for child in children[tid]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
        ready = deque(sorted(ready))
    if seen != len(ids):
        # ciclo: frontier = nós sem blocker interno; waves parciais + resto
        leftover = sorted(tid for tid in ids if tid not in {x for w in waves for x in w})
        if leftover:
            waves.append(leftover)
    frontier = list(waves[0]) if waves else []
    return frontier, waves


def tokenize(text: str) -> list[str]:
    folded = fold(text)
    out: list[str] = []
    for tok in TOKEN_RE.findall(folded):
        if tok in STOPWORDS:
            continue
        if len(tok) >= 4:
            out.append(tok)
            continue
        if re.fullmatch(r"\d+[a-z]?(?:-[\w-]+)?", tok):
            out.append(tok)
            continue
        if 2 <= len(tok) <= 5:
            out.append(tok)
    return out


def build_inverted(
    sections: list[Section],
) -> tuple[dict[str, list[str]], dict[str, float]]:
    tf: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    df: dict[str, int] = defaultdict(int)
    for sec in sections:
        terms = set()
        extra = [sec.heading]
        if sec.ticket_id:
            extra.append(sec.ticket_id)
        blob = " ".join(extra) + "\n" + sec.text
        for tok in tokenize(blob):
            tf[sec.id][tok] += 1
            terms.add(tok)
        for tok in terms:
            df[tok] += 1

    n = max(1, len(sections))
    idf = {tok: 1.0 + math.log(n / max(1, d)) for tok, d in df.items()}
    inverted: dict[str, list[str]] = {}
    for tok, d in df.items():
        postings = sorted(tf.keys(), key=lambda sid: -tf[sid][tok] * idf[tok])
        inverted[tok] = [sid for sid in postings if tf[sid][tok]]
    return inverted, idf


def lookup(
    index: DocIndex,
    query: str,
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    q = query.strip()
    if not q:
        return []
    by_id = index.by_id()
    folded_q = fold(q)

    exact: list[dict[str, Any]] = []
    if q in index.tickets:
        sec = index.tickets[q]
        exact.append(_hit(sec, 1000.0, ["id"]))
    elif folded_q in {fold(s.id) for s in index.sections}:
        for sec in index.sections:
            if fold(sec.id) == folded_q:
                exact.append(_hit(sec, 900.0, ["id"]))
                break

    tf_query = tokenize(q)
    scores: dict[str, float] = defaultdict(float)
    evidence: dict[str, list[str]] = defaultdict(list)
    for tok in tf_query:
        postings = index.inverted.get(tok)
        if not postings:
            # prefixo curto de sigla (ir, prd, nfr)
            for term, ids in index.inverted.items():
                if term.startswith(tok) or tok.startswith(term):
                    postings = ids
                    tok = term
                    break
        if not postings:
            continue
        weight = index.idf.get(tok, 1.0)
        for sid in postings:
            scores[sid] += weight
            if tok not in evidence[sid]:
                evidence[sid].append(tok)

    for sid in list(scores):
        boost = by_id.get(sid)
        if boost is None:
            continue
        if boost.ticket_id:
            scores[sid] *= 1.6
        heading_toks = set(tokenize(boost.heading))
        for tok in tf_query:
            if tok in heading_toks:
                scores[sid] += 2.0 * index.idf.get(tok, 1.0)

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    hits = list(exact)
    seen = {h["id"] for h in hits}
    skipped_generic: list[tuple[str, float]] = []
    for sid, score in ranked:
        if sid in seen:
            continue
        ranked_sec = by_id.get(sid)
        if ranked_sec is None:
            continue
        if fold(ranked_sec.heading) in GENERIC_HEADINGS:
            skipped_generic.append((sid, score))
            continue
        hits.append(_hit(ranked_sec, round(score, 3), evidence[sid][:6]))
        seen.add(sid)
        if len(hits) >= limit:
            break
    if len(hits) < limit:
        for sid, score in skipped_generic:
            sec = by_id[sid]
            hits.append(_hit(sec, round(score, 3), evidence[sid][:6]))
            if len(hits) >= limit:
                break
    return hits[:limit]


def _hit(sec: Section, score: float, terms: list[str]) -> dict[str, Any]:
    return {
        "id": sec.id,
        "heading": sec.heading,
        "start_line": sec.start_line,
        "end_line": sec.end_line,
        "limit": sec.end_line - sec.start_line + 1,
        "est_tokens": sec.est_tokens,
        "ticket_id": sec.ticket_id,
        "kanban": sec.kanban,
        "score": score,
        "terms": terms,
        "read": f"Read(offset={sec.start_line}, limit={sec.end_line - sec.start_line + 1})",
    }


def build_routes(index: DocIndex) -> dict[str, list[dict[str, Any]]]:
    routes: dict[str, list[dict[str, Any]]] = {}
    for intent, words in INTENT_LEXICON.items():
        hits = lookup(index, " ".join(words), limit=MAX_ROUTE_HITS)
        routes[intent] = [
            {
                "id": h["id"],
                "heading": h["heading"],
                "start_line": h["start_line"],
                "end_line": h["end_line"],
                "limit": h["limit"],
            }
            for h in hits
        ]
    return routes


def shift_lines(sections: list[Section], offset: int) -> None:
    """offset = linhas do arquivo antes da linha 1 do body (0-based count)."""
    if offset <= 0:
        return
    for sec in sections:
        sec.start_line += offset
        sec.end_line += offset


def distinctive_terms(index: DocIndex, limit: int = MAX_PREFACE_TERMS) -> list[tuple[str, list[str]]]:
    n = max(1, len(index.sections))
    section_ids = {s.id for s in index.sections}
    glossary_folded = {fold(g) for g in index.glossary}
    rows: list[tuple[int, float, str, list[str]]] = []
    for term, ids in index.inverted.items():
        if term in STOPWORDS or term in section_ids:
            continue
        if term not in index.tickets and term not in glossary_folded and len(term) < 5:
            continue
        df = len(ids)
        if df < 1 or df > max(3, n // 2):
            continue
        # hapax só entra se for glossário ou id de slice
        if df == 1 and term not in index.tickets and term not in glossary_folded:
            continue
        rank_group = 0 if term in glossary_folded else (1 if term in index.tickets else 2)
        rows.append((rank_group, -index.idf.get(term, 1.0) * df, term, ids[:4]))
    rows.sort()
    return [(term, ids) for _, _, term, ids in rows[:limit]]


def render_preface(index: DocIndex, *, sidecar_name: str) -> str:
    lines: list[str] = [
        "## Prefácio operacional — mapa de salto (não Grep o corpo)",
        "",
        "Gerado por `python -m src.doc_preface`. Este bloco é a **tabela de roteamento**.",
        "Indexar o arquivo custa **O(n)** uma vez. Lookup de slice/termo é **O(1)** + **O(k)**",
        "na lista invertida. O DAG de tickets usa lista de adjacência; a frontier sai de",
        "Kahn em **O(V+E)** (V típico < 30). Não concatene o corpo. Não mande o bruto ao modelo.",
        "",
        "### Protocolo para agentes",
        "",
        "1. Leia **somente este prefácio** (ou o sidecar YAML).",
        "2. Identifique o artefato (`historia` | `prd` | `openapi` | `ticket:<id>`).",
        "3. Abra **apenas** as âncoras com `Read(path, offset, limit)` — `offset` = linha inicial.",
        "4. `Grep` só se o termo **não** estiver no índice invertido nem no sidecar.",
        "5. Para um slice, carregue também a vizinhança (`blocked_by` + `dependents`), não o arquivo.",
        "",
        f"Sidecar: `{sidecar_name}`",
        f"Hash do corpo (sem prefácio): `{index.body_hash}`",
        "",
        "### Roteamento por artefato",
        "",
        "| Artefato | Âncoras (id · linhas) |",
        "|---|---|",
    ]
    for intent, hits in index.routes.items():
        if not hits:
            cell = "—"
        else:
            cell = "; ".join(
                f"`{h['id']}` {h['start_line']}–{h['end_line']}" for h in hits[:4]
            )
        lines.append(f"| `{intent}` | {cell} |")

    lines += [
        "",
        "### Catálogo de slices (O(1) por id)",
        "",
        "| ID | Kanban | Blocked by | Linhas | `Read` |",
        "|---|---|---|---|---|",
    ]
    for tid in sorted(index.tickets, key=lambda t: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", t)]):
        sec = index.tickets[tid]
        if sec.blocked_by:
            blocked = ", ".join(f"`{b}`" for b in sec.blocked_by)
        elif sec.blocked_by_raw:
            blocked = ", ".join(f"`{b}`" for b in sec.blocked_by_raw)
        else:
            blocked = "—"
        kanban = sec.kanban or "—"
        read = f"offset={sec.start_line} limit={sec.end_line - sec.start_line + 1}"
        lines.append(
            f"| `{tid}` | {kanban} | {blocked} | {sec.start_line}–{sec.end_line} | `{read}` |"
        )

    frontier = ", ".join(f"`{t}`" for t in index.frontier) or "—"
    wave_txt = " → ".join(
        "[" + ", ".join(f"`{t}`" for t in wave) + "]" for wave in index.waves
    )
    lines += [
        "",
        "### Frontier e ondas (DAG)",
        "",
        f"- **Frontier** (indegree 0 no grafo indexado): {frontier}",
        f"- **Ondas topológicas:** {wave_txt or '—'}",
        "",
        "### Adjacência (ticket → dependentes)",
        "",
    ]
    any_adj = False
    for src in sorted(index.adjacency):
        dsts = index.adjacency[src]
        if not dsts:
            continue
        any_adj = True
        lines.append(f"- `{src}` → " + ", ".join(f"`{d}`" for d in dsts))
    if not any_adj:
        lines.append("- (sem arestas internas)")

    lines += [
        "",
        "### Índice invertido (termo → âncoras)",
        "",
        "| Termo | Âncoras |",
        "|---|---|",
    ]
    for term, ids in distinctive_terms(index):
        lines.append(f"| `{term}` | " + ", ".join(f"`{i}`" for i in ids) + " |")

    level2 = [s for s in index.sections if s.level == 2]
    if level2:
        lines += [
            "",
            "### Âncoras de seção (`##`)",
            "",
            "| Seção | Linhas | Tokens est. |",
            "|---|---|---|",
        ]
        for sec in level2:
            lines.append(
                f"| {sec.heading} | {sec.start_line}–{sec.end_line} | ~{sec.est_tokens} |"
            )

    if index.glossary:
        shown = ", ".join(f"`{g}`" for g in index.glossary[:24])
        extra = f" (+{len(index.glossary) - 24})" if len(index.glossary) > 24 else ""
        lines += ["", "### Glossário (termos extraídos)", "", shown + extra]

    lines += [
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


def compose(title: str, inner: str, body: str) -> str:
    parts: list[str] = []
    if title:
        parts.append(title.strip() + "\n")
    parts.append(f"\n{PREFACE_START}\n{inner.rstrip()}\n{PREFACE_END}\n\n")
    parts.append(body.lstrip("\n"))
    text = "".join(parts)
    if not text.endswith("\n"):
        text += "\n"
    return text


def body_start_line(composed: str) -> int:
    lines = composed.splitlines()
    end_idx = next((i for i, ln in enumerate(lines) if ln.strip() == PREFACE_END), None)
    if end_idx is None:
        return 1
    idx = end_idx + 1
    while idx < len(lines) and lines[idx].strip() == "":
        idx += 1
    return idx + 1  # 1-based


def preface_span(composed: str) -> tuple[int, int]:
    lines = composed.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip() == PREFACE_START)
    end = next(i for i, ln in enumerate(lines) if ln.strip() == PREFACE_END)
    return start + 1, end + 1


def build_index_from_body(
    body: str,
    *,
    path: str,
    body_hash: str,
    line_offset: int = 0,
) -> DocIndex:
    sections = parse_sections(body)
    if line_offset:
        shift_lines(sections, line_offset)
    tickets = link_graph(sections)
    frontier, waves = topological_waves(tickets)
    inverted, idf = build_inverted(sections)
    adjacency = {tid: list(tickets[tid].dependents) for tid in tickets}
    index = DocIndex(
        path=path,
        body_hash=body_hash,
        sections=sections,
        tickets=tickets,
        inverted=inverted,
        idf=idf,
        adjacency=adjacency,
        frontier=frontier,
        waves=waves,
        routes={},
        glossary=extract_glossary(sections),
    )
    index.routes = build_routes(index)
    return index


def build_document(text: str, path: Path) -> tuple[str, DocIndex]:
    core = strip_preface(text)
    title, body = split_title(core)
    body_hash = content_hash(core)
    index = build_index_from_body(body, path=str(path), body_hash=body_hash, line_offset=0)
    sidecar_name = index_path(path).name
    inner = render_preface(index, sidecar_name=sidecar_name)
    composed = ""
    for _ in range(4):
        composed = compose(title, inner, body)
        offset = body_start_line(composed) - 1
        index = build_index_from_body(
            body, path=str(path), body_hash=body_hash, line_offset=offset
        )
        new_inner = render_preface(index, sidecar_name=sidecar_name)
        if new_inner == inner:
            break
        inner = new_inner
    composed = compose(title, inner, body)
    index.preface_lines = preface_span(composed)
    return composed, index


def index_path(md_path: Path) -> Path:
    return md_path.with_name(md_path.stem + ".index.yaml")


def sidecar_payload(index: DocIndex) -> dict[str, Any]:
    return {
        "document": index.path,
        "generated_by": "src.doc_preface",
        "protocol": "read_preface_then_Read_ranges",
        "complexity": {
            "index": "O(n)",
            "lookup_id": "O(1)",
            "lookup_term": "O(k) postings",
            "frontier": "O(V+E) Kahn",
        },
        "body_hash": index.body_hash,
        "preface_lines": list(index.preface_lines or []),
        "frontier": list(index.frontier),
        "waves": [list(w) for w in index.waves],
        "adjacency": {k: list(v) for k, v in index.adjacency.items()},
        "routes": index.routes,
        "glossary": list(index.glossary),
        "tickets": {tid: index.tickets[tid].to_dict() for tid in sorted(index.tickets)},
        "sections": [
            s.to_dict()
            for s in index.sections
            if s.ticket_id or s.level <= 2 or fold(s.heading) in {"glossario", "siglas"} or "gloss" in fold(s.heading)
        ],
        "term_index": {term: ids for term, ids in distinctive_terms(index, limit=80)},
    }


def apply_to_file(path: Path) -> tuple[DocIndex, Path]:
    original = path.read_text(encoding="utf-8")
    composed, index = build_document(original, path)
    path.write_text(composed, encoding="utf-8")
    side = index_path(path)
    side.write_text(
        yaml.safe_dump(sidecar_payload(index), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return index, side


def neighborhood(index: DocIndex, ticket_id: str) -> dict[str, Any]:
    sec = index.tickets.get(ticket_id)
    if not sec:
        return {"error": f"ticket não encontrado: {ticket_id}"}
    nodes = [ticket_id, *sec.blocked_by, *sec.dependents]
    hits = []
    for tid in nodes:
        node = index.tickets.get(tid)
        if node:
            hits.append(_hit(node, 1.0 if tid == ticket_id else 0.5, ["graph"]))
    return {
        "ticket": ticket_id,
        "blocked_by": list(sec.blocked_by),
        "dependents": list(sec.dependents),
        "read": hits,
    }


def summarize(index: DocIndex) -> dict[str, Any]:
    return {
        "document": index.path,
        "sections": len(index.sections),
        "tickets": len(index.tickets),
        "terms": len(index.inverted),
        "frontier": list(index.frontier),
        "waves": len(index.waves),
        "preface_lines": list(index.preface_lines or []),
        "sidecar": str(index_path(Path(index.path))),
        "protocol": "Read prefácio → Read(offset, limit) nas âncoras. Grep só se o termo faltar no índice.",
    }


def main() -> None:
    p = argparse.ArgumentParser(
        description="Prefácio operacional + índice de salto (substitui Grep em specs longas)"
    )
    p.add_argument("file", type=Path, help="markdown da spec")
    p.add_argument("--apply", action="store_true", help="reescreve o arquivo com prefácio + sidecar YAML")
    p.add_argument("--lookup", metavar="QUERY", help="termos ou id de slice → âncoras (JSON)")
    p.add_argument("--show", metavar="TICKET_ID", help="vizinhança do slice no DAG")
    p.add_argument("--out-index", type=Path, help="destino do sidecar (default: <stem>.index.yaml)")
    args = p.parse_args()

    path = args.file.expanduser()
    if not path.is_file():
        raise SystemExit(f"erro: arquivo inexistente: {path}")

    text = path.read_text(encoding="utf-8")
    if args.apply:
        index, side = apply_to_file(path)
        if args.out_index:
            payload = sidecar_payload(index)
            args.out_index.write_text(
                yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            side = args.out_index
        print(json.dumps({**summarize(index), "sidecar": str(side)}, ensure_ascii=False, indent=2))
        return

    composed, index = build_document(text, path)
    index.preface_lines = preface_span(composed)

    if args.lookup is not None:
        print(json.dumps({"query": args.lookup, "hits": lookup(index, args.lookup)}, ensure_ascii=False, indent=2))
        return
    if args.show:
        print(json.dumps(neighborhood(index, args.show), ensure_ascii=False, indent=2))
        return
    print(json.dumps(summarize(index), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
