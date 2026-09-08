#!/usr/bin/env python3
"""
Prompt-less — pipeline token-eficiente de artefatos técnicos.

  Dados brutos (json/yaml/txt/docx/doc)
    → preprocess → state → RAG+doc compress → context ≤ budget → reason → emit

Uso:
  python -m src.run openapi [--dry-run]
  python -m src.run mermaid [--dry-run]
  python -m src.run historia [--dry-run]   # também emite PRD.md (insumo SDD)
  python -m src.run prd [--dry-run]
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
from src.ingest import ARTIFACT_TEMPLATES, load_inputs  # noqa: E402
from src.preprocess import preprocess  # noqa: E402
from src.rag_compress import compress_rag  # noqa: E402
from src.reason import build_llm_package, dry_run_scaffold  # noqa: E402
from src.state_store import write_state  # noqa: E402


def load_cfg() -> dict:
    return yaml.safe_load((ROOT / "config" / "pipeline.yaml").read_text(encoding="utf-8"))


def _also_emit(cfg: dict, tipo: str) -> list[str]:
    art = (cfg.get("artifacts") or {}).get(tipo) or {}
    return list(art.get("also_emit") or [])


def _build_one(
    tipo: str,
    slim: dict,
    state: dict,
    rag: dict,
    max_ctx: int,
    dry_run: bool,
) -> tuple[Path, Path, dict]:
    template = ARTIFACT_TEMPLATES[tipo].read_text(encoding="utf-8")
    context = build_context(
        tipo=tipo,
        state=state,
        rag=rag,
        template=template,
        budget_tokens=max_ctx,
    )
    package = build_llm_package(context)
    pkg_path = ROOT / "outputs" / f"llm_package_{tipo}.json"
    pkg_path.parent.mkdir(parents=True, exist_ok=True)
    pkg_path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")

    if dry_run:
        artifact = dry_run_scaffold(
            tipo,
            slim["ui"],
            slim["regras"],
            template,
            consolidated=rag.get("consolidated") or "",
        )
    else:
        raise NotImplementedError("Mode --live: plugar client OpenAI/Claude no reason.py")

    out = emit(tipo, artifact)
    return out, pkg_path, context


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
    rag = compress_rag(
        slim,
        consolidated_chars=consolidated_chars,
        lines_per_chunk=lines_per_chunk,
        chunk_summary_chars=chunk_summary_chars,
    )

    out, pkg_path, context = _build_one(tipo, slim, state, rag, max_ctx, dry_run)
    outputs = {tipo: str(out)}
    packages = {tipo: str(pkg_path)}

    # história → também gera PRD.md (canônico para SDD)
    for extra in _also_emit(cfg, tipo):
        extra_out, extra_pkg, _ = _build_one(extra, slim, state, rag, max_ctx, dry_run)
        outputs[extra] = str(extra_out)
        packages[extra] = str(extra_pkg)

    write_state(
        {
            **slim,
            "status": "emitted",
            "previous_actions": ["ingest", "preprocess", "doc_compress", "rag", "emit"],
        }
    )

    return {
        "output": str(out),
        "outputs": outputs,
        "llm_package": str(pkg_path),
        "llm_packages": packages,
        "est_tokens": context["est_tokens"],
        "rag": context["rag_stats"],
        "docs_ingested": [
            {"name": d.get("name"), "lines": d.get("lines"), "est_tokens_raw": d.get("est_tokens_raw")}
            for d in (raw.get("documents") or [])
        ],
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Prompt-less — token-efficient tech artifacts")
    p.add_argument("tipo", choices=["openapi", "mermaid", "historia", "prd"])
    p.add_argument("--dry-run", action="store_true", default=True, help="scaffold sem LLM (default)")
    p.add_argument("--live", action="store_true", help="chamar LLM (ainda não implementado)")
    args = p.parse_args()
    result = run(args.tipo, dry_run=not args.live)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
