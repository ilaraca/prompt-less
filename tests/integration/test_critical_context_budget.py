"""Budget com reserva de conteúdo crítico e métricas sem fatura falsa."""
from __future__ import annotations

from typing import Any

from src.context_builder import (
    CriticalItem,
    build_context,
    extract_critical_items,
    plan_critical_split,
)
from src.domain.spec import (
    AcceptanceCriterion,
    CanonicalSpec,
    Operation,
    Requirement,
    ResolvedInt,
)
from src.learning.evals import DEFAULT_CASES, _critical_context_score
from src.task_metrics import build_cost_section, build_task_metrics
from src.tokenizer import TokenEstimate, using_tokenizer


def _rag(text: str = "consolidado curto", *, claims: list[dict] | None = None) -> dict[str, Any]:
    return {
        "consolidated": text,
        "est_tokens_raw": 8,
        "est_tokens_compressed": 4,
        "claims": list(claims or []),
        "documents": {"docs": [], "reduction_pct": 0},
    }


def _spec_with_critical(*, n_rf: int = 2) -> CanonicalSpec:
    requirements = [
        Requirement(id=f"RF-{i:03d}", text=f"requisito crítico número {i} com detalhe")
        for i in range(1, n_rf + 1)
    ]
    acceptance = [
        AcceptanceCriterion(
            id=f"AC-{i:03d}",
            requirement_id=f"RF-{i:03d}",
            given="contexto",
            when="ação",
            then=f"resultado {i}",
        )
        for i in range(1, n_rf + 1)
    ]
    operations = [
        Operation(
            id="OP-001",
            name="get_x",
            method="GET",
            path="/x",
            success_status=ResolvedInt(value=200, origin="declared"),
        )
    ]
    return CanonicalSpec(
        version="1.0",
        service_id="svc",
        service_name="svc",
        repositories={},
        claims=[],
        requirements=requirements,
        acceptance_criteria=acceptance,
        operations=operations,
        errors=[],
        nfrs=[],
        open_questions=[],
    )


def test_critical_content_survives_tight_budget():
    spec = _spec_with_critical(n_rf=2)
    huge_cons = "ruido padding " * 500
    with using_tokenizer("anthropic", "claude-sonnet"):
        ctx = build_context(
            "historia",
            state={"bloqueios": [{"status": 403, "trigger": "sem permissão"}]},
            rag=_rag(huge_cons),
            template="T" * 800,
            budget_tokens=400,
            spec=spec,
        )
    critical = str(ctx["dynamic"].get("critical") or "")
    assert "RF-001" in critical
    assert "RF-002" in critical or any(
        om.get("id") == "RF-002" for om in (ctx["budget_report"].get("critical_omissions") or [])
    )
    assert "AC-001" in critical or any(
        om.get("id") == "AC-001" for om in (ctx["budget_report"].get("critical_omissions") or [])
    )
    report = ctx["budget_report"]
    # contrato: presente no critical ou omitido com ref recuperável (split/block)
    op_ok = (
        "OP-001" in critical
        or "GET /x" in critical
        or any(om.get("id") == "OP-001" for om in (report.get("critical_omissions") or []))
        or any(
            "OP-001" in batch
            for batch in (report.get("split_plan") or [])
        )
    )
    assert op_ok
    assert report["critical_coverage"]["complete"] or report["status"] in {
        "split_required",
        "blocked",
    }
    # omissões não-críticas têm motivo + ref recuperável
    for om in report.get("omissions") or []:
        assert om.get("reason")
        assert om.get("recoverable") is True
        assert om.get("ref")


def test_critical_does_not_silently_disappear():
    """Reduzir budget não apaga RF sem registrar omissão/diagnóstico."""
    spec = _spec_with_critical(n_rf=3)
    with using_tokenizer("anthropic", "claude-sonnet"):
        roomy = build_context(
            "prd",
            state={},
            rag=_rag("ok"),
            template="tpl",
            budget_tokens=5000,
            spec=spec,
        )
        tight = build_context(
            "prd",
            state={},
            rag=_rag("x" * 3000),
            template="Y" * 2000,
            budget_tokens=50,
            spec=spec,
        )
    assert "RF-001" in roomy["dynamic"]["critical"]
    report = tight["budget_report"]
    if report["status"] in {"blocked", "split_required"}:
        assert report.get("diagnosis")
        assert report.get("critical_omissions")
        for om in report["critical_omissions"]:
            assert om.get("reason")
            assert om.get("ref")
            assert om.get("recoverable") is True
    else:
        # ainda cabe: crítico intacto
        assert "RF-001" in tight["dynamic"]["critical"]
        assert report["critical_coverage"]["complete"] is True


