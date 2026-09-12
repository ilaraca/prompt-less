"""Canonical Spec: IR, validação, render alinhado, gate de ambiguidade."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from src.run import run
from src.spec.builder import build_canonical_spec
from src.validators import validate_spec

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_happy_path_writes_canonical_spec(tmp_path: Path):
    result = run(
        "historia",
        dry_run=True,
        inputs_dir=FIXTURES / "happy_path",
        output_root=tmp_path,
        run_id="spec-happy-1",
    )
    assert result["status"] == "completed"
    specs = list(tmp_path.rglob("canonical-spec.yaml"))
    assert specs, "deve emitir canonical-spec.yaml"
    data = yaml.safe_load(specs[0].read_text(encoding="utf-8"))
    assert data["spec_version"] == "1.0"
    assert data["requirements"]
    assert data["acceptance_criteria"]
    for ac in data["acceptance_criteria"]:
        assert ac["requirement_id"] in {r["id"] for r in data["requirements"]}


def test_prd_and_historia_share_same_ac_ids(tmp_path: Path):
    result = run(
        "historia",
        dry_run=True,
        inputs_dir=FIXTURES / "happy_path",
        output_root=tmp_path,
        run_id="spec-align-1",
    )
    assert result["status"] == "completed"
    historias = list(tmp_path.rglob("historia.md"))
    prds = list(tmp_path.rglob("PRD.md"))
    assert historias and prds
    h = historias[0].read_text(encoding="utf-8")
    p = prds[0].read_text(encoding="utf-8")
    # IDs AC do spec devem aparecer nos dois artefatos
    spec = yaml.safe_load(next(tmp_path.rglob("canonical-spec.yaml")).read_text(encoding="utf-8"))
    for ac in spec["acceptance_criteria"]:
        assert ac["id"] in h
        assert ac["id"] in p
    for rf in spec["requirements"]:
        # RF aparece no PRD; história referencia via AC
        assert rf["id"] in p or any(ac["requirement_id"] == rf["id"] and ac["id"] in h for ac in spec["acceptance_criteria"])


def test_ambiguous_fixture_blocked(tmp_path: Path):
    result = run(
        "historia",
        dry_run=True,
        inputs_dir=FIXTURES / "ambiguous_status",
        output_root=tmp_path,
        run_id="spec-amb-1",
    )
    assert result["status"] == "blocked"
    assert result.get("reason") == "spec_validation_failed" or any(
        (c.get("status") == "blocked") for c in (result.get("by_context") or [])
    )
    reports = list(tmp_path.rglob("spec-validation.json"))
    assert reports
    data = json.loads(reports[0].read_text(encoding="utf-8"))
    assert data["status"] == "blocked"
    assert data["errors"] >= 1
    assert any(i["code"] == "AMBIGUOUS_HTTP_STATUS" for i in data["issues"])


def test_validate_rejects_ac_without_rf():
    spec = build_canonical_spec(
        ui={"actions": []},
        regras={"bloqueios": [{"trigger": "x", "status": 400}]},
        claims=[{"id": "CLM-1", "text": "x 400", "origin": "declared", "confidence": 1.0, "sources": [{"document": "r.yaml"}]}],
    )
    # corrompe AC
    spec.acceptance_criteria[0].requirement_id = "RF-999"
    result = validate_spec(spec)
    assert result.has_errors
    assert any(i.code == "AC_UNKNOWN_REQUIREMENT" for i in result.errors)
