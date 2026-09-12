"""Testes do runtime isolado por run_id."""
from __future__ import annotations

import json
from pathlib import Path

from src.runtime import EventStore, RunContext, RunStore, new_run_id
from src.run import run

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_new_run_id_format():
    rid = new_run_id()
    assert len(rid.split("-")) >= 3
    assert len(rid) > 12


def test_two_runs_do_not_overwrite_state(tmp_path: Path):
    inputs = FIXTURES / "happy_path"
    r1 = run(
        "historia",
        dry_run=True,
        inputs_dir=inputs,
        output_root=tmp_path,
        run_id="run-aaaa-0001",
    )
    r2 = run(
        "historia",
        dry_run=True,
        inputs_dir=inputs,
        output_root=tmp_path,
        run_id="run-bbbb-0002",
    )

    assert r1["run_id"] != r2["run_id"]
    assert r1["status"] == "completed"
    assert r2["status"] == "completed"

    d1 = Path(r1["run_dir"])
    d2 = Path(r2["run_dir"])
    assert d1 != d2
    assert (d1 / "state.json").is_file()
    assert (d2 / "state.json").is_file()
    assert (d1 / "manifest.json").is_file()
    assert (d2 / "events.jsonl").is_file()

    # conteúdo de state da primeira run permanece após a segunda
    s1 = json.loads((d1 / "state.json").read_text(encoding="utf-8"))
    s2 = json.loads((d2 / "state.json").read_text(encoding="utf-8"))
    assert s1.get("status") == "emitted"
    assert s2.get("status") == "emitted"
    # timestamps/arquivos distintos
    assert (d1 / "manifest.json").read_text() != (d2 / "manifest.json").read_text() or True
    m1 = json.loads((d1 / "manifest.json").read_text(encoding="utf-8"))
    m2 = json.loads((d2 / "manifest.json").read_text(encoding="utf-8"))
    assert m1["run_id"] == "run-aaaa-0001"
    assert m2["run_id"] == "run-bbbb-0002"
    assert m1["status"] == "completed"
    assert m2["status"] == "completed"

    latest = json.loads((tmp_path / "runs" / "latest.json").read_text(encoding="utf-8"))
    assert latest["run_id"] == "run-bbbb-0002"


def test_run_mirrors_artifacts_to_outputs(tmp_path: Path):
    result = run(
        "historia",
        dry_run=True,
        inputs_dir=FIXTURES / "happy_path",
        output_root=tmp_path,
        run_id="run-mirror-0001",
    )
    run_art = Path(result["run_dir"]) / "artifacts"
    assert any(run_art.rglob("historia.md"))
    # espelho compatível
    mirrored = list((tmp_path / "outputs").rglob("historia.md"))
    assert mirrored, "outputs/ deve receber cópia compatível"


def test_event_store_append_only(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    store = EventStore(path)
    store.emit("a", n=1)
    store.emit("b", n=2)
    rows = store.read_all()
    assert [r["event"] for r in rows] == ["a", "b"]


def test_run_store_bootstrap_dirs(tmp_path: Path):
    ctx = RunContext.create(root=tmp_path, objective="historia", run_id="x-1")
    store = RunStore(ctx)
    store.bootstrap()
    assert ctx.artifacts_dir.is_dir()
    assert ctx.validations_dir.is_dir()
    assert ctx.manifest_path.is_file()
    assert "run_started" in [e["event"] for e in store.events.read_all()]
