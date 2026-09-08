#!/usr/bin/env python3
"""
Pipeline token-eficiente (Yuval Ben-itzhak → artefatos techlead).

  Dados brutos (json/yaml/txt/docx/doc)
    → preprocess → state → RAG+doc compress → context ≤ budget → reason → emit

Uso:
  python -m src.run openapi [--dry-run]
  python -m src.run mermaid [--dry-run]
  python -m src.run historia [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.context_builder import build_context  # noqa: E402
from src.emit import emit  # noqa: E402
from src.ingest import load_inputs  # noqa: E402
from src.preprocess import preprocess  # noqa: E402
from src.rag_compress import compress_rag  # noqa: E402
from src.reason import build_llm_package, dry_run_scaffold  # noqa: E402
from src.state_store import write_state  # noqa: E402


def load_cfg() -> dict:
    return yaml.safe_load((ROOT / "config" / "pipeline.yaml").read_text(encoding="utf-8"))


def run(tipo: str, dry_run: bool = True) -> dict:
    cfg = load_cfg()
    budget = cfg.get("budget") or {}
    max_ctx = int(budget.get("max_context_tokens", 2000))
    consolidated_chars = int(budget.get("consolidated_summary_max_tokens", 200)) * 4
    lines_per_chunk = int(budget.get("doc_lines_per_chunk", 40))
    chunk_summary_chars = int(budget.get("rag_chunk_max_tokens", 120)) * 2

    raw = load_inputs(tipo)
    slim = preprocess(raw)
    state = write_state(
        {**slim, "status": "preprocessing_done", "previous_actions": ["ingest", "preprocess"]}
    )
    # texto dos docs não vai para o state; só para compressão
    rag = compress_rag(
        slim,
        consolidated_chars=consolidated_chars,
        lines_per_chunk=lines_per_chunk,
        chunk_summary_chars=chunk_summary_chars,
    )
    # remove texto bruto antes de montar pacote LLM (já está em consolidated)
    slim_for_reason = {**slim, "documents": state.get("documents", [])}
    context = build_context(
        tipo=tipo,
        state=state,
        rag=rag,
        template=slim_for_reason["template"],
        budget_tokens=max_ctx,
    )
    package = build_llm_package(context)

    pkg_path = ROOT / "outputs" / f"llm_package_{tipo}.json"
    pkg_path.parent.mkdir(parents=True, exist_ok=True)
    pkg_path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")

    if dry_run:
        artifact = dry_run_scaffold(tipo, slim["ui"], slim["regras"], slim["template"])
    else:
        raise NotImplementedError("Mode --live: plugar client OpenAI/Claude no reason.py")

    out = emit(tipo, artifact)
    write_state(
        {
            **slim,
            "status": "emitted",
            "previous_actions": ["ingest", "preprocess", "doc_compress", "rag", "emit"],
        }
    )

    return {
        "output": str(out),
        "llm_package": str(pkg_path),
        "est_tokens": context["est_tokens"],
        "rag": context["rag_stats"],
        "docs_ingested": [
            {"name": d.get("name"), "lines": d.get("lines"), "est_tokens_raw": d.get("est_tokens_raw")}
            for d in (raw.get("documents") or [])
        ],
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Techlead artifact pipeline (token-efficient)")
    p.add_argument("tipo", choices=["openapi", "mermaid", "historia"])
    p.add_argument("--dry-run", action="store_true", default=True, help="scaffold sem LLM (default)")
    p.add_argument("--live", action="store_true", help="chamar LLM (ainda não implementado)")
    args = p.parse_args()
    result = run(args.tipo, dry_run=not args.live)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
