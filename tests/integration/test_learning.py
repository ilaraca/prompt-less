"""Autoaperfeiçoamento controlado: patterns, propostas, evals, aceite."""
from __future__ import annotations

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


def test_compare_evals_rejects_critical_case_regression():
    baseline = {
        "summary": {"pass_rate": 0.5, "avg_est_tokens": 100, "claim_recall": 1.0},
        "cases": [
            {"case_id": "happy_path", "ok": False, "critical": False},
            {"case_id": "access_denied", "ok": True, "critical": True},
        ],
    }
    candidate = {
        "summary": {"pass_rate": 0.5, "avg_est_tokens": 90, "claim_recall": 1.0},
        "cases": [
            {"case_id": "happy_path", "ok": True, "critical": False},
            {"case_id": "access_denied", "ok": False, "critical": True},
        ],
    }
    cmp = compare_evals(baseline, candidate)
    assert cmp["critical_regression"] is True
    assert cmp["decision"] == "reject"
    assert any("access_denied" in r for r in cmp["reasons"])


def test_compare_evals_marks_noncritical_pass_to_fail_without_compensation():
    """Troca pass→fail compensada por outro caso: ainda é regressão."""
    baseline = {
        "summary": {
            "pass_rate": 0.5,
            "avg_est_tokens": 100,
            "claim_recall": 0.8,
            "traceability_rate": 1.0,
            "unexpected_inferences": 0,
        },
        "cases": [
            {"case_id": "a", "ok": True, "critical": False},
            {"case_id": "b", "ok": False, "critical": False},
        ],
    }
    candidate = {
        "summary": {
            "pass_rate": 0.5,
            "avg_est_tokens": 90,
            "claim_recall": 0.9,
            "traceability_rate": 1.0,
            "unexpected_inferences": 0,
        },
        "cases": [
            {"case_id": "a", "ok": False, "critical": False},
            {"case_id": "b", "ok": True, "critical": False},
        ],
    }
    cmp = compare_evals(baseline, candidate)
    assert cmp["regression"] is True
    assert cmp["decision"] == "reject"
    assert cmp["improved"] is False
    gate_a = next(g for g in cmp["case_gates"] if g["case_id"] == "a")
    assert gate_a["regressed"] is True
    assert gate_a["tolerated"] is False
    assert any(r == "case_regressed:a" for r in cmp["reasons"])


def test_compare_evals_records_explicit_noncritical_tolerance():
    # pass_rate agregado igual: isola o gate por caso (sem side-effect de summary)
    baseline = {
        "summary": {"pass_rate": 1.0, "avg_est_tokens": 100, "claim_recall": 0.8},
        "cases": [{"case_id": "flaky", "ok": True, "critical": False}],
    }
    candidate = {
        "summary": {"pass_rate": 1.0, "avg_est_tokens": 90, "claim_recall": 0.9},
        "cases": [{"case_id": "flaky", "ok": False, "critical": False}],
    }
    cmp = compare_evals(
        baseline,
        candidate,
        tolerances=[
            {
                "case_id": "flaky",
                "justification": "fixture known-flake until ticket 99",
            }
        ],
    )
    assert cmp["regression"] is False
    assert cmp["decision"] == "accept"
    assert cmp["tolerances_applied"]
    assert cmp["tolerances_applied"][0]["justification"]
    gate = cmp["case_gates"][0]
    assert gate["regressed"] is True
    assert gate["tolerated"] is True
    assert cmp["improved"] is True  # claim_recall subiu; tolerância registrada


def test_compare_evals_blocks_missing_or_incompatible_case_sets():
    baseline = {
        "summary": {"pass_rate": 1.0, "avg_est_tokens": 100},
        "cases": [
            {"case_id": "happy_path", "ok": True, "critical": False},
            {"case_id": "access_denied", "ok": True, "critical": True},
        ],
    }
    candidate = {
        "summary": {"pass_rate": 1.0, "avg_est_tokens": 90},
        "cases": [{"case_id": "happy_path", "ok": True, "critical": False}],
    }
    cmp = compare_evals(baseline, candidate)
    assert cmp["comparable"] is False
    assert cmp["decision"] == "reject"
    assert any("incomparable_missing_cases" in r for r in cmp["reasons"])
    missing_gate = next(
        g for g in cmp["case_gates"] if g["case_id"] == "access_denied"
    )
    assert missing_gate.get("missing_in_candidate") is True


