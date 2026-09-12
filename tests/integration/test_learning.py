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
    assert len(result["accepted"]) == 1
    assert result["rejected"] == []


def test_eval_suite_smoke(tmp_path: Path):
    # só happy_path para ficar rápido
    report = run_eval_suite(cases=["happy_path"], output_root=tmp_path)
    assert report["summary"]["total"] == 1
    assert report["summary"]["passed"] == 1
