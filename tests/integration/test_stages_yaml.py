"""Orquestração declarativa via pipeline.yaml: grafo, gates, resume, sandbox."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
import yaml

from src.ingest import load_inputs
from src.runtime.run import load_cfg, run
from src.runtime import (
    GraphError,
    HandlerRegistry,
    HashMismatch,
    Orchestrator,
    RunContext,
    RunStore,
    StageContext,
    StageError,
    StageTimeout,
    default_registry,
    load_stage_graph,
)
from src.runtime.atomic_io import UnsafePath
from src.runtime.checkpoint import CHECKPOINT_SCHEMA_VERSION, CheckpointStore
from src.runtime.handlers import REGISTRY
from src.validators import ValidationIssue, ValidationResult

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _store(tmp_path: Path, run_id: str = "orch-1") -> RunStore:
    ctx = RunContext.create(root=tmp_path, objective="historia", run_id=run_id)
    store = RunStore(ctx)
    store.bootstrap()
    return store


def _mini_cfg(stages: list[dict]) -> dict:
    return {"stages": stages, "version": "1.0"}


# ------------------------------------------------------------------ grafo / protocol


def test_default_yaml_is_executable_graph():
    cfg = load_cfg()
    graph = load_stage_graph(cfg, default_registry())
    enabled = [s.id for s in graph if s.enabled]
    assert enabled[:3] == ["ingest", "preprocess", "servicos_split"]
    assert "canonical_spec" in enabled
    assert enabled[-1] == "emit"
    spec_gate = next(s for s in graph if s.id == "canonical_spec")
    assert spec_gate.gates[0].when == "validation.has_errors"
    assert spec_gate.gates[0].then == "blocked"
    optional = [s.id for s in graph if s.optional]
    assert set(optional) == {"repos_scan", "repo_index", "marcar"}
    assert all(not s.enabled for s in graph if s.optional)


def test_graph_rejects_cycle():
    reg = HandlerRegistry()
    reg.register("a", lambda ctx: None)
    reg.register("b", lambda ctx: None)
    with pytest.raises(GraphError, match="ciclo"):
        load_stage_graph(
            _mini_cfg(
                [
                    {"id": "a", "handler": "a", "depends_on": ["b"]},
                    {"id": "b", "handler": "b", "depends_on": ["a"]},
                ]
            ),
            reg,
        )


def test_graph_unknown_handler_is_fail_closed():
    reg = HandlerRegistry()
    with pytest.raises(GraphError, match="ausente"):
        load_stage_graph(_mini_cfg([{"id": "x", "handler": "nao-existe"}]), reg)


def test_isolated_stage_preprocess(tmp_path: Path):
    store = _store(tmp_path, "iso-prep-1")
    raw = load_inputs("historia", inputs_dir=FIXTURES / "happy_path")
    ctx = StageContext(
        stage_id="preprocess",
        run_ctx=store.ctx,
        store=store,
        cfg={},
        payload={"raw": raw, "tipo": "historia"},
    )
    REGISTRY.get("preprocess")(ctx)
    slim = ctx.payload["slim"]
    assert slim["ui"]["inputs"]
    assert slim["regras"]["fluxo"]
    REGISTRY.get("preprocess")(ctx)
    assert ctx.payload["slim"] == slim


# -------------------------------------------------------------- retry / timeout / gate


def test_retry_then_success(tmp_path: Path):
    hits = {"n": 0}
    reg = HandlerRegistry()

    @reg.register("flaky")
    def flaky(ctx: StageContext) -> None:
        hits["n"] += 1
        if hits["n"] < 3:
            raise RuntimeError("ainda nao")
        ctx.payload["ok"] = True

    store = _store(tmp_path, "retry-1")
    orch = Orchestrator.from_cfg(
        _mini_cfg([{"id": "flaky", "handler": "flaky", "retry": 2}]),
        store,
        registry=reg,
    )
    orch.execute({"tipo": "historia"})
    assert hits["n"] == 3
    assert orch.checkpoints.read("flaky")["status"] == "completed"
    assert orch.checkpoints.read("flaky")["schema_version"] == CHECKPOINT_SCHEMA_VERSION


def test_timeout_fails_stage(tmp_path: Path):
    reg = HandlerRegistry()

    @reg.register("slow")
    def slow(_ctx: StageContext) -> None:
        time.sleep(0.4)

    store = _store(tmp_path, "timeout-1")
    orch = Orchestrator.from_cfg(
        _mini_cfg([{"id": "slow", "handler": "slow", "timeout_s": 0.05}]),
        store,
        registry=reg,
    )
    with pytest.raises(StageTimeout, match="timeout"):
        orch.execute({"tipo": "historia"})
    assert orch.checkpoints.read("slow")["status"] == "failed"


def test_gate_validation_has_errors_blocks(tmp_path: Path):
    reg = HandlerRegistry()

    @reg.register("check")
    def check(ctx: StageContext) -> None:
        ctx.slot()["validation"] = ValidationResult(
            issues=[
                ValidationIssue(
                    code="X", severity="error", message="entrada inválida"
                )
            ]
        )

    store = _store(tmp_path, "gate-1")
    orch = Orchestrator.from_cfg(
        _mini_cfg(
            [
                {
                    "id": "check",
                    "handler": "check",
                    "gates": [{"when": "validation.has_errors", "then": "blocked"}],
                    "foreach": "context",
                }
            ]
        ),
        store,
        registry=reg,
    )
    payload = {"tipo": "historia", "targets": [None]}
    orch.execute(payload)
    slot = payload["per_context"][""]
    assert slot["blocked"] is True
    assert slot["blocked_payload"]["status"] == "blocked"


def test_cancellation_writes_consistent_manifest(tmp_path: Path):
    reg = HandlerRegistry()

    @reg.register("die")
    def die(_ctx: StageContext) -> None:
        raise KeyboardInterrupt()

    store = _store(tmp_path, "cancel-1")
    orch = Orchestrator.from_cfg(
        _mini_cfg([{"id": "die", "handler": "die"}]), store, registry=reg
    )
    with pytest.raises(KeyboardInterrupt):
        orch.execute({"tipo": "historia"})
    manifest = store.read_manifest()
    assert manifest["status"] == "cancelled"
    assert manifest["run_id"] == "cancel-1"
    assert isinstance(manifest["version"], int)
    ckpt = orch.checkpoints.read("die")
    assert ckpt["cancelled"] is True


def test_handler_cannot_write_outside_run_dir(tmp_path: Path):
    reg = HandlerRegistry()
    fora = tmp_path / "escape.txt"

    @reg.register("escape")
    def escape(ctx: StageContext) -> None:
        ctx.write_text(fora, "nao")

    store = _store(tmp_path, "sandbox-1")
    orch = Orchestrator.from_cfg(
        _mini_cfg([{"id": "escape", "handler": "escape"}]), store, registry=reg
    )
    with pytest.raises(UnsafePath):
        orch.execute({"tipo": "historia"})
    assert not fora.exists()


# ----------------------------------------------------- run_id / resume / migração


def _registry_with(preprocess_handler) -> HandlerRegistry:
    reg = HandlerRegistry()
    src = default_registry()
    for name in src.names():
        if name != "preprocess":
            reg.register(name, src.get(name))
    reg.register("preprocess", preprocess_handler)
    return reg


def test_intermediate_failure_does_not_lose_run_id(tmp_path: Path):
    def boom(_ctx: StageContext) -> None:
        raise RuntimeError("falha injetada no preprocess")

    with pytest.raises(StageError, match="preprocess"):
        run(
            "historia",
            dry_run=True,
            inputs_dir=FIXTURES / "happy_path",
            output_root=tmp_path,
            run_id="fail-mid-1",
            registry=_registry_with(boom),
        )
    run_dir = tmp_path / "runs" / "fail-mid-1"
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_id"] == "fail-mid-1"
    assert manifest["status"] == "failed"
    events = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "stage_completed" in events  # ingest sobreviveu
    assert '"stage": "ingest"' in events


def test_resume_from_checkpoint_completes_same_run(tmp_path: Path):
    hits = {"n": 0}
    original = default_registry().get("preprocess")

    def flaky(ctx: StageContext) -> None:
        hits["n"] += 1
        if hits["n"] == 1:
            raise RuntimeError("falha transitória")
        original(ctx)

    kwargs = dict(
        tipo="historia",
        dry_run=True,
        inputs_dir=FIXTURES / "happy_path",
        output_root=tmp_path,
        run_id="resume-1",
        registry=_registry_with(flaky),
    )
    with pytest.raises(StageError):
        run(**kwargs)
    result = run(**kwargs, resume=True)
    assert result["run_id"] == "resume-1"
    assert result["status"] == "completed"
    ckpt = json.loads(
        (Path(result["run_dir"]) / "checkpoints" / "ingest.json").read_text(
            encoding="utf-8"
        )
    )
    assert ckpt["schema_version"] == CHECKPOINT_SCHEMA_VERSION
    assert ckpt["input_hashes"]["files"]


def test_resume_rejects_hash_mismatch(tmp_path: Path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for src in (FIXTURES / "happy_path").iterdir():
        dest = inputs / src.name
        if src.is_file():
            dest.write_bytes(src.read_bytes())

    hits = {"n": 0}

    def boom(_ctx: StageContext) -> None:
        hits["n"] += 1
        raise RuntimeError("para no preprocess")

    kwargs = dict(
        tipo="historia",
        dry_run=True,
        inputs_dir=inputs,
        output_root=tmp_path,
        run_id="hash-1",
        registry=_registry_with(boom),
    )
    with pytest.raises(StageError):
        run(**kwargs)
    (inputs / "regras.yaml").write_text("fluxo: adulterado\n", encoding="utf-8")
    with pytest.raises(HashMismatch):
        run(**kwargs, resume=True)


def test_migrate_old_events_without_checkpoints(tmp_path: Path):
    store = _store(tmp_path, "legacy-1")
    store.events.emit("stage_completed", stage="ingest")
    store.events.emit("stage_completed", stage="preprocess")
    ckpt = CheckpointStore(store.ctx)
    migrated = ckpt.migrate_from_events(store)
    assert migrated == ["ingest", "preprocess"]
    data = ckpt.read("ingest")
    assert data["schema_version"] == CHECKPOINT_SCHEMA_VERSION
    assert data["migrated"] is True
    assert ckpt.migrate_from_events(store) == []  # idempotente


def test_default_yaml_happy_path_still_emits(tmp_path: Path):
    result = run(
        "historia",
        dry_run=True,
        inputs_dir=FIXTURES / "happy_path",
        output_root=tmp_path,
        run_id="yaml-happy-1",
    )
    assert result["status"] == "completed"
    assert result["run_id"] == "yaml-happy-1"
    run_dir = Path(result["run_dir"])
    ckpts = list((run_dir / "checkpoints").glob("emit*.json"))
    assert ckpts, "emit deve gravar checkpoint (por contexto quando há split)"
    assert yaml.safe_load(ckpts[0].read_text(encoding="utf-8"))[
        "schema_version"
    ] == CHECKPOINT_SCHEMA_VERSION
    spec_ckpts = list((run_dir / "checkpoints").glob("canonical_spec*.json"))
    assert spec_ckpts
    assert yaml.safe_load(spec_ckpts[0].read_text(encoding="utf-8"))[
        "schema_version"
    ] == CHECKPOINT_SCHEMA_VERSION
    events = [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    completed = [e.get("stage") for e in events if e.get("event") == "stage_completed"]
    assert "ingest" in completed
    assert "preprocess" in completed
    assert "emit" in completed
    assert "repos_scan" not in completed
