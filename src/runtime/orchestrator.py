"""Orquestra o grafo de estágios: retry, timeout, gates, retomada, cancelamento."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from pathlib import Path
from typing import Any

from src.runtime.checkpoint import (
    CHECKPOINT_SCHEMA_VERSION,
    CheckpointStore,
    hash_input_files,
    json_hash,
)
from src.runtime.graph import StageSpec, load_stage_graph
from src.runtime.handlers import default_registry
from src.runtime.run_store import RunStore
from src.runtime.atomic_io import UnsafePath
from src.runtime.stage import (
    GraphError,
    HandlerRegistry,
    HashMismatch,
    StageContext,
    StageError,
    StageTimeout,
)
from src.validators import PipelineBlocked, ValidationResult

_NO_RETRY = (
    PipelineBlocked,
    HashMismatch,
    GraphError,
    UnsafePath,
    KeyboardInterrupt,
    SystemExit,
    GeneratorExit,
)


class Orchestrator:
    def __init__(
        self,
        stages: list[StageSpec],
        store: RunStore,
        registry: HandlerRegistry,
        cfg: dict[str, Any],
    ) -> None:
        self.stages = stages
        self.store = store
        self.registry = registry
        self.cfg = cfg
        self.checkpoints = CheckpointStore(store.ctx)
        self._current: tuple[str, str | None] | None = None

    @classmethod
    def from_cfg(
        cls,
        cfg: dict[str, Any],
        store: RunStore,
        registry: HandlerRegistry | None = None,
    ) -> "Orchestrator":
        reg = registry or default_registry()
        return cls(load_stage_graph(cfg, reg), store, reg, cfg)

    def execute(self, payload: dict[str, Any], *, resume: bool = False) -> dict[str, Any]:
        self.checkpoints.ensure_dir()
        self.store.write_manifest(
            {
                "checkpoint_schema_version": CHECKPOINT_SCHEMA_VERSION,
                "current_stage": "graph",
            }
        )
        if resume:
            self.checkpoints.migrate_from_events(self.store)
            self._validate_resume_hashes(payload)
        try:
            for spec in self.stages:
                if not spec.enabled:
                    self.store.events.emit(
                        "stage_skipped", stage=spec.id, reason="disabled"
                    )
                    continue
                if spec.is_foreach_context:
                    self._run_foreach(spec, payload)
                else:
                    self._run_one(spec, payload, context_id=None)
            return payload
        except KeyboardInterrupt:
            self._leave_consistent("cancelled", reason="keyboard_interrupt")
            raise

    def _run_foreach(self, spec: StageSpec, payload: dict[str, Any]) -> None:
        targets = payload.get("targets")
        if not targets:
            targets = [None]
        blocked = set(payload.get("blocked_contexts") or [])
        for context_id in targets:
            key = _ctx_key(context_id)
            if key in blocked:
                self.store.events.emit(
                    "stage_skipped",
                    stage=spec.id,
                    context=context_id,
                    reason="context_blocked",
                )
                continue
            try:
                self._run_one(spec, payload, context_id=context_id)
            except PipelineBlocked as exc:
                self._record_blocked(payload, context_id, exc)
                blocked.add(key)
                payload["blocked_contexts"] = sorted(blocked, key=lambda x: x or "")
                # demais contextos seguem (mesmo comportamento do loop legado)
                continue

    def _run_one(
        self, spec: StageSpec, payload: dict[str, Any], *, context_id: str | None
    ) -> None:
        self._current = (spec.id, context_id)
        self.store.write_manifest(
            {"current_stage": spec.id, "service_id": context_id}
        )
        hashes = _run_input_hashes(payload)
        self.checkpoints.write(
            spec.id,
            status="running",
            context_id=context_id,
            input_hashes=hashes,
        )
        ctx = StageContext(
            stage_id=spec.id,
            run_ctx=self.store.ctx,
            store=self.store,
            cfg=self.cfg,
            payload=payload,
            context_id=context_id,
        )
        handler = self.registry.get(spec.handler)
        attempts = 1 + int(spec.retry)
        last_exc: BaseException | None = None
        for attempt in range(1, attempts + 1):
            ctx.attempt = attempt
            self.store.events.emit(
                "stage_started",
                stage=spec.id,
                context=context_id,
                attempt=attempt,
            )
            try:
                self._invoke(handler, ctx, spec.timeout_s)
                last_exc = None
                break
            except _NO_RETRY:
                raise
            except StageTimeout as exc:
                last_exc = exc
                self.store.events.emit(
                    "stage_timeout",
                    stage=spec.id,
                    context=context_id,
                    attempt=attempt,
                    timeout_s=spec.timeout_s,
                )
                if attempt >= attempts:
                    self.checkpoints.write(
                        spec.id,
                        status="failed",
                        context_id=context_id,
                        attempt=attempt,
                        extra={"error": str(exc)},
                    )
                    raise
            except Exception as exc:
                last_exc = exc
                self.store.events.emit(
                    "stage_failed",
                    stage=spec.id,
                    context=context_id,
                    attempt=attempt,
                    error=str(exc),
                )
                if attempt >= attempts:
                    self.checkpoints.write(
                        spec.id,
                        status="failed",
                        context_id=context_id,
                        attempt=attempt,
                        extra={"error": str(exc)},
                    )
                    raise StageError(
                        f"estágio {spec.id!r} falhou após {attempts} tentativa(s): {exc}"
                    ) from exc
        if last_exc is not None:
            raise last_exc
        self._apply_gates(spec, ctx)
        self.checkpoints.write(
            spec.id,
            status="completed",
            context_id=context_id,
            input_hashes=hashes,
            attempt=ctx.attempt,
        )
        self.store.events.emit(
            "stage_completed", stage=spec.id, context=context_id
        )

    def _invoke(self, handler, ctx: StageContext, timeout_s: float | None) -> Any:
        if timeout_s is None:
            return handler(ctx)
        pool = ThreadPoolExecutor(max_workers=1)
        fut = pool.submit(handler, ctx)
        try:
            return fut.result(timeout=timeout_s)
        except FuturesTimeout as exc:
            raise StageTimeout(
                f"estágio {ctx.stage_id!r} excedeu timeout de {timeout_s}s"
            ) from exc
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _apply_gates(self, spec: StageSpec, ctx: StageContext) -> None:
        slot = ctx.slot()
        for gate in spec.gates:
            if not _gate_fired(gate.when, ctx.payload, slot):
                continue
            self.store.events.emit(
                "gate_blocked",
                stage=spec.id,
                context=ctx.context_id,
                when=gate.when,
            )
            validation = slot.get("validation") or ctx.payload.get("validation")
            if not isinstance(validation, ValidationResult):
                validation = ValidationResult()
            raise PipelineBlocked(
                validation,
                slot.get("spec"),
                discarded=list((slot.get("rag") or {}).get("discarded") or []),
                context=ctx.context_id,
            )

    def _record_blocked(
        self,
        payload: dict[str, Any],
        context_id: str | None,
        exc: PipelineBlocked,
    ) -> None:
        ctx = StageContext(
            stage_id=(self._current or ("gate", None))[0],
            run_ctx=self.store.ctx,
            store=self.store,
            cfg=self.cfg,
            payload=payload,
            context_id=context_id,
        )
        slot = ctx.slot()
        slot["blocked"] = True
        slot["blocked_payload"] = blocked_payload(exc, ctx)
        slot["spec"] = exc.spec
        slot["validation"] = exc.validation
        self.checkpoints.write(
            ctx.stage_id,
            status="blocked",
            context_id=context_id,
            extra={"reason": exc.reason},
        )
        self.store.events.emit(
            "validation.failed",
            errors=len(exc.validation.errors),
            context=context_id or exc.context,
        )

    def _validate_resume_hashes(self, payload: dict[str, Any]) -> None:
        current = _run_input_hashes(payload)
        found = False
        for path in sorted(self.checkpoints.dir.glob("*.json")):
            stem = path.stem
            if "::" in stem:
                stage_id, context_id = stem.split("::", 1)
            else:
                stage_id, context_id = stem, None
            data = self.checkpoints.read(stage_id, context_id)
            if not data:
                continue
            found = True
            stored = data.get("input_hashes") or {}
            if not stored or data.get("migrated"):
                self.checkpoints.write(
                    data.get("stage_id") or path.stem,
                    status=str(data.get("status") or "completed"),
                    context_id=data.get("context_id"),
                    input_hashes=current,
                    extra={"migrated": data.get("migrated"), "hashes_adopted": True},
                )
                continue
            if stored.get("files") != current["files"]:
                raise HashMismatch(
                    f"hash das entradas da run '{self.store.ctx.run_id}' não "
                    f"coincide com o checkpoint {path.name}"
                )
            if stored.get("params") and stored.get("params") != current["params"]:
                raise HashMismatch(
                    f"parâmetros da run '{self.store.ctx.run_id}' não coincidem "
                    f"com o checkpoint {path.name}"
                )
        if not found:
            # run antiga sem checkpoints: migração já tentou; se ainda vazio, segue
            return

    def _leave_consistent(self, status: str, *, reason: str) -> None:
        if self._current:
            stage_id, context_id = self._current
            self.checkpoints.write(
                stage_id,
                status="failed" if status == "cancelled" else status,
                context_id=context_id,
                extra={"cancelled": status == "cancelled", "reason": reason},
            )
        if not self.store.is_finished:
            self.store.finish(status)


def blocked_payload(exc: PipelineBlocked, ctx: StageContext) -> dict[str, Any]:
    sid = exc.context or ctx.context_id
    if exc.report_path:
        report = Path(exc.report_path)
    elif sid:
        report = ctx.run_ctx.context_validations_dir(sid) / "spec-validation.json"
    else:
        report = ctx.run_ctx.validations_dir / "spec-validation.json"
    claims = [claim.to_dict() for claim in exc.spec.claims] if exc.spec else []
    return {
        "context": sid,
        "status": "blocked",
        "reason": exc.reason,
        "validation": exc.validation.to_dict(),
        "report": str(report) if report.exists() else None,
        "questions": [i.message for i in exc.validation.errors],
        "claims": claims,
        "discarded": list(exc.discarded or []),
        "canonical_spec_service": exc.spec.service_id if exc.spec else None,
        "outputs": {},
        "output": None,
    }


def build_run_result(payload: dict[str, Any]) -> dict[str, Any]:
    per = payload.get("per_context") or {}
    split = bool(payload.get("split"))
    targets = payload.get("targets") or [None]
    docs = payload.get("docs_ingested") or []
    if split:
        by_context = []
        all_outputs: dict[str, Any] = {}
        any_blocked = False
        for sid in targets:
            slot = per.get(_ctx_key(sid)) or {}
            if slot.get("blocked"):
                any_blocked = True
                one = dict(slot.get("blocked_payload") or {})
            else:
                one = dict(slot.get("result") or {})
            by_context.append(one)
            all_outputs[sid] = one.get("outputs") or {}
        return {
            "split": True,
            "contexts": targets,
            "by_context": by_context,
            "outputs": all_outputs,
            "output": by_context[0].get("output") if by_context else None,
            "docs_ingested": docs,
            "partition_preview": payload.get("partition_preview") or {},
            "_blocked": any_blocked,
        }

    slot = per.get("") or {}
    if slot.get("blocked"):
        result = dict(slot.get("blocked_payload") or {})
        result["split"] = False
        result["docs_ingested"] = docs
        if payload.get("hint"):
            result["hint"] = payload["hint"]
            result["mapa"] = True
        result["_blocked"] = True
        return result
    result = dict(slot.get("result") or {})
    result["split"] = False
    result["docs_ingested"] = docs
    if payload.get("hint"):
        result["hint"] = payload["hint"]
        result["mapa"] = True
    result["_blocked"] = False
    return result


def _ctx_key(context_id: str | None) -> str:
    return context_id if context_id is not None else ""


def _run_input_hashes(payload: dict[str, Any]) -> dict[str, Any]:
    inputs_dir = payload.get("inputs_dir")
    return {
        "files": hash_input_files(Path(inputs_dir) if inputs_dir else None),
        "params": json_hash(
            {
                "tipo": payload.get("tipo"),
                "dry_run": payload.get("dry_run"),
                "no_split": payload.get("no_split"),
                "requested_context": payload.get("requested_context"),
                "all_contexts": payload.get("all_contexts"),
            }
        ),
    }


def _gate_fired(expr: str, payload: dict[str, Any], slot: dict[str, Any]) -> bool:
    """Lookup pontilhado fail-closed (sem eval). Ausente → não dispara."""
    parts = [p for p in expr.split(".") if p]
    if not parts:
        return False
    for root in (slot, payload):
        cur: Any = root
        ok = True
        for part in parts:
            if isinstance(cur, dict):
                if part not in cur:
                    ok = False
                    break
                cur = cur[part]
            else:
                if not hasattr(cur, part):
                    ok = False
                    break
                cur = getattr(cur, part)
        if ok:
            return bool(cur)
    return False
