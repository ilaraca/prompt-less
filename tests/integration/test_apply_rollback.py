"""Apply em config versionada: snapshot, aceite e rollback por regressão."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from src.learning.accept import load_history
from src.learning.apply_rollback import (
    ApplyGateError,
    apply_change_to_config,
    apply_proposals_with_rollback,
    create_snapshot,
    resolve_config_target,
    restore_snapshot,
)
from src.runtime.config_load import load_merged_cfg

PIPELINE = Path(__file__).resolve().parents[2]


def _seed_root(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    shutil.copytree(PIPELINE / "config", root / "config")
    return root


def _low_proposal(**overrides) -> dict:
    base = {
        "id": "PROP-LOW-1",
        "playbook": "clarify_http_status",
        "risk": "low",
        "change": {"key": "validators.ambiguity.blocking", "value": True},
        "status": "proposed",
    }
    base.update(overrides)
    return base


def _suite_ok(workspace=None, pass_rate: float = 1.0):
    return {
        "cases": [
            {
                "case_id": "happy_path",
                "ok": pass_rate >= 1.0,
                "critical": True,
            }
        ],
        "summary": {
            "pass_rate": pass_rate,
            "avg_est_tokens": 100,
            "claim_recall": 1.0,
            "traceability_rate": 1.0,
            "unexpected_inferences": 0,
            "avg_latency_ms": 10.0,
            "http_status_match_rate": 1.0,
        },
        "workspace": workspace,
    }


def test_resolve_target_named_yaml_and_overlay(tmp_path: Path):
    root = _seed_root(tmp_path)
    path, key = resolve_config_target(root, "permission_profiles.enforce_deny")
    assert path.name == "permission_profiles.yaml"
    assert key == "enforce_deny"
    path2, key2 = resolve_config_target(root, "validators.ambiguity.blocking")
    assert path2.name == "proposal-overlay.yaml"
    assert key2 == "validators.ambiguity.blocking"


def test_snapshot_restores_exact_bytes(tmp_path: Path):
    root = _seed_root(tmp_path)
    target = root / "config" / "pipeline.yaml"
    before = target.read_bytes()
    snap = create_snapshot(root, [target], proposal_ids=["P1"])
    assert (snap.path / "manifest.json").is_file()
    target.write_text("broken: true\n", encoding="utf-8")
    assert target.read_bytes() != before
    restore_snapshot(root, snap)
    assert target.read_bytes() == before


def test_accept_applies_change_to_versioned_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _seed_root(tmp_path)
    calls: list[dict] = []

    def fake_suite(**kwargs):
        calls.append(kwargs)
        ws = kwargs.get("workspace")
        # baseline intact; candidate after apply sees merged overlay
        rate = 1.0
        return _suite_ok(ws, pass_rate=rate)

    monkeypatch.setattr(
        "src.learning.apply_rollback.run_eval_suite", fake_suite
    )
    proposals = [_low_proposal()]
    result = apply_proposals_with_rollback(
        proposals,
        root=root,
        eval_root=tmp_path / "evals",
        cases=["happy_path"],
    )
    assert result["status"] == "accepted"
    assert result["applied_ids"] == ["PROP-LOW-1"]
    assert result["restored"] is False
    overlay = root / "config" / "proposal-overlay.yaml"
    assert overlay.is_file()
    data = yaml.safe_load(overlay.read_text(encoding="utf-8"))
    assert data["validators"]["ambiguity"]["blocking"] is True
    merged = load_merged_cfg(root)
    assert merged["validators"]["ambiguity"]["blocking"] is True
    snap_id = result["snapshot"]["snapshot_id"]
    assert (root / "state" / "knowledge" / "snapshots" / snap_id / "manifest.json").is_file()
    hist = load_history(root)
    assert hist["accepted"]
    assert hist["accepted"][-1]["applied_to_production"] is True
    assert len(calls) == 2
    assert calls[0]["config_root"] == root
    assert calls[1]["workspace"]["snapshot_sha256"] != calls[0]["workspace"]["snapshot_sha256"]


def test_regression_rolls_back_and_rejects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _seed_root(tmp_path)
    overlay = root / "config" / "proposal-overlay.yaml"
    assert not overlay.exists()
    calls = {"n": 0}

    def fake_suite(**kwargs):
        calls["n"] += 1
        rate = 1.0 if calls["n"] == 1 else 0.0
        return _suite_ok(kwargs.get("workspace"), pass_rate=rate)

    monkeypatch.setattr(
        "src.learning.apply_rollback.run_eval_suite", fake_suite
    )
    result = apply_proposals_with_rollback(
        [_low_proposal()],
        root=root,
        eval_root=tmp_path / "evals",
        cases=["happy_path"],
    )
    assert result["status"] == "rejected"
    assert result["restored"] is True
    assert result["applied_ids"] == []
    assert not overlay.exists()
    hist = load_history(root)
    assert hist["rejected"]
    assert hist["rejected"][-1]["rolled_back"] is True


def test_medium_risk_requires_approval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _seed_root(tmp_path)
    monkeypatch.setattr(
        "src.learning.apply_rollback.run_eval_suite",
        lambda **kwargs: _suite_ok(kwargs.get("workspace")),
    )
    medium = _low_proposal(
        id="PROP-MED",
        risk="medium",
        change={"key": "repair.focus", "value": "tests"},
    )
    with pytest.raises(ApplyGateError, match="medium"):
        apply_proposals_with_rollback(
            [medium],
            root=root,
            eval_root=tmp_path / "evals",
            cases=["happy_path"],
        )

    monkeypatch.setattr(
        "src.learning.apply_rollback.assert_promotable",
        lambda run_dir, run_id: {"id": "apr-1", "decision": "approved"},
    )
    result = apply_proposals_with_rollback(
        [medium],
        root=root,
        eval_root=tmp_path / "evals",
        cases=["happy_path"],
        run_dir=tmp_path / "runs" / "r1",
        run_id="r1",
    )
    assert result["status"] == "accepted"
    assert result["approval_id"] == "apr-1"


def test_apply_change_to_named_config_file(tmp_path: Path):
    root = _seed_root(tmp_path)
    path = apply_change_to_config(root, "permission_profiles.enforce_deny", True)
    assert path.name == "permission_profiles.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["enforce_deny"] is True


def test_cli_apply_accept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from src.apply import main

    root = _seed_root(tmp_path)
    prop = tmp_path / "prop.json"
    prop.write_text(json.dumps(_low_proposal()), encoding="utf-8")
    monkeypatch.setattr(
        "src.learning.apply_rollback.run_eval_suite",
        lambda **kwargs: _suite_ok(kwargs.get("workspace")),
    )
    main(
        [
            "--root",
            str(root),
            "--proposal-json",
            str(prop),
            "--cases",
            "happy_path",
            "--out",
            str(tmp_path / "evals"),
        ]
    )
    assert (root / "config" / "proposal-overlay.yaml").is_file()
