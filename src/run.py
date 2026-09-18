#!/usr/bin/env python3
"""
Prompt-less — pipeline token-eficiente de artefatos técnicos.

Uso:
  python -m src.run historia --dry-run
  python -m src.run historia --context ms-cliente
  python -m src.run historia --all-contexts
  python -m src.run historia --no-split
  python -m src.run historia --run-id RUN --resume
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

from src.hardening.debugger import build_debugger_report  # noqa: E402
from src.runtime import (  # noqa: E402
    HashMismatch,
    HandlerRegistry,
    Orchestrator,
    RunContext,
    RunStore,
    StageContext,
    StageError,
    build_run_result,
    default_registry,
)
from src.runtime.orchestrator import blocked_payload  # noqa: E402
from src.state_store import write_state  # noqa: E402
from src.validators import PipelineBlocked  # noqa: E402


def load_cfg() -> dict:
    return yaml.safe_load((ROOT / "config" / "pipeline.yaml").read_text(encoding="utf-8"))


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
    resume: bool = False,
    cfg: dict | None = None,
    registry: HandlerRegistry | None = None,
) -> dict:
    cfg = cfg or load_cfg()
    budget = cfg.get("budget") or {}
    max_ctx = int(budget.get("max_context_tokens", 2000))
    consolidated_chars = int(budget.get("consolidated_summary_max_tokens", 200)) * 4
    lines_per_chunk = int(budget.get("doc_lines_per_chunk", 40))
    chunk_summary_chars = int(budget.get("rag_chunk_max_tokens", 120)) * 2
    pipeline_version = str(cfg.get("version") or "1.0")

    compat_root = output_root or ROOT
    if resume:
        if not run_id:
            raise ValueError("resume requer run_id")
        run_dir = Path(compat_root) / "runs" / run_id
        if not run_dir.is_dir():
            raise FileNotFoundError(f"run '{run_id}' não encontrada em {run_dir}")

    run_ctx = RunContext.create(
        root=compat_root,
        objective=tipo,
        pipeline_version=pipeline_version,
        run_id=run_id,
    )
    store = RunStore(run_ctx)
    store.bootstrap(resume=resume)
    effective_state = run_ctx.state_path
    legacy_state = state_path

    payload: dict[str, Any] = {
        "tipo": tipo,
        "dry_run": dry_run,
        "inputs_dir": inputs_dir,
        "no_split": no_split,
        "requested_context": context,
        "all_contexts": all_contexts,
        "lines_per_chunk": lines_per_chunk,
        "consolidated_chars": consolidated_chars,
        "chunk_summary_chars": chunk_summary_chars,
        "max_ctx": max_ctx,
    }
    orchestrator = Orchestrator.from_cfg(
        cfg, store, registry=registry or default_registry()
    )

    def _mirror_state(data: dict) -> None:
        write_state(data, path=effective_state)
        if legacy_state is not None and Path(legacy_state) != effective_state:
            write_state(data, path=legacy_state)
        if output_root is None and legacy_state is None:
            write_state(data)

    def _scan_from_result(result: dict) -> dict | None:
        if isinstance(result.get("input_scan"), dict):
            return result["input_scan"]
        for ctx_result in result.get("by_context") or []:
            if isinstance(ctx_result.get("input_scan"), dict):
                return ctx_result["input_scan"]
        return None

    def _reason_from_result(result: dict) -> str | None:
        if result.get("reason"):
            return str(result["reason"])
        for ctx_result in result.get("by_context") or []:
            if ctx_result.get("reason"):
                return str(ctx_result["reason"])
        return None

    def _write_debugger(
        result: dict,
        *,
        status: str,
        exc: BaseException | None = None,
    ) -> None:
        store.write_debugger(
            build_debugger_report(
                scan=_scan_from_result(result),
                blocked_reason=_reason_from_result(result),
                validation=result.get("validation")
                if isinstance(result.get("validation"), dict)
                else None,
                run_status=status,
                stage=store.read_manifest().get("current_stage"),
                exception=exc,
            )
        )

    def _finalize(result: dict, *, status: str = "completed") -> dict:
        claims: list[dict[str, Any]] = list(result.get("claims") or [])
        discarded: list[dict[str, Any]] = list(result.get("discarded") or [])
        if result.get("by_context"):
            for ctx_result in result["by_context"]:
                claims.extend(ctx_result.get("claims") or [])
                discarded.extend(ctx_result.get("discarded") or [])
        seen: set[str] = set()
        unique_claims: list[dict[str, Any]] = []
        for c in claims:
            cid = str(c.get("id") or "")
            if cid and cid not in seen:
                seen.add(cid)
                unique_claims.append(c)
        prov_path = store.write_provenance(claims=unique_claims, discarded=discarded)
        if status in {"blocked", "failed"}:
            _write_debugger(result, status=status)
        store.mirror_artifacts_to_outputs(compat_root)
        store.finish(status, result)
        return {
            **result,
            "run_id": run_ctx.run_id,
            "status": status,
            "run_dir": str(run_ctx.run_dir),
            "claims_count": len(unique_claims),
            "discarded_count": len(discarded),
            "provenance": str(prov_path),
        }

    try:
        orchestrator.execute(payload, resume=resume)
        assembled = build_run_result(payload)
        blocked = bool(assembled.pop("_blocked", False))
        slim = payload.get("slim") or {}
        if blocked:
            if assembled.get("split"):
                _mirror_state(
                    {
                        **slim,
                        "status": "blocked",
                        "previous_actions": ["servicos_split", "emit"],
                        "contexts": payload.get("targets"),
                    }
                )
            return _finalize(assembled, status="blocked")
        _mirror_state(
            {
                **slim,
                "status": "emitted",
                "previous_actions": ["emit"]
                if not assembled.get("split")
                else ["servicos_split", "emit"],
                "contexts": payload.get("targets") if assembled.get("split") else None,
            }
        )
        return _finalize(assembled)
    except PipelineBlocked as exc:
        ctx = StageContext(
            stage_id="gate",
            run_ctx=store.ctx,
            store=store,
            cfg=cfg,
            payload=payload,
            context_id=exc.context,
        )
        assembled = blocked_payload(exc, ctx)
        assembled["split"] = bool(payload.get("split"))
        assembled["docs_ingested"] = payload.get("docs_ingested") or []
        return _finalize(assembled, status="blocked")
    except (StageError, HashMismatch) as exc:
        store.events.emit("run_failed", error=str(exc))
        _write_debugger({}, status="failed", exc=exc)
        if not store.is_finished:
            store.finish("failed")
        raise
    except Exception as exc:
        store.events.emit("run_failed", error=str(exc))
        _write_debugger({}, status="failed", exc=exc)
        if not store.is_finished:
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
    p.add_argument(
        "--run-id",
        metavar="ID",
        help="Identificador canônico da run (default: gerado)",
    )
    p.add_argument(
        "--resume",
        action="store_true",
        help="Retoma a run --run-id a partir dos checkpoints (valida hashes)",
    )
    args = p.parse_args()
    result = run(
        args.tipo,
        dry_run=not args.live,
        context=args.context,
        all_contexts=args.all_contexts,
        no_split=args.no_split,
        run_id=args.run_id,
        resume=args.resume,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
