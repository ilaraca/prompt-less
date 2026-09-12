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
from src.repo_index import load_index, service_evidence  # noqa: E402
from src.runtime import RunContext, RunStore  # noqa: E402
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
    output_root: Path | None = None,
    artifacts_root: Path | None = None,
) -> tuple[Path, Path, dict]:
    template = ARTIFACT_TEMPLATES[tipo].read_text(encoding="utf-8")
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
    pkg_name = f"llm_package_{tipo}.json"

    if artifacts_root is not None:
        emit_root = artifacts_root.parent
        emit_subdir = "artifacts"
        if context:
            pkg_path = artifacts_root / "contextos" / context / pkg_name
        else:
            pkg_path = artifacts_root / pkg_name
    else:
        emit_root = output_root
        emit_subdir = "outputs"
        base = output_root or ROOT
        if context:
            pkg_path = base / "outputs" / "contextos" / context / pkg_name
        else:
            pkg_path = base / "outputs" / pkg_name

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

    out = emit(tipo, artifact, context=context, root=emit_root, subdir=emit_subdir)
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
    output_root: Path | None = None,
    state_path: Path | None = None,
    artifacts_root: Path | None = None,
) -> dict:
    regras = slim.get("regras") or {}
    if servico:
        regras = _filter_regras_for_service(regras, servico)
    slim_ctx = {**slim, "documents": raw_docs, "regras": regras}
    state_kwargs = {"path": state_path} if state_path is not None else {}
    state = write_state(
        {
            **slim_ctx,
            "status": "preprocessing_done",
            "previous_actions": ["ingest", "preprocess", "servicos_split"],
        },
        **state_kwargs,
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
        output_root=output_root,
        artifacts_root=artifacts_root,
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
            output_root=output_root,
            artifacts_root=artifacts_root,
        )
        outputs[extra] = str(extra_out)
        packages[extra] = str(extra_pkg)
    return {
        "context": context,
        "servico": {k: v for k, v in (servico or {}).items() if k != "indice"} or None,
        "indice_usado": bool((servico or {}).get("indice")),
        "output": str(out),
        "outputs": outputs,
        "llm_packages": packages,
        "est_tokens": context_pkg["est_tokens"],
        "rag": context_pkg["rag_stats"],
        "claims": list(rag.get("claims") or []),
        "discarded": list(rag.get("discarded") or []),
    }


