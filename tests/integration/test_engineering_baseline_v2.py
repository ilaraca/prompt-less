"""Engineering baseline v2: schema, seleção por camada/criticidade, gaps."""
from __future__ import annotations

from src.engenharia import (
    dehydrate_engenharia,
    detect_nfr_signals,
    nfr_gaps_from_code,
    select_nfrs,
    validate_engenharia_schema,
)
from src.renderers import render_historia, render_prd
from src.renderers.sdd import build_sdd_package
from src.spec.builder import build_canonical_spec


def test_migrate_v1_template_to_v2():
    v1 = {
        "version": 1,
        "resiliencia": {"timeout_ms": 1500, "retry": {"max_attempts": 1}},
        "observabilidade": {"logs": {"formato": "json", "sem_pii": True}},
    }
    eng = dehydrate_engenharia(v1)
    assert eng["version"] == 2
    assert eng["_meta"]["migrated_from"] == 1
    assert eng["resiliencia"]["circuit_breaker"]["enabled"] is True
    assert eng["observabilidade"]["metrics"]["enabled"] is True
    assert eng["observabilidade"]["tracing"]["enabled"] is True
    assert eng["resiliencia"]["timeout_ms"] == 1500
    # timeout estava no YAML → declared; circuit_breaker veio do baseline
    assert eng["_declared_nfrs"]["NFR-R-01"] is True
    assert eng["_declared_nfrs"]["NFR-R-03"] is False
    errs = validate_engenharia_schema(eng)
    assert errs == []


def test_select_nfrs_by_layer_and_criticidade():
    eng = dehydrate_engenharia(
        {"version": 2, "criticidade": "low", "resiliencia": {"timeout_ms": 2000}}
    )
    mfe = select_nfrs(eng, layers=["mfe"], criticidade="low")
    mfe_ids = {n.id for n in mfe}
    assert "NFR-R-01" not in mfe_ids  # timeout não aplica a mfe
    assert "NFR-O-01" in mfe_ids
    assert "NFR-R-03" not in mfe_ids  # circuit breaker exige medium+

    api_high = select_nfrs(eng, layers=["api"], criticidade="high")
    api_ids = {n.id for n in api_high}
    assert "NFR-R-03" in api_ids
    assert "NFR-R-04" in api_ids
    assert "NFR-O-04" in api_ids
    assert "NFR-S-03" in api_ids


def test_nfr_ids_shared_across_historia_prd_sdd():
    template_h = (
        "# {{titulo}}\n## Resiliência\n{{resiliencia}}\n"
        "## Observabilidade\n{{observabilidade}}\n"
    )
    template_p = (
        "nfr:\n{{nfr_ids_yaml}}\n"
        "## R\n{{nfr_resiliencia}}\n## O\n{{nfr_observabilidade}}\n"
        "## S\n{{nfr_seguranca}}\n## D\n{{nfr_documentacao}}\n"
    )
    spec = build_canonical_spec(
        ui={"actions": [{"id": "salvar", "method": "POST", "path": "/x"}]},
        regras={"decisoes": [{"quando": "ok", "entao": "201"}]},
        engenharia={
            "version": 1,
            "criticidade": "medium",
            "resiliencia": {"timeout_ms": 2000},
            "observabilidade": {"logs": {"formato": "json", "sem_pii": True}},
        },
        servico={
            "id": "ms-cliente",
            "nome": "Cliente",
            "repos": ["ms-cliente", "bff-cliente", "mfe-onboarding"],
        },
    )
    nfr_ids = [n.id for n in spec.nfrs]
    assert nfr_ids
    assert all(n.origin in {"baseline", "declared", "observed"} for n in spec.nfrs)

    h = render_historia(spec, template_h, engenharia={"version": 2})
    p = render_prd(spec, template_p, engenharia={"version": 2})
    pkg = build_sdd_package(spec)

    for nid in nfr_ids:
        assert nid in h or nid in p  # render lista por categoria
        assert nid in p  # frontmatter + seções com with_ids
    # SDD tasks usam subconjunto por camada; união ⊆ IDs do IR
    task_nfrs: set[str] = set()
    for task in pkg["tasks"]:
        task_nfrs.update(task["nfr_ids"])
        for nid in task["nfr_ids"]:
            assert nid in nfr_ids
    assert task_nfrs
    # mfe task não deve carregar circuit breaker se o IR o restringe a api/bff
    mfe_tasks = [t for t in pkg["tasks"] if t.get("layer") == "mfe"]
    if mfe_tasks:
        for t in mfe_tasks:
            assert "NFR-R-03" not in t["nfr_ids"]


def test_nfr_conflict_with_code_creates_gap():
    indice = {
        "evidencias": [
            {
                "file": "src/App.java",
                "symbol": "salvar",
                "route": "POST /x",
                "origin": "observed",
                "confidence": 0.9,
                "kind": "route",
            }
        ]
    }
    # índice aplicado sem sinais de circuit breaker / metrics → gaps
    spec = build_canonical_spec(
        ui={"actions": [{"id": "salvar", "method": "POST", "path": "/x"}]},
        regras={},
        engenharia={"version": 2, "criticidade": "high"},
        servico={
            "id": "ms-cliente",
            "repos": ["ms-cliente"],
            "indice": indice,
        },
    )
    nfr_gaps = [g for g in spec.gaps if str(g.id).startswith("GAP-NFR")]
    assert nfr_gaps
    assert any("NFR-R-03" in g.text or g.declared == "NFR-R-03" for g in nfr_gaps)

    # com sinal no código → origem observed e sem gap daquele NFR
    indice2 = {
        "evidencias": [
            {
                "file": "ResilienceConfig.java",
                "symbol": "CircuitBreaker",
                "origin": "observed",
                "confidence": 0.9,
                "kind": "symbol",
            },
            {
                "file": "Metrics.java",
                "symbol": "MeterRegistry",
                "origin": "observed",
                "confidence": 0.9,
                "kind": "symbol",
            },
            {
                "file": "Trace.java",
                "symbol": "OpenTelemetry",
                "origin": "observed",
                "confidence": 0.9,
                "kind": "symbol",
            },
            {
                "file": "Idem.java",
                "symbol": "Idempotency-Key",
                "origin": "observed",
                "confidence": 0.9,
                "kind": "symbol",
            },
            {
                "file": "Sec.java",
                "symbol": "SecurityFilterChain",
                "origin": "observed",
                "confidence": 0.9,
                "kind": "symbol",
            },
            {
                "file": "Authz.java",
                "symbol": "hasRole",
                "origin": "observed",
                "confidence": 0.9,
                "kind": "symbol",
            },
            {
                "file": "Retry.java",
                "symbol": "@Retry",
                "origin": "observed",
                "confidence": 0.9,
                "kind": "symbol",
            },
            {
                "file": "Timeout.java",
                "symbol": "Timeout",
                "origin": "observed",
                "confidence": 0.9,
                "kind": "symbol",
            },
        ]
    }
    observed = detect_nfr_signals(indice2)
    assert "NFR-R-03" in observed
    selected = select_nfrs(
        dehydrate_engenharia({"version": 2, "criticidade": "high"}),
        layers=["api"],
        observed=observed,
    )
    by_id = {n.id: n for n in selected}
    assert by_id["NFR-R-03"].origin == "observed"
    gaps = nfr_gaps_from_code(selected, indice_applied=True)
    assert not any(g.get("declared") == "NFR-R-03" for g in gaps)
