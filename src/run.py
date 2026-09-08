#!/usr/bin/env python3
"""
Prompt-less — pipeline token-eficiente de artefatos técnicos.

Uso:
  python -m src.run historia --dry-run
  python -m src.run historia --context ms-cliente
  python -m src.run historia --all-contexts
  python -m src.run historia --no-split
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.context_builder import build_context  # noqa: E402
from src.emit import emit  # noqa: E402
from src.ingest import ARTIFACT_TEMPLATES, load_inputs  # noqa: E402
from src.preprocess import preprocess  # noqa: E402
from src.rag_compress import compress_rag  # noqa: E402
from src.reason import build_llm_package, dry_run_scaffold  # noqa: E402
from src.servicos import (  # noqa: E402
    docs_for_service,
    get_service,
    list_service_ids,
    load_mapa,
    partition_documents,
)
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
    *,
    context: str | None = None,
    servico: dict[str, Any] | None = None,
) -> tuple[Path, Path, dict]:
    template = ARTIFACT_TEMPLATES[tipo].read_text(encoding="utf-8")
    # state enriquecido com ownership (sem texto)
    state_out = {
        **state,
        "servico": {
            "id": (servico or {}).get("id"),
            "nome": (servico or {}).get("nome"),
            "repos": (servico or {}).get("repos") or [],
        }
        if servico
        else None,
    }
    context_pkg = build_context(
        tipo=tipo,
        state=state_out,
        rag=rag,
        template=template,
        budget_tokens=max_ctx,
    )
    package = build_llm_package(context_pkg)
    pkg_name = f"llm_package_{tipo}.json" if not context else f"llm_package_{tipo}.json"
    if context:
        pkg_path = ROOT / "outputs" / "contextos" / context / pkg_name
    else:
        pkg_path = ROOT / "outputs" / pkg_name
    pkg_path.parent.mkdir(parents=True, exist_ok=True)
    pkg_path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")

    if dry_run:
        artifact = dry_run_scaffold(
            tipo,
            slim["ui"],
            slim["regras"],
            template,
            consolidated=rag.get("consolidated") or "",
            engenharia=slim.get("engenharia") or {},
            servico=servico,
        )
    else:
        raise NotImplementedError("Mode --live: plugar client OpenAI/Claude no reason.py")

    out = emit(tipo, artifact, context=context)
    return out, pkg_path, context_pkg


def _filter_regras_for_service(regras: dict, svc: dict) -> dict:
    """Mantém bloqueios/decisões cujo texto case com keywords do serviço (best-effort)."""
    kws = [str(k).lower() for k in (svc.get("keywords") or []) if k]
    if not kws or not svc.get("id") or svc.get("id") == "_unassigned":
        return regras
    out = dict(regras)
    out["fluxo"] = svc.get("nome") or regras.get("fluxo")
    blocks = []
    for b in regras.get("bloqueios") or []:
        blob = " ".join(str(v) for v in (b.values() if isinstance(b, dict) else [b])).lower()
        if any(k in blob for k in kws):
            blocks.append(b)
    # se nada casou, mantém todos (melhor falso positivo que história vazia)
    out["bloqueios"] = blocks or list(regras.get("bloqueios") or [])
    decs = []
    for d in regras.get("decisoes") or []:
        blob = str(d).lower()
        if any(k in blob for k in kws):
            decs.append(d)
    out["decisoes"] = decs if decs else list(regras.get("decisoes") or [])
    return out


def _run_single(
    tipo: str,
    slim: dict,
    raw_docs: list,
    cfg: dict,
    dry_run: bool,
    *,
    context: str | None = None,
    servico: dict[str, Any] | None = None,
    lines_per_chunk: int = 40,
    consolidated_chars: int = 800,
    chunk_summary_chars: int = 220,
    max_ctx: int = 2000,
) -> dict:
    regras = slim.get("regras") or {}
    if servico:
        regras = _filter_regras_for_service(regras, servico)
    slim_ctx = {**slim, "documents": raw_docs, "regras": regras}
    state = write_state(
        {
            **slim_ctx,
            "status": "preprocessing_done",
            "previous_actions": ["ingest", "preprocess", "servicos_split"],
        }
    )
    rag = compress_rag(
        slim_ctx,
        consolidated_chars=consolidated_chars,
        lines_per_chunk=lines_per_chunk,
        chunk_summary_chars=chunk_summary_chars,
    )
    out, pkg_path, context_pkg = _build_one(
        tipo,
        slim_ctx,
        state,
        rag,
        max_ctx,
        dry_run,
        context=context,
        servico=servico,
    )
    outputs = {tipo: str(out)}
    packages = {tipo: str(pkg_path)}
    for extra in _also_emit(cfg, tipo):
        extra_out, extra_pkg, _ = _build_one(
            extra,
            slim_ctx,
            state,
            rag,
            max_ctx,
            dry_run,
            context=context,
            servico=servico,
        )
        outputs[extra] = str(extra_out)
        packages[extra] = str(extra_pkg)
    return {
        "context": context,
        "servico": servico,
        "output": str(out),
        "outputs": outputs,
        "llm_packages": packages,
        "est_tokens": context_pkg["est_tokens"],
        "rag": context_pkg["rag_stats"],
    }


def run(
    tipo: str,
    dry_run: bool = True,
    *,
    context: str | None = None,
    all_contexts: bool = False,
    no_split: bool = False,
) -> dict:
    cfg = load_cfg()
    budget = cfg.get("budget") or {}
    max_ctx = int(budget.get("max_context_tokens", 2000))
    consolidated_chars = int(budget.get("consolidated_summary_max_tokens", 200)) * 4
    lines_per_chunk = int(budget.get("doc_lines_per_chunk", 40))
    chunk_summary_chars = int(budget.get("rag_chunk_max_tokens", 120)) * 2

    raw = load_inputs(tipo)
    slim = preprocess(raw)
    mapa = None if no_split else load_mapa()
    documents = slim.get("documents") or []

    # Sem mapa ou --no-split → comportamento legado (um artefato)
    if mapa is None or no_split:
        result = _run_single(
            tipo,
            slim,
            documents,
            cfg,
            dry_run,
            lines_per_chunk=lines_per_chunk,
            consolidated_chars=consolidated_chars,
            chunk_summary_chars=chunk_summary_chars,
            max_ctx=max_ctx,
        )
        write_state({**slim, "status": "emitted", "previous_actions": ["emit"]})
        return {
            **result,
            "split": False,
            "docs_ingested": [
                {
                    "name": d.get("name"),
                    "lines": d.get("lines"),
                    "est_tokens_raw": d.get("est_tokens_raw"),
                }
                for d in (raw.get("documents") or [])
            ],
        }

    # Com mapa: --context, --all-contexts, ou all automático para historia/prd
    ids = list_service_ids(mapa)
    if context:
        if context not in ids and context != "_unassigned":
            raise SystemExit(
                f"contexto desconhecido: {context}. Disponíveis: {', '.join(ids)}"
            )
        targets = [context]
    elif all_contexts or tipo in {"historia", "prd"}:
        # default com mapa: gera um pacote por serviço que tiver texto
        partitioned = partition_documents(
            documents, mapa, lines_per_chunk=lines_per_chunk
        )
        targets = [sid for sid in ids if sid in partitioned]
        if "_unassigned" in partitioned:
            targets.append("_unassigned")
        if not targets:
            targets = ids  # ainda emite ownership mesmo sem texto
    else:
        # openapi/mermaid sem flag → legado single (docs completos)
        result = _run_single(
            tipo,
            slim,
            documents,
            cfg,
            dry_run,
            lines_per_chunk=lines_per_chunk,
            consolidated_chars=consolidated_chars,
            chunk_summary_chars=chunk_summary_chars,
            max_ctx=max_ctx,
        )
        return {
            **result,
            "split": False,
            "mapa": True,
            "hint": "Use --context ID ou --all-contexts para fatiar por microsserviço",
            "docs_ingested": [
                {"name": d.get("name"), "lines": d.get("lines")}
                for d in (raw.get("documents") or [])
            ],
        }

    by_context = []
    all_outputs: dict[str, Any] = {}
    for sid in targets:
        svc = (
            get_service(mapa, sid)
            if sid != "_unassigned"
            else {
                "id": "_unassigned",
                "nome": "Não classificado",
                "repos": [],
                "keywords": [],
            }
        )
        docs = docs_for_service(
            documents, mapa, sid, lines_per_chunk=lines_per_chunk
        )
        one = _run_single(
            tipo,
            slim,
            docs,
            cfg,
            dry_run,
            context=sid,
            servico=svc,
            lines_per_chunk=lines_per_chunk,
            consolidated_chars=consolidated_chars,
            chunk_summary_chars=chunk_summary_chars,
            max_ctx=max_ctx,
        )
        by_context.append(one)
        all_outputs[sid] = one["outputs"]

    write_state(
        {
            **slim,
            "status": "emitted",
            "previous_actions": ["servicos_split", "emit"],
            "contexts": targets,
        }
    )

    return {
        "split": True,
        "contexts": targets,
        "by_context": by_context,
        "outputs": all_outputs,
        "output": by_context[0]["output"] if by_context else None,
        "docs_ingested": [
            {"name": d.get("name"), "lines": d.get("lines"), "est_tokens_raw": d.get("est_tokens_raw")}
            for d in (raw.get("documents") or [])
        ],
        "partition_preview": {
            sid: {
                "lines": meta["lines"],
                "sources": meta["sources"],
                "repos": meta["meta"].get("repos"),
            }
            for sid, meta in partition_documents(
                documents, mapa, lines_per_chunk=lines_per_chunk
            ).items()
        },
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Prompt-less — token-efficient tech artifacts")
    p.add_argument("tipo", choices=["openapi", "mermaid", "historia", "prd"])
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--live", action="store_true")
    p.add_argument(
        "--context",
        metavar="ID",
        help="Gera artefatos só para este serviço (ex.: ms-cliente)",
    )
    p.add_argument(
        "--all-contexts",
        action="store_true",
        help="Gera um pacote por serviço do mapa-servicos.yaml",
    )
    p.add_argument(
        "--no-split",
        action="store_true",
        help="Ignora mapa-servicos e emite um único artefato (legado)",
    )
    args = p.parse_args()
    result = run(
        args.tipo,
        dry_run=not args.live,
        context=args.context,
        all_contexts=args.all_contexts,
        no_split=args.no_split,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