def run(
    tipo: str,
    dry_run: bool = True,
    *,
    context: str | None = None,
    all_contexts: bool = False,
    no_split: bool = False,
    inputs_dir: Path | None = None,
    output_root: Path | None = None,
    state_path: Path | None = None,
    run_id: str | None = None,
) -> dict:
    cfg = load_cfg()
    budget = cfg.get("budget") or {}
    max_ctx = int(budget.get("max_context_tokens", 2000))
    consolidated_chars = int(budget.get("consolidated_summary_max_tokens", 200)) * 4
    lines_per_chunk = int(budget.get("doc_lines_per_chunk", 40))
    chunk_summary_chars = int(budget.get("rag_chunk_max_tokens", 120)) * 2
    pipeline_version = str(cfg.get("version") or "1.0")

    compat_root = output_root or ROOT
    run_ctx = RunContext.create(
        root=compat_root,
        objective=tipo,
        pipeline_version=pipeline_version,
        run_id=run_id,
    )
    store = RunStore(run_ctx)
    store.bootstrap()
    store.events.emit("stage_started", stage="ingest")

    effective_state = run_ctx.state_path
    legacy_state = state_path

    raw = load_inputs(tipo, inputs_dir=inputs_dir)
    slim = preprocess(raw)
    store.events.emit("stage_completed", stage="ingest")
    store.events.emit("stage_completed", stage="preprocess")
    store.write_manifest({"current_stage": "reason", "service_id": context})

    mapa_path = (inputs_dir / "mapa-servicos.yaml") if inputs_dir else None
    mapa = None if no_split else load_mapa(mapa_path)
    documents = slim.get("documents") or []
    single_kwargs = dict(
        lines_per_chunk=lines_per_chunk,
        consolidated_chars=consolidated_chars,
        chunk_summary_chars=chunk_summary_chars,
        max_ctx=max_ctx,
        output_root=compat_root,
        state_path=effective_state,
        artifacts_root=run_ctx.artifacts_dir,
    )

    def _mirror_state(data: dict) -> None:
        write_state(data, path=effective_state)
        if legacy_state is not None and Path(legacy_state) != effective_state:
            write_state(data, path=legacy_state)
        if output_root is None and legacy_state is None:
            write_state(data)

    def _finalize(result: dict) -> dict:
        claims: list[dict[str, Any]] = list(result.get("claims") or [])
        discarded: list[dict[str, Any]] = list(result.get("discarded") or [])
        if result.get("by_context"):
            for ctx_result in result["by_context"]:
                claims.extend(ctx_result.get("claims") or [])
                discarded.extend(ctx_result.get("discarded") or [])
        # dedupe claims by id
        seen: set[str] = set()
        unique_claims: list[dict[str, Any]] = []
        for c in claims:
            cid = str(c.get("id") or "")
            if cid and cid not in seen:
                seen.add(cid)
                unique_claims.append(c)
        prov_path = store.write_provenance(claims=unique_claims, discarded=discarded)
        store.mirror_artifacts_to_outputs(compat_root)
        store.finish("completed", result)
        return {
            **result,
            "run_id": run_ctx.run_id,
            "status": "completed",
            "run_dir": str(run_ctx.run_dir),
            "claims_count": len(unique_claims),
            "discarded_count": len(discarded),
            "provenance": str(prov_path),
        }

    try:
        if mapa is None or no_split:
            store.events.emit("stage_started", stage="emit")
            result = _run_single(tipo, slim, documents, cfg, dry_run, **single_kwargs)
            _mirror_state({**slim, "status": "emitted", "previous_actions": ["emit"]})
            return _finalize(
                {
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
            )

        ids = list_service_ids(mapa)
        if context:
            if context not in ids and context != "_unassigned":
                raise SystemExit(
                    f"contexto desconhecido: {context}. Disponíveis: {', '.join(ids)}"
                )
            targets = [context]
        elif all_contexts or tipo in {"historia", "prd"}:
            partitioned = partition_documents(
                documents, mapa, lines_per_chunk=lines_per_chunk
            )
            targets = [sid for sid in ids if sid in partitioned]
            if "_unassigned" in partitioned:
                targets.append("_unassigned")
            if not targets:
                targets = ids
        else:
            store.events.emit("stage_started", stage="emit")
            result = _run_single(tipo, slim, documents, cfg, dry_run, **single_kwargs)
            return _finalize(
                {
                    **result,
                    "split": False,
                    "mapa": True,
                    "hint": "Use --context ID ou --all-contexts para fatiar por microsserviço",
                    "docs_ingested": [
                        {"name": d.get("name"), "lines": d.get("lines")}
                        for d in (raw.get("documents") or [])
                    ],
                }
            )

        by_context = []
        all_outputs: dict[str, Any] = {}
        index = load_index()
        store.events.emit("stage_started", stage="emit", targets=targets)
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
            evidencia = service_evidence(index, sid)
            if evidencia:
                svc["indice"] = {k: v for k, v in evidencia.items() if k != "repos"}
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
                **single_kwargs,
            )
            by_context.append(one)
            all_outputs[sid] = one["outputs"]

        _mirror_state(
            {
                **slim,
                "status": "emitted",
                "previous_actions": ["servicos_split", "emit"],
                "contexts": targets,
            }
        )

        return _finalize(
            {
                "split": True,
                "contexts": targets,
                "by_context": by_context,
                "outputs": all_outputs,
                "output": by_context[0]["output"] if by_context else None,
                "docs_ingested": [
                    {
                        "name": d.get("name"),
                        "lines": d.get("lines"),
                        "est_tokens_raw": d.get("est_tokens_raw"),
                    }
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
        )
    except Exception as exc:
        store.events.emit("run_failed", error=str(exc))
        store.finish("failed")
        raise


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
