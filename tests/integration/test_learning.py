"""Autoaperfeiçoamento controlado: patterns, propostas, evals, aceite."""
from __future__ import annotations

import json
from pathlib import Path

from src.learning.accept import decide_proposals, load_history
from src.learning.evals import compare_evals, run_eval_suite
from src.learning.failure_patterns import classify_issues, diagnose_verify_report
from src.learning.proposals import build_proposals


def test_classify_ambiguous():
    issues = [{"code": "AMBIGUOUS_HTTP_STATUS", "severity": "error"}]
    matched = classify_issues(issues)
    assert matched
    assert matched[0]["pattern_id"] == "FP-AMBIGUOUS_STATUS"
    assert matched[0]["probable_owner"] == "canonical_spec"


def test_diagnose_and_propose():
    report = {
        "verify": {
            "status": "failed",
            "issues": [
                {"code": "RF_NOT_MAPPED", "severity": "error"},
                {"code": "FILE_OUT_OF_SCOPE", "severity": "error"},
            ],
        }
    }
    diag = diagnose_verify_report(report)
    assert diag["failure"]["patterns"]
    props = build_proposals(diag)
    assert props
    assert all(p["status"] == "proposed" for p in props)


def test_compare_evals_detects_regression():
    baseline = {"summary": {"pass_rate": 1.0, "avg_est_tokens": 100}}
    worse = {"summary": {"pass_rate": 0.5, "avg_est_tokens": 100}}
    cmp = compare_evals(baseline, worse)
    assert cmp["regression"] is True
    assert cmp["decision"] == "reject"

    costly = {"summary": {"pass_rate": 1.0, "avg_est_tokens": 200}}
    cmp2 = compare_evals(baseline, costly)
    assert cmp2["regression"] is True


def test_decide_rejects_on_regression(tmp_path: Path):
    proposals = [
        {
            "id": "PROP-1",
            "playbook": "clarify_http_status",
            "risk": "low",
            "change": {"key": "x", "value": True},
        }
    ]
    comparison = {"regression": True, "decision": "reject", "reasons": ["pass_rate_decreased"]}
    result = decide_proposals(proposals, comparison, root=tmp_path)
    assert result["accepted"] == []
    assert result["rejected"]
    hist = load_history(tmp_path)
    assert len(hist["rejected"]) >= 1


def test_decide_accepts_low_risk_without_regression(tmp_path: Path):
    proposals = [
        {
            "id": "PROP-2",
            "playbook": "human_gate",
            "risk": "low",
            "change": {"key": "approval.auto", "value": False},
        }
    ]
    comparison = {"regression": False, "decision": "accept", "reasons": []}
    result = decide_proposals(proposals, comparison, root=tmp_path)
    assert len(result["approved_for_experiment"]) == 1
    assert result["approved_for_experiment"][0]["status"] == "approved_for_experiment"
    assert result["rejected"] == []
    # alias legado
    assert len(result["accepted"]) == 1


def test_eval_suite_smoke(tmp_path: Path):
    # só happy_path para ficar rápido
    report = run_eval_suite(cases=["happy_path"], output_root=tmp_path)
    assert report["summary"]["total"] == 1
    assert report["summary"]["passed"] == 1
    score = report["cases"][0]["score"]
    assert score["service_match"] is True
    assert score["expected_status_match"] is True
    assert score["signals_present"] is True


def test_confidence_zero_preserved():
    from src.spec.builder import build_canonical_spec

    spec = build_canonical_spec(
        ui={},
        regras={"bloqueios": [{"trigger": "x", "status": 400}]},
        claims=[
            {
                "id": "CLM-Z",
                "text": "x HTTP 400",
                "origin": "declared",
                "confidence": 0.0,
                "sources": [{"document": "t"}],
            }
        ],
    )
    claim = next(c for c in spec.claims if c.id == "CLM-Z")
    assert claim.confidence == 0.0


def test_unknown_source_claim_blocked():
    from src.domain.claim import Claim, ClaimOrigin
    from src.domain.spec import CanonicalSpec, Requirement
    from src.validators import validate_spec

    spec = CanonicalSpec(
        version="1.0",
        service_id="default",
        repositories={},
        claims=[],
        requirements=[
            Requirement(id="RF-001", text="x", source_claims=["CLM-INEXISTENTE"])
        ],
        acceptance_criteria=[],
        operations=[],
        errors=[],
        nfrs=[],
        open_questions=[],
    )
    result = validate_spec(spec)
    assert result.has_errors
    assert any(i.code == "UNKNOWN_SOURCE_CLAIM" for i in result.errors)
