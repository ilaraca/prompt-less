"""Evals de candidato: workspaces distintos, apply, gates críticos, recovery."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
import yaml

from src.improve import improve_from_verify
from src.learning.accept import decide_proposals, load_history
from src.learning.evals import compare_evals, run_eval_suite, score_case
from src.learning.workspaces import (
    apply_journal,
    apply_proposals_to_candidate,
    is_fully_applied,
    materialize_eval_workspaces,
)
from src.learning import workspaces as workspaces_mod

PIPELINE = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

REPORT = {
    "verify": {
        "status": "failed",
        "issues": [
            {"code": "AMBIGUOUS_HTTP_STATUS", "severity": "error", "message": "status ambíguo"}
        ],
    }
}


def _proposals() -> list[dict]:
    return [
        {
            "id": "PROP-TEST",
            "playbook": "clarify_http_status",
            "risk": "low",
            "change": {"key": "validators.ambiguity.blocking", "value": True},
            "status": "proposed",
        }
    ]


def test_workspaces_are_distinct_and_apply_only_hits_candidate(tmp_path: Path):
    pair = materialize_eval_workspaces(source_root=PIPELINE, eval_root=tmp_path)
    before_baseline = (pair.baseline.path / "config" / "pipeline.yaml").read_bytes()
    applied = apply_proposals_to_candidate(_proposals(), pair)

    assert applied.status == "applied"
    assert pair.baseline.path != pair.candidate.path
    assert pair.baseline.workspace_commit != pair.candidate.workspace_commit
    assert pair.source_commit
    overlay = pair.candidate.path / "config" / "proposal-overlay.yaml"
    assert overlay.is_file()
    data = yaml.safe_load(overlay.read_text(encoding="utf-8"))
    assert data["validators"]["ambiguity"]["blocking"] is True
    assert not (pair.baseline.path / "config" / "proposal-overlay.yaml").exists()
    assert (pair.baseline.path / "config" / "pipeline.yaml").read_bytes() == before_baseline
    assert applied.diff
    assert "proposal-overlay.yaml" in applied.diff


def test_critical_http_defaults_to_exact_equality():
    expected = {
        "critical": True,
        "http_statuses": [200, 400],
        "services": [],
        "signals": [],
    }
    result = {"status": "completed", "contexts": [], "by_context": [], "claims": []}
    score = score_case(expected, result, output_root=None)
    assert score.critical is True
    assert score.details["http_status_mode"] == "exact"
    assert score.details["http_status_mode_explicit"] is False


def test_critical_http_extra_status_is_adversarial_fail(tmp_path: Path):
    from src.runtime.atomic_io import sha256_of
    from src.runtime.integrity import seal_hmac
    from src.runtime.run_context import RunContext
    from src.runtime.run_store import RunStore

    run_id = "eval-adv-extra"
    ctx = RunContext.create(root=tmp_path, objective="historia", run_id=run_id)
    store = RunStore(ctx)
    store.bootstrap()
    spec_path = ctx.artifacts_dir / "canonical-spec.yaml"
    ctx.artifacts_dir.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(
        yaml.safe_dump(
            {
                "claims": [{"id": "CLM-0001", "text": "cadastro POST /clientes"}],
                "requirements": [],
                "acceptance_criteria": [],
                "operations": [],
                "errors": [
                    {"trigger": "ok", "status": 200},
                    {"trigger": "cpf", "status": 400},
                    {"trigger": "inventado", "status": 500},
                ],
                "open_questions": [],
            }
        ),
        encoding="utf-8",
    )
    store.finish("completed")
    integrity = {
        "algo": "hmac-sha256",
        "kid": "v1",
        "events_tip": store.events.tip,
        "files": [
            {
                "path": "artifacts/canonical-spec.yaml",
                "bytes": spec_path.stat().st_size,
                "sha256": sha256_of(spec_path),
            }
        ],
        "sealed_at": "2026-09-18T00:00:00Z",
    }
    integrity["hmac"] = seal_hmac(integrity)
    store.write_manifest({"run_id": run_id, "integrity": integrity})

    expected = yaml.safe_load(
        (FIXTURES / "eval_adversarial" / "expected.yaml").read_text(encoding="utf-8")
    )
    result = {
        "status": "completed",
        "run_id": run_id,
        "run_dir": str(ctx.run_dir),
        "contexts": ["ms-cliente"],
        "by_context": [
            {"servico": {"id": "ms-cliente", "repos": ["mfe-onboarding", "bff-cliente", "ms-cliente"]}}
        ],
        "claims": [{"text": "POST /clientes CPF"}],
    }
    score = score_case(expected, result, output_root=tmp_path)
    assert score.critical is True
    assert score.details["http_status_mode"] == "exact"
    assert score.expected_status_match is False
    assert score.passed is False


def test_critical_http_explicit_subset_rule_allows_extra(tmp_path: Path):
    from src.runtime.atomic_io import sha256_of
    from src.runtime.integrity import seal_hmac
    from src.runtime.run_context import RunContext
    from src.runtime.run_store import RunStore

    run_id = "eval-subset-extra"
    ctx = RunContext.create(root=tmp_path, objective="historia", run_id=run_id)
    store = RunStore(ctx)
    store.bootstrap()
    spec_path = ctx.artifacts_dir / "canonical-spec.yaml"
    ctx.artifacts_dir.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(
        yaml.safe_dump(
            {
                "claims": [],
                "requirements": [],
                "acceptance_criteria": [],
                "operations": [],
                "errors": [{"status": 401}, {"status": 403}, {"status": 200}],
                "open_questions": [],
            }
        ),
        encoding="utf-8",
    )
    store.finish("completed")
    integrity = {
        "algo": "hmac-sha256",
        "kid": "v1",
        "events_tip": store.events.tip,
        "files": [
            {
                "path": "artifacts/canonical-spec.yaml",
                "bytes": spec_path.stat().st_size,
                "sha256": sha256_of(spec_path),
            }
        ],
        "sealed_at": "2026-09-18T00:00:00Z",
    }
    integrity["hmac"] = seal_hmac(integrity)
    store.write_manifest({"run_id": run_id, "integrity": integrity})

    expected = {
        "critical": True,
        "http_status_mode": "subset",
        "http_statuses": [401, 403],
        "services": [],
        "signals": [],
        "expect_blocked": False,
    }
    result = {
        "status": "completed",
        "run_id": run_id,
        "run_dir": str(ctx.run_dir),
        "contexts": [],
        "by_context": [],
        "claims": [],
    }
    score = score_case(expected, result, output_root=tmp_path)
    assert score.details["http_status_mode"] == "subset"
    assert score.expected_status_match is True
    assert score.selection_ok is True


def test_eval_adversarial_and_multi_context_fixtures(tmp_path: Path):
    report = run_eval_suite(
        cases=["eval_adversarial", "eval_multi_context"],
        output_root=tmp_path,
        run_id_prefix="eval-fx",
    )
    by_id = {c["case_id"]: c for c in report["cases"]}
    assert by_id["eval_adversarial"]["critical"] is True
    assert by_id["eval_adversarial"]["fixture_kind"] == "adversarial"
    assert by_id["eval_adversarial"]["ok"] is True
    assert by_id["eval_adversarial"]["score"]["details"]["http_status_mode"] == "exact"
    assert by_id["eval_multi_context"]["critical"] is True
    assert by_id["eval_multi_context"]["fixture_kind"] == "multi_context"
    assert by_id["eval_multi_context"]["ok"] is True
    assert set(by_id["eval_multi_context"]["score"]["details"]["found_services"]) >= {
        "ms-cliente",
        "ms-pagamento",
    }
    summary = report["summary"]
    for key in (
        "claim_recall",
        "traceability_rate",
        "unexpected_inferences",
        "avg_est_tokens",
        "avg_latency_ms",
        "http_status_match_rate",
    ):
        assert key in summary


def test_metrics_include_claim_recall_and_traceability(tmp_path: Path):
    report = run_eval_suite(cases=["happy_path"], output_root=tmp_path)
    score = report["cases"][0]["score"]
    assert 0 <= score["claim_recall"] <= 1
    assert "all_requirements_traceable" in score["layer_scores"]["canonical_spec"]
    assert report["cases"][0]["latency_ms"] >= 0


def test_apply_interrupted_never_claims_proven_improvement(tmp_path: Path, monkeypatch):
    pair = materialize_eval_workspaces(source_root=PIPELINE, eval_root=tmp_path)
    original = workspaces_mod.atomic_write_text

    def _kill(path, text, **kwargs):
        if path.name == "proposal-overlay.yaml":
            raise KeyboardInterrupt("kill simulado no apply")
        return original(path, text, **kwargs)

    monkeypatch.setattr(workspaces_mod, "atomic_write_text", _kill)
    with pytest.raises(KeyboardInterrupt):
        apply_proposals_to_candidate(_proposals(), pair)

    assert is_fully_applied(pair.candidate.path) is False
    assert not (pair.candidate.path / "config" / "proposal-overlay.yaml").exists()
    journal = apply_journal(pair.candidate.path)
    assert journal is None or journal.get("status") != "applied"

    comparison = {
        "regression": False,
        "improved": True,
        "decision": "accept",
        "reasons": [],
        "metrics": {"claim_recall": {"delta": 0.2}},
        "workspaces": {
            "baseline": pair.baseline.to_dict(),
            "candidate": pair.candidate.to_dict(),
            "distinct": False,
        },
    }
    decision = decide_proposals(
        _proposals(),
        comparison,
        root=tmp_path,
        apply_result={"status": "failed", "applied_ids": [], "diff": ""},
    )
    assert decision["accepted"] == []
    assert decision["approved_for_experiment"] == []
    assert all(i["status"] != "accepted" for i in decision["rejected"])


def test_recovery_retries_apply_after_crash(tmp_path: Path, monkeypatch):
    pair = materialize_eval_workspaces(source_root=PIPELINE, eval_root=tmp_path)
    original = workspaces_mod.atomic_write_text

    def _kill(path, text, **kwargs):
        if path.name == "proposal-overlay.yaml":
            raise KeyboardInterrupt("kill simulado no apply")
        return original(path, text, **kwargs)

    monkeypatch.setattr(workspaces_mod, "atomic_write_text", _kill)
    with pytest.raises(KeyboardInterrupt):
        apply_proposals_to_candidate(_proposals(), pair)
    monkeypatch.setattr(workspaces_mod, "atomic_write_text", original)

    applied = apply_proposals_to_candidate(_proposals(), pair)
    assert applied.status == "applied"
    assert is_fully_applied(pair.candidate.path)


def test_concurrent_applies_keep_workspaces_isolated(tmp_path: Path):
    erros: list[BaseException] = []
    resultados: dict[str, object] = {}

    def _run(name: str) -> None:
        try:
            root = tmp_path / name
            pair = materialize_eval_workspaces(source_root=PIPELINE, eval_root=root)
            applied = apply_proposals_to_candidate(_proposals(), pair)
            resultados[name] = (pair, applied)
        except BaseException as exc:  # noqa: BLE001
            erros.append(exc)

    threads = [
        threading.Thread(target=_run, args=("alpha",)),
        threading.Thread(target=_run, args=("beta",)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not erros, erros
    (pair_a, app_a) = resultados["alpha"]
    (pair_b, app_b) = resultados["beta"]
    assert pair_a.candidate.path != pair_b.candidate.path
    assert app_a.status == "applied" and app_b.status == "applied"
    assert (pair_a.candidate.path / "config" / "proposal-overlay.yaml").is_file()
    assert (pair_b.candidate.path / "config" / "proposal-overlay.yaml").is_file()
    assert not (pair_a.baseline.path / "config" / "proposal-overlay.yaml").exists()


def test_concurrent_evals_do_not_mix_outputs(tmp_path: Path):
    pair = materialize_eval_workspaces(source_root=PIPELINE, eval_root=tmp_path)
    apply_proposals_to_candidate(_proposals(), pair)
    erros: list[BaseException] = []
    reports: dict[str, dict] = {}

    def _eval(role: str) -> None:
        try:
            ws = pair.baseline if role == "baseline" else pair.candidate
            reports[role] = run_eval_suite(
                cases=["happy_path"],
                output_root=tmp_path / "evals" / role,
                workspace=ws,
                run_id_prefix=f"eval-{role[0]}",
            )
        except BaseException as exc:  # noqa: BLE001
            erros.append(exc)

    threads = [
        threading.Thread(target=_eval, args=("baseline",)),
        threading.Thread(target=_eval, args=("candidate",)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not erros, erros
    assert reports["baseline"]["workspace"]["path"] != reports["candidate"]["workspace"]["path"]
    cmp = compare_evals(reports["baseline"], reports["candidate"])
    assert cmp["workspaces"]["distinct"] is True
    assert (tmp_path / "evals" / "baseline" / "happy_path").is_dir()
    assert (tmp_path / "evals" / "candidate" / "happy_path").is_dir()


def test_improve_applies_to_candidate_and_distinguishes_statuses(tmp_path: Path):
    result = improve_from_verify(
        REPORT,
        root=tmp_path,
        eval_root=tmp_path / "improve",
        source_root=PIPELINE,
        cases=["happy_path"],
    )
    assert result["workspaces"]["baseline"]["path"] != result["workspaces"]["candidate"]["path"]
    assert (
        result["workspaces"]["baseline"]["workspace_commit"]
        != result["workspaces"]["candidate"]["workspace_commit"]
    )
    assert result["applied"]["status"] == "applied"
    overlay = Path(result["workspaces"]["candidate"]["path"]) / "config" / "proposal-overlay.yaml"
    assert overlay.is_file()
    assert not (
        Path(result["workspaces"]["baseline"]["path"]) / "config" / "proposal-overlay.yaml"
    ).exists()
    decision = result["decision"]
    for key in (
        "proposed",
        "applied_to_candidate",
        "evaluated",
        "approved_for_experiment",
        "accepted",
        "rejected",
    ):
        assert key in decision
    assert decision["applied_to_candidate"]
    assert decision["evaluated"]
    terminal = (decision["accepted"] or decision["approved_for_experiment"] or decision["rejected"])
    assert terminal
    assert all(p["status"] != "accepted" for p in decision["proposed"])
    hist = load_history(tmp_path)
    stored = hist["accepted"] or hist["approved_for_experiment"] or hist["rejected"]
    assert stored[0].get("diff")
    assert stored[0].get("metrics")
    last = json.loads(
        # knowledge está em tmp_path/state/knowledge via decide_proposals
        (tmp_path / "state" / "knowledge" / "proposals-history.json").read_text(encoding="utf-8")
    )
    assert "applied_to_candidate" in last
