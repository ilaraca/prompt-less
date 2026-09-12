"""Planejamento multi-repositório."""
from __future__ import annotations

from src.planning.graph import PlanTask, topological_waves
from src.planning.layers import infer_layer, sort_repos_by_layer
from src.planning.plan import (
    build_implementation_plan,
    build_plans_from_mapa,
    integrate_report,
)

FIXTURES_MAPA = {
    "servicos": {
        "gestao-de-ofertas": {
            "nome": "Gestão de Ofertas",
            "repos": [
                "gestao-de-ofertas-api",
                "gestao-de-ofertas-bff",
                "gestao-de-ofertas-mfe",
                "ofertas-gtw",
            ],
        },
        "ms-cliente": {
            "nome": "Cadastro",
            "repos": ["mfe-onboarding", "bff-cliente", "ms-cliente"],
        },
    }
}


def test_infer_layer():
    assert infer_layer("gestao-de-ofertas-api") == "api"
    assert infer_layer("bff-cliente") == "bff"
    assert infer_layer("mfe-onboarding") == "mfe"
    assert infer_layer("ofertas-gtw") == "gtw"


def test_sort_repos_api_before_mfe():
    ordered = sort_repos_by_layer(
        ["gestao-de-ofertas-mfe", "gestao-de-ofertas-api", "gestao-de-ofertas-bff"]
    )
    layers = [L for _, L in ordered]
    assert layers == ["api", "bff", "mfe"]


def test_plan_dependencies_and_contracts():
    plan = build_implementation_plan(
        service_id="gestao-de-ofertas",
        repos=[
            "gestao-de-ofertas-api",
            "gestao-de-ofertas-bff",
            "gestao-de-ofertas-mfe",
        ],
        contract_version="v2",
    )
    by_id = {t["id"]: t for t in plan["tasks"]}
    api = next(t for t in plan["tasks"] if t["layer"] == "api")
    bff = next(t for t in plan["tasks"] if t["layer"] == "bff")
    mfe = next(t for t in plan["tasks"] if t["layer"] == "mfe")
    assert "contract:v2" in api["produces"]
    assert "contract:v2" in bff["consumes"]
    assert api["id"] in bff["depends_on"]
    assert bff["id"] in mfe["depends_on"]
    assert plan["rollout"]["strategy"] == "expand-contract"
    # ondas: api | bff | mfe
    assert plan["waves"][0] == [api["id"]]
    assert bff["id"] in plan["waves"][1]
    assert mfe["id"] in plan["waves"][2]


def test_same_layer_repos_are_parallel():
    plan = build_implementation_plan(
        service_id="x",
        repos=["dom-a-api", "dom-b-api", "app-x-bff"],
    )
    api_wave = plan["waves"][0]
    assert len(api_wave) == 2
    assert plan["parallelism"]["max_wave_size"] >= 2


def test_topological_detects_cycle():
    tasks = [
        PlanTask(id="A", repo="a", layer="api", service_id="s", depends_on=["B"]),
        PlanTask(id="B", repo="b", layer="bff", service_id="s", depends_on=["A"]),
    ]
    try:
        topological_waves(tasks)
        assert False, "deveria falhar"
    except ValueError as e:
        assert "ciclo" in str(e)


def test_build_plans_from_mapa_report():
    result = build_plans_from_mapa(FIXTURES_MAPA)
    assert len(result["plans"]) == 2
    report = result["report"]
    assert "gestao-de-ofertas" in report["services"]
    assert report["total_tasks"] >= 5
    assert report["rollout_strategy"] == "expand-contract"
    assert report["ready_for_parallel_execution"] is True


def test_plan_repos_cli(tmp_path):
    import json
    import yaml
    from src.plan_repos import main
    import sys

    mapa = tmp_path / "mapa.yaml"
    mapa.write_text(yaml.safe_dump(FIXTURES_MAPA), encoding="utf-8")
    out = tmp_path / "out"
    argv = sys.argv
    try:
        sys.argv = [
            "plan_repos",
            "--mapa",
            str(mapa),
            "--service",
            "ms-cliente",
            "--out",
            str(out),
        ]
        main()
    finally:
        sys.argv = argv
    assert (out / "implementation_plan.yaml").is_file()
    data = json.loads((out / "implementation_plan.json").read_text(encoding="utf-8"))
    assert data["plans"][0]["service_id"] == "ms-cliente"