def test_compare_evals_latency_jitter_alone_does_not_improve():
    baseline = {
        "summary": {
            "pass_rate": 1.0,
            "avg_est_tokens": 100,
            "claim_recall": 1.0,
            "traceability_rate": 1.0,
            "unexpected_inferences": 0,
            "avg_latency_ms": 50.0,
        },
        "cases": [{"case_id": "happy_path", "ok": True, "critical": False}],
    }
    candidate = {
        "summary": {
            "pass_rate": 1.0,
            "avg_est_tokens": 100,
            "claim_recall": 1.0,
            "traceability_rate": 1.0,
            "unexpected_inferences": 0,
            "avg_latency_ms": 10.0,
        },
        "cases": [{"case_id": "happy_path", "ok": True, "critical": False}],
    }
    cmp = compare_evals(baseline, candidate)
    assert cmp["regression"] is False
    assert cmp["decision"] == "accept"
    assert cmp["improved"] is False
    assert cmp["metrics"]["avg_latency_ms"]["delta"] < 0


def test_compare_evals_marks_dimension_regression():
    baseline = {
        "summary": {"pass_rate": 1.0, "avg_est_tokens": 100, "claim_recall": 1.0},
        "cases": [
            {
                "case_id": "happy_path",
                "ok": True,
                "critical": False,
                "score": {
                    "required_gates": {
                        "status_ok": True,
                        "traceable": True,
                    }
                },
            }
        ],
    }
    candidate = {
        "summary": {"pass_rate": 1.0, "avg_est_tokens": 100, "claim_recall": 1.0},
        "cases": [
            {
                "case_id": "happy_path",
                "ok": True,
                "critical": False,
                "score": {
                    "required_gates": {
                        "status_ok": True,
                        "traceable": False,
                    }
                },
            }
        ],
    }
    cmp = compare_evals(baseline, candidate)
    assert cmp["regression"] is True
    assert any("dimension_regressed:happy_path:traceable" in r for r in cmp["reasons"])


def test_holdout_critical_regression_blocks_despite_dev_improvement():
    """Candidato melhora no conjunto de desenvolvimento e regride no hold-out."""
    from src.learning.evals import apply_reserved_gate

    dev_baseline = {
        "summary": {
            "pass_rate": 0.5,
            "avg_est_tokens": 100,
            "claim_recall": 0.5,
            "traceability_rate": 1.0,
            "unexpected_inferences": 0,
        },
        "cases": [
            {"case_id": "a", "ok": False, "critical": False},
            {"case_id": "b", "ok": True, "critical": False},
        ],
    }
    dev_candidate = {
        "summary": {
            "pass_rate": 1.0,
            "avg_est_tokens": 90,
            "claim_recall": 0.9,
            "traceability_rate": 1.0,
            "unexpected_inferences": 0,
        },
        "cases": [
            {"case_id": "a", "ok": True, "critical": False},
            {"case_id": "b", "ok": True, "critical": False},
        ],
    }
    comparison = compare_evals(dev_baseline, dev_candidate)
    assert comparison["decision"] == "accept"
    assert comparison["improved"] is True
    assert comparison["regression"] is False

    reserved_baseline = {
        "summary": {"pass_rate": 1.0, "avg_est_tokens": 100, "claim_recall": 1.0},
        "cases": [{"case_id": "eval_adversarial", "ok": True, "critical": True}],
    }
    reserved_candidate = {
        "summary": {"pass_rate": 0.0, "avg_est_tokens": 100, "claim_recall": 1.0},
        "cases": [{"case_id": "eval_adversarial", "ok": False, "critical": True}],
    }
    gated = apply_reserved_gate(
        comparison, reserved_baseline, reserved_candidate
    )
    assert gated["critical_regression"] is True
    assert gated["regression"] is True
    assert gated["decision"] == "reject"
    assert gated["improved"] is False
    # Orientação (métricas / case_gates de desenvolvimento) preservada
    assert gated["metrics"]["claim_recall"]["delta"] > 0
    assert all(g["case_id"] != "eval_adversarial" for g in gated["case_gates"])
    hold_gate = next(
        g for g in gated["reserved_case_gates"] if g["case_id"] == "eval_adversarial"
    )
    assert hold_gate["regressed"] is True
    assert hold_gate["critical"] is True
    assert any("reserved:" in r for r in gated["reasons"])
    assert gated["reserved_comparison"]["decision"] == "reject"


