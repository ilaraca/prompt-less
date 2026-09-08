"""
De/para repos → marcadores nos docs.

Lê `inputs/mapa-servicos.yaml` (gerado por `scripts/scan-repos.sh`), pontua cada
chunk dos documentos por keywords e injeta `[[service:<id>]]` onde houver match.

  python -m src.marcar                      # dry-run + relatório
  python -m src.marcar --apply              # escreve marcadores em .txt/.md (com .bak)
  python -m src.marcar --apply --convert-binarios   # .docx/.doc → <stem>.marcado.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.doc_compress import chunk_text  # noqa: E402
from src.docs_ingest import load_documents  # noqa: E402
from src.servicos import MARKER_RE, load_mapa, resolve_service_id  # noqa: E402

INPUTS = ROOT / "inputs"
TEXT_EXTS = {".txt", ".md"}
BINARY_EXTS = {".docx", ".doc"}

# "## 2. Ofertas", "2. Ofertas", "2.1) Ofertas", "SEÇÃO 3 - Pagamentos"
HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s+\S|\d+(?:\.\d+)*[.)]?\s+\S|(?:SE[CÇ][AÃ]O|CAP[IÍ]TULO|ANEXO)\b)",
    re.I,
)

# marcador gerado por este módulo (linha isolada) — removido antes de remarcar
GENERATED_MARKER_RE = re.compile(r"^[ \t]*\[\[service:[^\]]+\]\][ \t]*\n?", re.M)


def strip_generated_markers(text: str) -> str:
    """Torna a remarcação idempotente: descarta marcadores de execuções anteriores."""
    return GENERATED_MARKER_RE.sub("", text)


def segment(text: str, *, lines_per_chunk: int = 40) -> list[str]:
    """Corta por títulos quando o doc tem estrutura; senão cai em blocos fixos."""
    lines = text.splitlines()
    heads = [i for i, ln in enumerate(lines) if HEADING_RE.match(ln)]
    if len(heads) < 2:
        return chunk_text(text, lines_per_chunk=lines_per_chunk)

    bounds = heads if heads[0] == 0 else [0] + heads
    segments: list[str] = []
    for pos, start in enumerate(bounds):
        end = bounds[pos + 1] if pos + 1 < len(bounds) else len(lines)
        bloco = "\n".join(lines[start:end]).strip("\n")
        if not bloco.strip():
            continue
        # seção gigante volta a ser fatiada para não estourar o chunk
        if bloco.count("\n") + 1 > lines_per_chunk * 3:
            segments.extend(chunk_text(bloco, lines_per_chunk=lines_per_chunk))
        else:
            segments.append(bloco)
    return segments


def _score(chunk: str, keywords: list[str]) -> int:
    low = chunk.lower()
    total = 0
    for kw in keywords:
        k = str(kw).lower().strip()
        if len(k) < 3:
            continue
        total += low.count(k)
    return total


def classify_chunks(
    text: str,
    mapa: dict[str, Any],
    *,
    lines_per_chunk: int = 40,
    min_score: int = 1,
) -> list[dict[str, Any]]:
    """Retorna [{index, service_id|None, score, has_marker, text}] por chunk."""
    servicos = mapa.get("servicos") or {}
    out: list[dict[str, Any]] = []
    for i, chunk in enumerate(segment(text, lines_per_chunk=lines_per_chunk)):
        best_id, best_score = None, 0
        for sid, meta in servicos.items():
            sc = _score(chunk, list(meta.get("keywords") or []))
            if sc > best_score:
                best_id, best_score = sid, sc
        out.append(
            {
                "index": i,
                "service_id": best_id if best_score >= min_score else None,
                "score": best_score,
                "has_marker": bool(MARKER_RE.search(chunk)),
                "text": chunk,
            }
        )
    return out


def annotate(chunks: list[dict[str, Any]], mapa: dict[str, Any]) -> str:
    """Reconstrói o texto inserindo marcadores só quando o serviço muda."""
    parts: list[str] = []
    current: str | None = None
    for c in chunks:
        if c["has_marker"]:
            # marcador manual manda: adota o serviço dele e não duplica
            m = MARKER_RE.search(c["text"])
            bruto = next((g for g in (m.groups() if m else ()) if g), "")
            current = resolve_service_id(mapa, bruto) if bruto else None
            parts.append(c["text"])
            continue
        sid = c["service_id"]
        if sid and sid != current:
            parts.append(f"[[service:{sid}]]")
            current = sid
        parts.append(c["text"])
    return "\n".join(parts) + "\n"


def process(
    *,
    apply_changes: bool = False,
    convert_binarios: bool = False,
    lines_per_chunk: int = 40,
    min_score: int = 1,
    inputs_dir: Path | None = None,
    mapa_path: Path | None = None,
) -> dict[str, Any]:
    inputs = inputs_dir or INPUTS
    mapa = load_mapa(mapa_path)
    if not mapa:
        raise SystemExit(
            "erro: inputs/mapa-servicos.yaml ausente ou vazio.\n"
            "      gere com: ./scripts/scan-repos.sh --workspace ~/dev/repos"
        )

    docs = load_documents(inputs)
    if not docs:
        raise SystemExit(f"erro: nenhum documento em {inputs} (.txt/.md/.docx/.doc)")

    report: list[dict[str, Any]] = []
    written: list[str] = []
    skipped: list[dict[str, str]] = []

    for doc in docs:
        path = Path(doc["path"])
        base = strip_generated_markers(doc.get("text") or "")
        chunks = classify_chunks(
            base,
            mapa,
            lines_per_chunk=lines_per_chunk,
            min_score=min_score,
        )
        por_servico: dict[str, int] = {}
        for c in chunks:
            key = c["service_id"] or "_unassigned"
            por_servico[key] = por_servico.get(key, 0) + 1

        report.append(
            {
                "doc": doc["name"],
                "ext": doc["ext"],
                "chunks": len(chunks),
                "por_servico": por_servico,
                "de_para": [
                    {
                        "secao": (c["text"].strip().splitlines() or [""])[0][:80],
                        "servico": c["service_id"] or "_unassigned",
                        "score": c["score"],
                    }
                    for c in chunks
                ],
                "marcadores_existentes": sum(1 for c in chunks if c["has_marker"]),
                "marcadores_a_inserir": sum(
                    1 for c in chunks if c["service_id"] and not c["has_marker"]
                ),
            }
        )

        if not apply_changes:
            continue

        novo = annotate(chunks, mapa)
        ext = doc["ext"]

        if ext in TEXT_EXTS:
            backup = path.with_suffix(path.suffix + ".bak")
            if not backup.exists():
                backup.write_text(doc.get("text") or "", encoding="utf-8")
            path.write_text(novo, encoding="utf-8")
            written.append(str(path))
        elif ext in BINARY_EXTS:
            if not convert_binarios:
                skipped.append(
                    {
                        "doc": doc["name"],
                        "motivo": "binário — use --convert-binarios para gerar .marcado.md",
                    }
                )
                continue
            destino = path.with_name(f"{path.stem}.marcado.md")
            destino.write_text(novo, encoding="utf-8")
            # evita ingestão duplicada do original
            path.rename(path.with_suffix(path.suffix + ".bak"))
            written.append(str(destino))
        else:
            skipped.append({"doc": doc["name"], "motivo": f"extensão {ext} não suportada"})

    resumo = {
        "servicos": list((mapa.get("servicos") or {}).keys()),
        "docs": report,
        "aplicado": apply_changes,
        "arquivos_escritos": written,
        "ignorados": skipped,
    }

    out_path = ROOT / "outputs" / "marcadores_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")
    resumo["report"] = str(out_path)
    return resumo


def main() -> None:
    p = argparse.ArgumentParser(description="De/para repos → marcadores nos docs")
    p.add_argument("--apply", action="store_true", help="escreve os marcadores nos arquivos")
    p.add_argument(
        "--convert-binarios",
        action="store_true",
        help=".docx/.doc → <stem>.marcado.md (original vira .bak)",
    )
    p.add_argument("--lines-per-chunk", type=int, default=40)
    p.add_argument("--min-score", type=int, default=1)
    p.add_argument("--inputs", metavar="DIR", help="diretório de docs (default: inputs/)")
    p.add_argument("--mapa", metavar="FILE", help="mapa (default: inputs/mapa-servicos.yaml)")
    args = p.parse_args()

    resumo = process(
        apply_changes=args.apply,
        convert_binarios=args.convert_binarios,
        lines_per_chunk=args.lines_per_chunk,
        min_score=args.min_score,
        inputs_dir=Path(args.inputs) if args.inputs else None,
        mapa_path=Path(args.mapa) if args.mapa else None,
    )
    print(json.dumps(resumo, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
