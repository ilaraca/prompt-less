"""
De/para repos → marcadores nos docs.

Pontua cada seção do documento contra o vocabulário de cada serviço e injeta
`[[service:<id>]]` na vencedora. O vocabulário vem de duas fontes:

  1. `inputs/mapa-servicos.yaml`  — keywords derivadas do nome dos repos (peso alto)
  2. `state/repo_index.json`      — termos extraídos do código real (rotas, entidades,
                                    tabelas, campos), quando `src.repo_index` já rodou

Todo termo é ponderado por IDF: o que aparece em vários serviços perde peso, o que
é exclusivo de um ganha. Sem LLM, sem embeddings — busca léxica sobre o código.

  python -m src.marcar                      # dry-run + relatório
  python -m src.marcar --explain            # tabela legível da decisão por seção
  python -m src.marcar --apply              # escreve marcadores em .txt/.md (com .bak)
  python -m src.marcar --apply --convert-binarios   # .docx/.doc → <stem>.marcado.md
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.doc_compress import chunk_text  # noqa: E402
from src.docs_ingest import load_documents  # noqa: E402
from src.repo_index import load_index, service_terms  # noqa: E402
from src.servicos import MARKER_RE, fold, load_mapa, resolve_service_id  # noqa: E402

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


PESO_KEYWORD = 3.0  # veio do nome do repo: sinal forte e curado
PESO_CODIGO = 1.0  # veio do código: sinal abundante, então vale menos por termo
MAX_OCORRENCIAS = 3  # trava para uma palavra repetida não dominar a seção


def build_vocab(
    mapa: dict[str, Any], index: dict[str, Any] | None = None
) -> dict[str, dict[str, float]]:
    """{service_id: {termo: peso}} com IDF entre serviços."""
    servicos = mapa.get("servicos") or {}
    bruto: dict[str, dict[str, float]] = {}

    for sid, meta in servicos.items():
        pesos: dict[str, float] = {}
        for kw in meta.get("keywords") or []:
            termo = fold(kw).strip().lstrip("/")
            if len(termo) >= 3:
                pesos[termo] = max(pesos.get(termo, 0.0), PESO_KEYWORD)
        for bruto_termo, freq in service_terms(index, sid).items():
            termo = fold(bruto_termo)
            if len(termo) < 4:
                continue
            # frequência no código dá um empurrão pequeno e saturado
            peso = PESO_CODIGO * (1.0 + min(1.0, freq / 50.0))
            pesos[termo] = max(pesos.get(termo, 0.0), peso)
        bruto[sid] = pesos

    total = len(bruto) or 1
    ocorre_em: Counter[str] = Counter(termo for pesos in bruto.values() for termo in pesos)
    for pesos in bruto.values():
        for termo in list(pesos):
            idf = 1.0 + math.log(total / ocorre_em[termo])
            pesos[termo] = round(pesos[termo] * idf, 3)
    return bruto


def score_section(secao: str, pesos: dict[str, float]) -> tuple[float, list[tuple[str, int]]]:
    """Pontua uma seção e devolve os termos que sustentaram a decisão."""
    low = fold(secao)
    total = 0.0
    achados: list[tuple[str, int]] = []
    for termo, peso in pesos.items():
        # casa plural/flexão simples, mas não pedaço de outra palavra
        n = len(re.findall(rf"(?<![a-z0-9]){re.escape(termo)}[a-z]{{0,3}}", low))
        if not n:
            continue
        total += peso * min(n, MAX_OCORRENCIAS)
        achados.append((termo, n))
    achados.sort(key=lambda kv: -pesos[kv[0]] * min(kv[1], MAX_OCORRENCIAS))
    return round(total, 2), achados[:5]


def classify_chunks(
    text: str,
    mapa: dict[str, Any],
    *,
    lines_per_chunk: int = 40,
    min_score: float = 2.0,
    min_margin: float = 1.3,
    min_terms: int = 2,
    index: dict[str, Any] | None = None,
    vocab: dict[str, dict[str, float]] | None = None,
) -> list[dict[str, Any]]:
    """Retorna a decisão por seção, com score, vice-colocado e evidência."""
    vocab = vocab if vocab is not None else build_vocab(mapa, index)
    out: list[dict[str, Any]] = []

    for i, chunk in enumerate(segment(text, lines_per_chunk=lines_per_chunk)):
        ranking: list[tuple[str, float, list[tuple[str, int]]]] = []
        for sid, pesos in vocab.items():
            score, achados = score_section(chunk, pesos)
            if score > 0:
                ranking.append((sid, score, achados))
        ranking.sort(key=lambda r: -r[1])

        melhor = ranking[0] if ranking else None
        vice = ranking[1] if len(ranking) > 1 else None
        sid, score, achados = (melhor or (None, 0.0, []))
        vice_score = vice[1] if vice else 0.0

        distintos = len(achados)
        repeticoes = max((n for _, n in achados), default=0)

        if not sid or score < min_score:
            decisao, motivo = None, "sem_sinal"
        elif distintos < min_terms and repeticoes < 2:
            # uma menção solta ("cpf" perdido num log) não classifica a seção
            decisao, motivo = None, "sinal_isolado"
        elif vice_score and score < vice_score * min_margin:
            # dois serviços empatados: não adivinha, deixa para revisão humana
            decisao, motivo = None, f"ambiguo_com_{vice[0]}"
        else:
            decisao, motivo = sid, "classificado"

        out.append(
            {
                "index": i,
                "service_id": decisao,
                "candidato": sid,
                "score": score,
                "vice": (vice[0] if vice else None),
                "vice_score": vice_score,
                "motivo": motivo,
                "evidencia": [{"termo": t, "ocorrencias": n} for t, n in achados],
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
    min_score: float = 2.0,
    min_margin: float = 1.3,
    min_terms: int = 2,
    inputs_dir: Path | None = None,
    mapa_path: Path | None = None,
    index_path: Path | None = None,
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

    index = load_index(index_path)
    vocab = build_vocab(mapa, index)

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
            min_margin=min_margin,
            min_terms=min_terms,
            vocab=vocab,
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
                        "motivo": c["motivo"],
                        "vice": c["vice"],
                        "vice_score": c["vice_score"],
                        "evidencia": c["evidencia"],
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
        "vocabulario": {
            "fonte": "mapa + repo_index" if index else "mapa (sem índice de código)",
            "indexado_em": (index or {}).get("generated_at"),
            "termos_por_servico": {sid: len(p) for sid, p in vocab.items()},
        },
        "corte": {
            "min_score": min_score,
            "min_margin": min_margin,
            "min_terms": min_terms,
        },
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


def _print_explain(resumo: dict[str, Any]) -> None:
    voc = resumo["vocabulario"]
    print(f"Vocabulário: {voc['fonte']}", end="")
    if voc.get("indexado_em"):
        print(f" (índice de {voc['indexado_em']})")
    else:
        print()
    print(
        "Termos por serviço: "
        + ", ".join(f"{sid}={n}" for sid, n in voc["termos_por_servico"].items())
    )
    corte = resumo["corte"]
    print(
        f"Corte: score ≥ {corte['min_score']}, margem ≥ {corte['min_margin']}x o vice, "
        f"≥ {corte['min_terms']} termos distintos (ou 1 repetido)\n"
    )

    for doc in resumo["docs"]:
        print(f"── {doc['doc']} ({doc['chunks']} seções)")
        for linha in doc["de_para"]:
            evid = ", ".join(
                f"{e['termo']}×{e['ocorrencias']}" for e in linha["evidencia"][:3]
            )
            marca = "✓" if linha["motivo"] == "classificado" else "·"
            print(f"  {marca} {linha['secao'][:52]:<52} → {linha['servico']}")
            detalhe = f"score {linha['score']}"
            if linha["vice"]:
                detalhe += f" | vice {linha['vice']} {linha['vice_score']}"
            if linha["motivo"] != "classificado":
                detalhe += f" | {linha['motivo']}"
            print(f"      {detalhe}")
            if evid:
                print(f"      evidência: {evid}")
        print()


def main() -> None:
    p = argparse.ArgumentParser(description="De/para repos → marcadores nos docs")
    p.add_argument("--apply", action="store_true", help="escreve os marcadores nos arquivos")
    p.add_argument(
        "--convert-binarios",
        action="store_true",
        help=".docx/.doc → <stem>.marcado.md (original vira .bak)",
    )
    p.add_argument("--explain", action="store_true", help="tabela legível em vez de JSON")
    p.add_argument("--lines-per-chunk", type=int, default=40)
    p.add_argument("--min-score", type=float, default=2.0, help="score mínimo (default: 2.0)")
    p.add_argument(
        "--min-margin",
        type=float,
        default=1.3,
        help="quanto o 1º precisa superar o 2º para não ser ambíguo (default: 1.3)",
    )
    p.add_argument(
        "--min-terms",
        type=int,
        default=2,
        help="termos distintos exigidos por seção (default: 2)",
    )
    p.add_argument("--inputs", metavar="DIR", help="diretório de docs (default: inputs/)")
    p.add_argument("--mapa", metavar="FILE", help="mapa (default: inputs/mapa-servicos.yaml)")
    p.add_argument("--index", metavar="FILE", help="índice (default: state/repo_index.json)")
    args = p.parse_args()

    resumo = process(
        apply_changes=args.apply,
        convert_binarios=args.convert_binarios,
        lines_per_chunk=args.lines_per_chunk,
        min_score=args.min_score,
        min_margin=args.min_margin,
        min_terms=args.min_terms,
        inputs_dir=Path(args.inputs) if args.inputs else None,
        mapa_path=Path(args.mapa) if args.mapa else None,
        index_path=Path(args.index) if args.index else None,
    )
    if args.explain:
        _print_explain(resumo)
    else:
        print(json.dumps(resumo, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