def test_holdout_noncritical_tolerance_must_be_explicit():
    from src.learning.evals import apply_reserved_gate

    comparison = compare_evals(
        {
            "summary": {"pass_rate": 1.0, "avg_est_tokens": 100, "claim_recall": 0.8},
            "cases": [{"case_id": "dev", "ok": True, "critical": False}],
        },
        {
            "summary": {"pass_rate": 1.0, "avg_est_tokens": 90, "claim_recall": 0.9},
            "cases": [{"case_id": "dev", "ok": True, "critical": False}],
        },
    )
    reserved_b = {
        "summary": {"pass_rate": 1.0, "avg_est_tokens": 50},
        "cases": [{"case_id": "hold_flake", "ok": True, "critical": False}],
    }
    reserved_c = {
        # pass_rate agregado igual: isola o gate por caso (como no teste de tolerância)
        "summary": {"pass_rate": 1.0, "avg_est_tokens": 50},
        "cases": [{"case_id": "hold_flake", "ok": False, "critical": False}],
    }
    blocked = apply_reserved_gate(comparison, reserved_b, reserved_c)
    assert blocked["decision"] == "reject"
    assert blocked["regression"] is True

    allowed = apply_reserved_gate(
        comparison,
        reserved_b,
        reserved_c,
        tolerances=[
            {
                "case_id": "hold_flake",
                "justification": "hold-out flake known until ticket X",
            }
        ],
    )
    assert allowed["decision"] == "accept"
    assert allowed["reserved_comparison"]["decision"] == "accept"
    assert any(t.get("scope") == "reserved" for t in allowed["tolerances_applied"])


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
    result = decide_proposals(
        proposals,
        comparison,
        root=tmp_path,
        apply_result={"status": "applied", "applied_ids": ["PROP-1"], "diff": "--- a\n+++ b\n"},
    )
    assert result["accepted"] == []
    assert result["approved_for_experiment"] == []
    assert result["rejected"]
    assert result["applied_to_candidate"]
    hist = load_history(tmp_path)
    assert len(hist["rejected"]) >= 1
    assert hist["rejected"][0].get("diff")
    assert "metrics" in hist["rejected"][0]


def test_decide_unapplied_never_gets_proven_status(tmp_path: Path):
    proposals = [
        {
            "id": "PROP-2",
            "playbook": "human_gate",
            "risk": "low",
            "change": {"key": "approval.auto", "value": False},
        }
    ]
    comparison = {
        "regression": False,
        "critical_regression": False,
        "improved": True,
        "decision": "accept",
        "reasons": [],
        "metrics": {"claim_recall": {"baseline": 0.5, "candidate": 1.0, "delta": 0.5}},
    }
    result = decide_proposals(proposals, comparison, root=tmp_path)
    assert result["accepted"] == []
    assert result["approved_for_experiment"] == []
    assert result["rejected"][0]["status"] == "rejected"
    assert "proposal_not_applied" in result["rejected"][0]["reason"]


def test_decide_accepts_applied_low_risk_with_improvement(tmp_path: Path):
    proposals = [
        {
            "id": "PROP-2",
            "playbook": "human_gate",
            "risk": "low",
            "change": {"key": "approval.auto", "value": False},
        }
    ]
    comparison = {
        "regression": False,
        "critical_regression": False,
        "improved": True,
        "decision": "accept",
        "reasons": [],
        "metrics": {"claim_recall": {"baseline": 0.5, "candidate": 1.0, "delta": 0.5}},
        "workspaces": {
            "baseline": {"path": "/b", "workspace_commit": "aaa"},
            "candidate": {"path": "/c", "workspace_commit": "bbb"},
            "distinct": True,
        },
    }
    result = decide_proposals(
        proposals,
        comparison,
        root=tmp_path,
        apply_result={"status": "applied", "applied_ids": ["PROP-2"], "diff": "+overlay"},
    )
    assert len(result["accepted"]) == 1
    assert result["accepted"][0]["status"] == "accepted"
    assert result["applied_to_candidate"][0]["status"] == "applied_to_candidate"
    assert result["evaluated"][0]["status"] == "evaluated"
    assert result["rejected"] == []
    hist = load_history(tmp_path)
    assert hist["accepted"][0]["diff"] == "+overlay"
    assert hist["accepted"][0]["metrics"]["claim_recall"]["delta"] == 0.5


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


def test_claim_without_source_blocked():
    from src.domain.claim import Claim, ClaimOrigin
    from src.domain.spec import CanonicalSpec, Requirement
    from src.validators import validate_spec

    spec = CanonicalSpec(
        version="1.0",
        service_id="default",
        repositories={},
        claims=[
            Claim(
                id="CLM-001",
                text="Cliente deve estar autenticado",
                origin=ClaimOrigin.DECLARED,
                confidence=1.0,
                sources=[],
            )
        ],
        requirements=[
            Requirement(id="RF-001", text="auth", source_claims=["CLM-001"])
        ],
        acceptance_criteria=[],
        operations=[],
        errors=[],
        nfrs=[],
        open_questions=[],
    )
    result = validate_spec(spec)
    assert result.has_errors
    assert any(i.code == "CLAIM_WITHOUT_SOURCE" for i in result.errors)