def test_excess_critical_split_or_block(monkeypatch):
    import src.context_builder as cb

    items = [
        CriticalItem(
            id=f"RF-{i}",
            kind="requirement",
            text=("REQUISITO MUITO LONGO " * 40) + str(i),
            ref={"source": "test", "subject_id": f"RF-{i}"},
        )
        for i in range(6)
    ]

    def fake_estimate(text: str, **kwargs: Any) -> TokenEstimate:
        # system+state leve; critical blob grande
        n = max(1, len(text) // 4)
        return TokenEstimate(
            tokens=n,
            method="heuristic",
            provider="anthropic",
            model="claude-sonnet",
            fallback_reason="test",
        )

    monkeypatch.setattr(cb, "estimate", fake_estimate)
    dynamic = {
        "comando": "Gerar historia",
        "state": {},
        "contexto_comprimido": "",
        "template": "",
        "critical": "",
    }
    # budget minúsculo frente ao blob crítico
    est, report = cb._fit_to_budget(dynamic, budget_tokens=80, critical_items=items)
    assert report.status in {"blocked", "split_required"}
    assert report.diagnosis
    assert report.critical_omissions
    # crítico do lote/payload não foi zerado sem rastro
    assert dynamic.get("critical")


def test_omissions_have_recoverable_refs():
    with using_tokenizer("anthropic", "claude-sonnet"):
        ctx = build_context(
            "historia",
            state={},
            rag=_rag("consolidado " * 200),
            template="TEMPLATE " * 100,
            budget_tokens=120,
            spec=_spec_with_critical(n_rf=1),
        )
    for om in ctx["budget_report"].get("omissions") or []:
        assert "reason" in om
        assert om.get("recoverable") is True
        assert isinstance(om.get("ref"), dict)
        assert om["ref"].get("source")


def test_task_metrics_attempts_and_not_invoice():
    metrics = build_task_metrics(
        attempts=3,
        duration_ms={"validation_ms": 10, "repair_ms": 5, "total_ms": 15},
        token_usage={"estimated": 100, "method": "heuristic", "billable": None},
    )
    assert metrics["attempts"] == 3
    assert metrics["duration_ms"]["total_ms"] == 15
    assert metrics["cost"]["kind"] == "estimate"
    assert metrics["cost"]["is_invoice"] is False
    assert "fatura" in metrics["cost"]["note"].lower() or "estimativa" in metrics["cost"]["note"].lower()

    observed = build_cost_section(
        {"estimated": 100, "billable": 120, "method": "official"},
        cost_usd={"usd_total": 0.01},
    )
    assert observed["kind"] == "observed_billing"
    assert observed["is_invoice"] is False
    assert observed["observed_billable_tokens"] == 120


def test_build_context_task_metrics_estimate_not_invoice():
    with using_tokenizer("anthropic", "claude-sonnet"):
        ctx = build_context(
            "historia",
            state={},
            rag=_rag(),
            template="t",
            budget_tokens=2000,
            attempts=2,
        )
    assert ctx["task_metrics"]["attempts"] == 2
    assert ctx["task_metrics"]["cost"]["is_invoice"] is False
    assert ctx["task_metrics"]["cost"]["kind"] == "estimate"
    assert ctx["token_usage"]["is_invoice"] is False
    assert ctx["token_usage"]["cost_kind"] == "estimate"
    assert ctx["token_usage"]["billable"] is None


def test_extract_critical_from_spec_and_state():
    spec = _spec_with_critical(n_rf=1)
    items = extract_critical_items(
        {"bloqueios": [{"status": 401, "trigger": "auth"}], "actions": [{"id": "a1", "method": "POST", "path": "/y"}]},
        _rag(claims=[{"id": "CLM-1", "text": "evidência", "sources": [{"document": "r.txt"}]}]),
        spec,
    )
    kinds = {it.kind for it in items}
    assert "requirement" in kinds
    assert "acceptance" in kinds
    assert "contract" in kinds
    assert "evidence" in kinds
    assert all(it.ref for it in items)


def test_plan_critical_split_packs_batches():
    items = [
        CriticalItem(id=f"RF-{i}", kind="requirement", text="x" * 20, ref={"i": i})
        for i in range(4)
    ]
    # força tamanhos via monkeypatch no caller — aqui só smoke do packing com budget folgado
    batches = plan_critical_split(items, budget_tokens=10_000, overhead_tokens=10)
    assert batches is not None
    assert sum(len(b) for b in batches) == 4


def test_critical_cases_remain_in_eval_set():
    """Cobertura crítica permanece no conjunto de avaliação."""
    from pathlib import Path

    import yaml

    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    critical_ids = []
    for case_id in DEFAULT_CASES:
        expected = yaml.safe_load((fixtures / case_id / "expected.yaml").read_text())
        if expected.get("critical"):
            critical_ids.append(case_id)
    assert critical_ids, "DEFAULT_CASES deve incluir ao menos um caso critical"
    assert "access_denied" in critical_ids or any(
        yaml.safe_load((fixtures / c / "expected.yaml").read_text()).get("critical")
        for c in DEFAULT_CASES
    )


def test_critical_context_score_flags_silent_loss():
    score = _critical_context_score(
        {
            "budget_report": {
                "status": "ok",
                "critical_omissions": [
                    {"id": "RF-1", "reason": "oops", "recoverable": True}
                ],
                "critical_coverage": {"complete": False},
            }
        },
        critical=True,
    )
    assert score["silent_critical_loss"] is True
    assert score["complete"] is False

    ok = _critical_context_score(
        {
            "budget_report": {
                "status": "ok",
                "critical_omissions": [],
                "critical_coverage": {"complete": True},
            }
        },
        critical=True,
    )
    assert ok["silent_critical_loss"] is False
    assert ok["complete"] is True
