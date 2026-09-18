"""Handlers do grafo default — mesmos efeitos do `run.py` pré-orquestração."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.context_builder import build_context
from src.hybrid_retrieval import build_query_from_ctx, compress_documents_hybrid
from src.domain.provenance import stamp_claim_identity
from src.emit import emit
from src.ingest import ARTIFACT_TEMPLATES, load_inputs
from src.preprocess import preprocess as preprocess_inputs
from src.rag_compress import compress_rag, retrieve_chunks
from src.hardening.input_scan import collect_untrusted_blobs, scan_blobs
from src.reason import (
    LiveApiError,
    build_live_telemetry,
    build_llm_package,
    dry_run_scaffold,
    live_generate,
)
from src.renderers import render_historia, render_mermaid, render_openapi, render_prd, render_sdd
from src.repo_index import load_index, service_evidence
from src.runtime.stage import HandlerRegistry, StageContext, StageError
from src.tokenizer import TokenEstimate
from src.servicos import (
    docs_for_service,
    get_service,
    list_service_ids,
    load_mapa,
    partition_documents,
)
from src.spec.builder import build_canonical_spec
from src.state_store import write_state
from src.validators import (
    PipelineBlocked,
    ValidationIssue,
    ValidationResult,
    validate_derived_artifact,
    validate_spec,
)

REGISTRY = HandlerRegistry()


def default_registry() -> HandlerRegistry:
    return REGISTRY


def _also_emit(cfg: dict, tipo: str) -> list[str]:
    art = (cfg.get("artifacts") or {}).get(tipo) or {}
    return list(art.get("also_emit") or [])


def _filter_regras_for_service(regras: dict, svc: dict) -> dict:
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


def _unassigned_service() -> dict[str, Any]:
    return {
        "id": "_unassigned",
        "nome": "Não classificado",
        "repos": [],
        "keywords": [],
    }


def _docs_ingested(raw: dict) -> list[dict[str, Any]]:
    return [
        {
            "name": d.get("name"),
            "lines": d.get("lines"),
            "est_tokens_raw": d.get("est_tokens_raw"),
        }
        for d in (raw.get("documents") or [])
    ]


@REGISTRY.register("repos_scan")
@REGISTRY.register("repo_index")
@REGISTRY.register("marcar")
def _optional_not_in_default_graph(ctx: StageContext) -> None:
    raise StageError(
        f"estágio opcional {ctx.stage_id!r} não faz parte do grafo default; "
        "habilite só com um handler real"
    )


@REGISTRY.register("ingest")
def ingest(ctx: StageContext) -> None:
    tipo = ctx.payload["tipo"]
    inputs_dir = ctx.payload.get("inputs_dir")
    raw = load_inputs(tipo, inputs_dir=inputs_dir)
    ctx.payload["raw"] = raw
    ctx.payload["docs_ingested"] = _docs_ingested(raw)


@REGISTRY.register("preprocess")
def preprocess(ctx: StageContext) -> None:
    ctx.payload["slim"] = preprocess_inputs(ctx.payload["raw"])


@REGISTRY.register("servicos_split")
def servicos_split(ctx: StageContext) -> None:
    slim = ctx.payload["slim"]
    documents = slim.get("documents") or []
    tipo = ctx.payload["tipo"]
    no_split = bool(ctx.payload.get("no_split"))
    requested = ctx.payload.get("requested_context")
    all_contexts = bool(ctx.payload.get("all_contexts"))
    lines_per_chunk = int(ctx.payload.get("lines_per_chunk") or 40)
    inputs_dir = ctx.payload.get("inputs_dir")
    mapa_path = (Path(inputs_dir) / "mapa-servicos.yaml") if inputs_dir else None
    mapa = None if no_split else load_mapa(mapa_path)
    ctx.payload["mapa"] = mapa
    ctx.payload["index"] = load_index()

    if mapa is None or no_split:
        ctx.payload["split"] = False
        ctx.payload["targets"] = [None]
        ctx.payload["docs_by_context"] = {None: documents}
        ctx.payload["services"] = {None: None}
        return

    ids = list_service_ids(mapa)
    if requested:
        if requested not in ids and requested != "_unassigned":
            raise SystemExit(
                f"contexto desconhecido: {requested}. Disponíveis: {', '.join(ids)}"
            )
        targets: list[str | None] = [requested]
        ctx.payload["split"] = True
    elif all_contexts or tipo in {"historia", "prd", "sdd"}:
        partitioned = partition_documents(
            documents, mapa, lines_per_chunk=lines_per_chunk
        )
        targets = [sid for sid in ids if sid in partitioned]
        if "_unassigned" in partitioned:
            targets.append("_unassigned")
        if not targets:
            targets = list(ids)
        ctx.payload["split"] = True
        ctx.payload["partition_preview"] = {
            sid: {
                "lines": meta["lines"],
                "sources": meta["sources"],
                "repos": meta["meta"].get("repos"),
            }
            for sid, meta in partitioned.items()
        }
    else:
        ctx.payload["split"] = False
        ctx.payload["mapa"] = mapa
        ctx.payload["hint"] = (
            "Use --context ID ou --all-contexts para fatiar por microsserviço"
        )
        ctx.payload["targets"] = [None]
        ctx.payload["docs_by_context"] = {None: documents}
        ctx.payload["services"] = {None: None}
        return

    services: dict[str | None, dict | None] = {}
    docs_by_context: dict[str | None, list] = {}
    index = ctx.payload["index"]
    for sid in targets:
        if sid == "_unassigned":
            svc: dict[str, Any] | None = _unassigned_service()
        else:
            svc = get_service(mapa, sid) if sid else None
        if svc and sid and sid != "_unassigned":
            evidencia = service_evidence(index, sid)
            if evidencia:
                svc = {**svc, "indice": {k: v for k, v in evidencia.items() if k != "repos"}}
        services[sid] = svc
        docs_by_context[sid] = (
            docs_for_service(documents, mapa, sid, lines_per_chunk=lines_per_chunk)
            if sid
            else documents
        )
    ctx.payload["targets"] = targets
    ctx.payload["services"] = services
    ctx.payload["docs_by_context"] = docs_by_context


def _prepare_slot(ctx: StageContext) -> dict[str, Any]:
    slot = ctx.slot()
    sid = ctx.context_id
    slim = ctx.payload["slim"]
    servico = (ctx.payload.get("services") or {}).get(sid)
    documents = (ctx.payload.get("docs_by_context") or {}).get(sid) or slim.get("documents") or []
    regras = slim.get("regras") or {}
    if servico:
        regras = _filter_regras_for_service(regras, servico)
    slim_ctx = {**slim, "documents": documents, "regras": regras}
    slot["servico"] = servico
    slot["documents"] = documents
    slot["slim_ctx"] = slim_ctx
    return slot


@REGISTRY.register("state_write")
def state_write(ctx: StageContext) -> None:
    slot = _prepare_slot(ctx)
    slim_ctx = slot["slim_ctx"]
    state = write_state(
        {
            **slim_ctx,
            "status": "preprocessing_done",
            "previous_actions": ["ingest", "preprocess", "servicos_split"],
        },
        path=ctx.run_ctx.state_path,
    )
    slot["state"] = state


@REGISTRY.register("doc_compress")
def doc_compress(ctx: StageContext) -> None:
    slot = ctx.slot()
    slim_ctx = slot.get("slim_ctx") or _prepare_slot(ctx)["slim_ctx"]
    state_dir = getattr(ctx.run_ctx, "state_dir", None) or (ctx.run_ctx.root / "state")
    slot["doc_compressed"] = compress_documents_hybrid(
        slim_ctx.get("documents") or [],
        query=build_query_from_ctx(slim_ctx),
        lines_per_chunk=int(ctx.payload.get("lines_per_chunk") or 40),
        chunk_summary_chars=int(ctx.payload.get("chunk_summary_chars") or 220),
        consolidated_chars=int(ctx.payload.get("consolidated_chars") or 800),
        enable_semantic=bool(ctx.payload.get("enable_semantic", True)),
        state_dir=state_dir,
    )


@REGISTRY.register("rag_retrieve")
def rag_retrieve(ctx: StageContext) -> None:
    slot = ctx.slot()
    slim_ctx = slot.get("slim_ctx") or _prepare_slot(ctx)["slim_ctx"]
    slot["retrieved"] = retrieve_chunks(slim_ctx)


@REGISTRY.register("rag_compress")
def rag_compress(ctx: StageContext) -> None:
    slot = ctx.slot()
    slim_ctx = slot.get("slim_ctx") or _prepare_slot(ctx)["slim_ctx"]
    servico = slot.get("servico") or (ctx.payload.get("services") or {}).get(ctx.context_id)
    slot["rag"] = compress_rag(
        slim_ctx,
        consolidated_chars=int(ctx.payload.get("consolidated_chars") or 800),
        lines_per_chunk=int(ctx.payload.get("lines_per_chunk") or 40),
        chunk_summary_chars=int(ctx.payload.get("chunk_summary_chars") or 220),
        service_id=(servico or {}).get("id") or ctx.context_id,
    )


@REGISTRY.register("canonical_spec")
def canonical_spec(ctx: StageContext) -> None:
    slot = ctx.slot()
    slim_ctx = slot["slim_ctx"]
    rag = slot["rag"]
    servico = slot.get("servico")
    spec = build_canonical_spec(
        ui=slim_ctx.get("ui") or {},
        regras=slim_ctx.get("regras") or {},
        engenharia=slim_ctx.get("engenharia") or {},
        claims=list(rag.get("claims") or []),
        servico=servico,
        mapa=ctx.payload.get("mapa"),
    )
    validation = validate_spec(spec)
    slot["spec"] = spec
    slot["validation"] = validation
    ctx.payload["validation"] = validation

    artifacts_root = ctx.run_ctx.artifacts_dir
    spec_dir = (
        ctx.run_ctx.context_artifacts_dir(ctx.context_id)
        if ctx.context_id
        else artifacts_root
    )
    spec_path = spec_dir / "canonical-spec.yaml"
    ctx.write_text(
        spec_path,
        yaml.safe_dump(spec.to_dict(), allow_unicode=True, sort_keys=False),
    )
    val_dir = (
        ctx.run_ctx.context_validations_dir(ctx.context_id)
        if ctx.context_id
        else ctx.run_ctx.validations_dir
    )
    val_path = val_dir / "spec-validation.json"
    ctx.write_json(val_path, validation.to_dict())
    slot["spec_path"] = spec_path
    slot["val_path"] = val_path
    # bloqueio é o gate `validation.has_errors` declarado no YAML


def _tipos_to_emit(ctx: StageContext) -> list[str]:
    tipo = ctx.payload["tipo"]
    return [tipo, *(_also_emit(ctx.cfg, tipo))]


@REGISTRY.register("context_build")
def context_build(ctx: StageContext) -> None:
    slot = ctx.slot()
    state = slot["state"]
    rag = slot["rag"]
    servico = slot.get("servico")
    spec = slot.get("spec")
    max_ctx = int(ctx.payload.get("max_ctx") or 2000)
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
    by_tipo: dict[str, dict[str, Any]] = {}
    for tipo in _tipos_to_emit(ctx):
        template = ARTIFACT_TEMPLATES[tipo].read_text(encoding="utf-8")
        by_tipo[tipo] = build_context(
            tipo=tipo,
            state=state_out,
            rag=rag,
            template=template,
            budget_tokens=max_ctx,
            spec=spec,
            attempts=int(getattr(ctx, "attempt", 1) or 1),
        )
    slot["context_by_tipo"] = by_tipo
    slot["context_pkg"] = by_tipo[ctx.payload["tipo"]]
    # Excesso do mínimo crítico → bloqueio com diagnóstico (não cortar RF/AC)
    blocked_pkg = next(
        (
            pkg
            for pkg in by_tipo.values()
            if pkg.get("budget_status") in {"blocked", "split_required"}
        ),
        None,
    )
    if blocked_pkg is not None:
        report = blocked_pkg.get("budget_report") or {}
        validation = ValidationResult(
            issues=[
                ValidationIssue(
                    code=(
                        "CRITICAL_BUDGET_SPLIT_REQUIRED"
                        if blocked_pkg.get("budget_status") == "split_required"
                        else "CRITICAL_BUDGET_EXCEEDED"
                    ),
                    severity="error",
                    message=str(
                        report.get("diagnosis")
                        or "conteúdo crítico não cabe no budget de contexto"
                    ),
                    subject_id="context_budget",
                )
            ]
        )
        val_dir = (
            ctx.run_ctx.context_validations_dir(ctx.context_id)
            if ctx.context_id
            else ctx.run_ctx.validations_dir
        )
        val_path = val_dir / "context-budget.json"
        ctx.write_json(
            val_path,
            {
                "budget_report": report,
                "validation": validation.to_dict(),
                "task_metrics": blocked_pkg.get("task_metrics"),
            },
        )
        raise PipelineBlocked(
            validation,
            spec if hasattr(spec, "claims") else None,
            discarded=list(rag.get("discarded") or [])
            + list(report.get("omissions") or [])
            + list(report.get("critical_omissions") or []),
            context=ctx.context_id,
            reason=(
                "critical_budget_split_required"
                if blocked_pkg.get("budget_status") == "split_required"
                else "critical_budget_exceeded"
            ),
            report_path=str(val_path),
        )


def _estimate_from_context(context_pkg: dict[str, Any]) -> TokenEstimate | dict[str, Any] | None:
    usage = context_pkg.get("token_usage")
    if isinstance(usage, dict) and usage.get("estimated") is not None:
        return usage
    tokens = context_pkg.get("est_tokens")
    if tokens is None:
        return None
    usage_dict = usage if isinstance(usage, dict) else {}
    method = context_pkg.get("est_tokens_method") or usage_dict.get("method") or "heuristic"
    if method not in ("official", "heuristic"):
        method = "heuristic"
    return TokenEstimate(
        tokens=int(tokens),
        method=method,  # type: ignore[arg-type]
        provider=str(usage_dict.get("provider") or "unknown"),
        model=str(usage_dict.get("model") or "unknown"),
    )


def _render_artifact(tipo: str, slim: dict, rag: dict, spec: Any, dry_run: bool, servico: dict | None) -> str:
    template = ARTIFACT_TEMPLATES[tipo].read_text(encoding="utf-8")
    if not dry_run:
        raise StageError("modo --live deve passar por live_generate antes de _render_artifact")
    if tipo == "historia" and spec is not None:
        return render_historia(spec, template, engenharia=slim.get("engenharia") or {})
    if tipo == "prd" and spec is not None:
        return render_prd(
            spec,
            template,
            engenharia=slim.get("engenharia") or {},
            consolidated=rag.get("consolidated") or "",
        )
    if tipo == "openapi" and spec is not None:
        return render_openapi(spec, template)
    if tipo == "mermaid" and spec is not None:
        return render_mermaid(spec, template)
    if tipo == "sdd" and spec is not None:
        return render_sdd(spec, template)
    return dry_run_scaffold(
        tipo,
        slim["ui"],
        slim["regras"],
        template,
        consolidated=rag.get("consolidated") or "",
        engenharia=slim.get("engenharia") or {},
        servico=servico,
    )


@REGISTRY.register("reason")
def reason(ctx: StageContext) -> None:
    slot = ctx.slot()
    scan_report = scan_blobs(collect_untrusted_blobs(ctx.payload, slot))
    run_scan_path = ctx.run_ctx.validations_dir / "input-scan.json"
    ctx.write_json(run_scan_path, scan_report.to_dict())
    scan_path = run_scan_path
    if ctx.context_id:
        scan_path = ctx.run_ctx.context_validations_dir(ctx.context_id) / "input-scan.json"
        ctx.write_json(scan_path, scan_report.to_dict())
    slot["input_scan"] = scan_report.to_dict()
    slot["input_scan_path"] = str(scan_path)
    if scan_report.blocks:
        issues = [
            ValidationIssue(
                code=f.code,
                severity=f.severity,
                message=f.message,
                subject_id=f.source,
            )
            for f in scan_report.findings
        ]
        raise PipelineBlocked(
            ValidationResult(issues=issues),
            slot.get("spec"),
            discarded=list((slot.get("rag") or {}).get("discarded") or []),
            context=ctx.context_id,
            reason="input_scan_failed",
            report_path=str(scan_path),
        )

    artifacts: dict[str, str] = {}
    packages: dict[str, Path] = {}
    live_telemetry: dict[str, Any] | None = None
    artifacts_root = ctx.run_ctx.artifacts_dir
    claims = list((slot.get("rag") or {}).get("claims") or [])
    dry_run = bool(ctx.payload.get("dry_run", True))
    models_cfg = ctx.cfg.get("models") or {}
    provider = str(models_cfg.get("provider") or "openai")
    model = str(models_cfg.get("name") or "gpt-4o")
    for tipo, context_pkg in (slot.get("context_by_tipo") or {}).items():
        package = build_llm_package(
            context_pkg,
            claims=claims,
            run_id=ctx.run_ctx.run_id,
            scan_inputs=False,
        )
        pkg_name = f"llm_package_{tipo}.json"
        if ctx.context_id:
            pkg_path = ctx.run_ctx.context_artifacts_dir(ctx.context_id) / pkg_name
        else:
            pkg_path = artifacts_root / pkg_name
        if dry_run:
            # Pacote + scaffold locais: dry-run permanece o default sem API.
            ctx.write_json(pkg_path, package)
            artifacts[tipo] = _render_artifact(
                tipo,
                slot["slim_ctx"],
                slot["rag"],
                slot.get("spec"),
                True,
                slot.get("servico"),
            )
        else:
            # Chama a API antes de gravar artefato/pacote live — falha não
            # corrompe runs/<id>/ (nada parcial deste tipo é commitado).
            try:
                live = live_generate(
                    package,
                    provider=provider,
                    model=model,
                    claims=claims,
                )
            except LiveApiError as exc:
                raise StageError(f"--live falhou ({tipo}): {exc}") from exc
            telemetry = build_live_telemetry(_estimate_from_context(context_pkg), live)
            meta = package.setdefault("meta", {})
            if isinstance(meta, dict):
                meta["token_usage"] = telemetry
                meta["live"] = {
                    "provider": live.provider,
                    "model": live.model,
                    "response_id": live.response_id,
                    "tool_rounds": live.tool_rounds,
                    "cache_hit": live.usage.cache_hit_ratio,
                    "billable_tokens": live.usage.billable_tokens,
                }
            live_telemetry = telemetry
            ctx.write_json(pkg_path, package)
            artifacts[tipo] = live.text
        packages[tipo] = pkg_path
    slot["artifacts"] = artifacts
    slot["package_paths"] = packages
    if live_telemetry is not None:
        slot["live_token_usage"] = live_telemetry


def _gate_derived(ctx: StageContext, tipo: str, artifact: str) -> None:
    spec = ctx.slot().get("spec")
    if spec is None:
        return
    validation = validate_derived_artifact(tipo, artifact, spec)
    if not validation.issues:
        return
    if ctx.context_id:
        report_path = ctx.run_ctx.context_validations_dir(ctx.context_id) / f"{tipo}-validation.json"
    else:
        report_path = ctx.run_ctx.validations_dir / f"{tipo}-validation.json"
    ctx.write_json(report_path, validation.to_dict())
    if validation.has_errors:
        raise PipelineBlocked(
            validation,
            spec,
            context=ctx.context_id,
            reason="derived_artifact_divergence",
            report_path=str(report_path),
        )


@REGISTRY.register("emit")
def emit_stage(ctx: StageContext) -> None:
    slot = ctx.slot()
    outputs: dict[str, str] = {}
    packages: dict[str, str] = {}
    emit_root = ctx.run_ctx.run_dir
    for tipo, artifact in (slot.get("artifacts") or {}).items():
        _gate_derived(ctx, tipo, artifact)
        out = emit(
            tipo,
            artifact,
            context=ctx.context_id,
            root=emit_root,
            subdir="artifacts",
        )
        ctx.confine(out)
        outputs[tipo] = str(out)
        pkg = (slot.get("package_paths") or {}).get(tipo)
        if pkg is not None:
            packages[tipo] = str(pkg)
    spec_path = slot.get("spec_path")
    if spec_path is not None:
        outputs["canonical_spec"] = str(spec_path)
    tipo = ctx.payload["tipo"]
    context_pkg = slot.get("context_pkg") or {}
    rag = slot.get("rag") or {}
    validation = slot.get("validation")
    servico = slot.get("servico")
    spec = slot.get("spec")
    ns = ctx.context_id or (servico or {}).get("id") or "default"
    claims_out: list[dict[str, Any]] = []
    if spec is not None:
        for claim in spec.claims:
            payload = claim.to_dict()
            if not payload.get("service_id"):
                payload["service_id"] = (servico or {}).get("id")
            claims_out.append(stamp_claim_identity(payload, context=ns))
    else:
        for claim in rag.get("claims") or []:
            payload = dict(claim)
            if not payload.get("service_id"):
                payload["service_id"] = (servico or {}).get("id")
            claims_out.append(stamp_claim_identity(payload, context=ns))
    token_usage = slot.get("live_token_usage") or context_pkg.get("token_usage")
    task_metrics = dict(context_pkg.get("task_metrics") or {})
    if token_usage and isinstance(token_usage, dict):
        # live preenche billable — recalcula seção de custo sem marcar como fatura
        from src.task_metrics import build_task_metrics

        task_metrics = build_task_metrics(
            attempts=int(task_metrics.get("attempts") or getattr(ctx, "attempt", 1) or 1),
            duration_ms=task_metrics.get("duration_ms") or {},
            token_usage=token_usage,
            cost_usd=token_usage.get("cost_usd"),
            phases=task_metrics.get("phases") or {},
        )
    slot["result"] = {
        "context": ctx.context_id,
        "servico": {k: v for k, v in (servico or {}).items() if k != "indice"} or None,
        "indice_usado": bool((servico or {}).get("indice")),
        "output": outputs.get(tipo),
        "outputs": outputs,
        "llm_packages": packages,
        "est_tokens": context_pkg.get("est_tokens"),
        "est_tokens_method": context_pkg.get("est_tokens_method"),
        "token_usage": token_usage,
        "budget_report": context_pkg.get("budget_report"),
        "budget_status": context_pkg.get("budget_status"),
        "omissions": context_pkg.get("omissions") or [],
        "task_metrics": task_metrics,
        "rag": context_pkg.get("rag_stats"),
        "claims": claims_out,
        "discarded": list(rag.get("discarded") or []),
        "canonical_spec": str(spec_path) if spec_path else None,
        "validation": validation.to_dict() if validation is not None else None,
        "validation_report": str(slot["val_path"]) if slot.get("val_path") else None,
        "input_scan": slot.get("input_scan"),
        "input_scan_path": slot.get("input_scan_path"),
    }
