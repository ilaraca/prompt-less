"""Planejamento multi-repositório baseado em evidência observada."""
from __future__ import annotations

from pathlib import Path

from src.domain.spec import CanonicalSpec, Operation
from src.planning.graph import PlanTask, topological_waves
from src.planning.layers import infer_layer, sort_repos_by_layer
from src.planning.plan import (
    build_implementation_plan,
    build_plans_from_mapa,
)
from src.repo_index import index_repo
from src.spec.builder import build_canonical_spec

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
    api = next(t for t in plan["tasks"] if t["layer"] == "api")
    bff = next(t for t in plan["tasks"] if t["layer"] == "bff")
    mfe = next(t for t in plan["tasks"] if t["layer"] == "mfe")
    assert "contract:v2" in api["produces"]
    assert "contract:v2" in bff["consumes"]
    assert api["id"] in bff["depends_on"]
    assert bff["id"] in mfe["depends_on"]
    assert plan["rollout"]["strategy"] == "expand-contract"
    assert plan["origin"] == "heuristic"
    assert plan["requires_review"] is True
    assert plan["reviewed"] is False
    fallback = [d for d in plan["dependencies"] if d["type"] == "layer-fallback"]
    assert fallback
    assert all(d["origin"] == "heuristic" and d["requires_review"] is True for d in fallback)
    assert all(d["reason"] for d in plan["dependencies"])
    assert bff["why_depends"][api["id"]]
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
    assert report["ready_for_parallel_execution"] is False
    reviewed = build_plans_from_mapa(FIXTURES_MAPA, reviewed=True)
    assert reviewed["report"]["ready_for_parallel_execution"] is True
    assert reviewed["report"]["conflicts"] == []
    assert reviewed["report"]["cycles"] == []


def test_plan_repos_cli(tmp_path):
    import json
    import sys

    import yaml

    from src.plan_repos import main

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
    assert "dependencies" in data["plans"][0]


def _write_observed_workspace(root: Path) -> dict:
    api = root / "ofertas-api"
    (api / "src").mkdir(parents=True)
    (api / "src" / "OfertaController.java").write_text(
        """\
@RequestMapping("/ofertas")
public class OfertaController {
    @GetMapping
    public ResponseEntity<?> listar() {
        kafkaTemplate.send("ofertas.created");
        return ResponseEntity.status(200).body(ok);
    }
}
""",
        encoding="utf-8",
    )
    (api / "openapi.yaml").write_text(
        "openapi: 3.0.0\npaths:\n  /ofertas:\n    get: {}\n",
        encoding="utf-8",
    )
    (api / "pom.xml").write_text(
        "<project><artifactId>ofertas-api</artifactId></project>\n",
        encoding="utf-8",
    )

    bff = root / "ofertas-bff"
    (bff / "src").mkdir(parents=True)
    (bff / "src" / "OfertasClient.java").write_text(
        """\
@FeignClient("ofertas-api")
public class OfertasClient {
    public void call() {}
}
""",
        encoding="utf-8",
    )
    (bff / "src" / "Listener.java").write_text(
        """\
public class Listener {
    @KafkaListener(topics = "ofertas.created")
    public void onCreated() {}
}
""",
        encoding="utf-8",
    )
    (bff / "src" / "http.ts").write_text(
        'export const url = "http://ofertas-api/ofertas";\n',
        encoding="utf-8",
    )
    (bff / "src" / "client.py").write_text(
        "from ofertas.api import Client\n",
        encoding="utf-8",
    )
    (bff / "package.json").write_text(
        '{"dependencies": {"ofertas-api": "1.0.0"}}\n',
        encoding="utf-8",
    )
    return {
        "ofertas-api": index_repo(api),
        "ofertas-bff": index_repo(bff),
    }


def test_observed_signals_feed_graph_with_evidence(tmp_path: Path):
    indexes = _write_observed_workspace(tmp_path)
    kinds = {
        hit["kind"]
        for idx in indexes.values()
        for hit in idx.get("dependencias") or []
    }
    assert {"openapi-client", "import", "url", "event", "build"} <= kinds

    plan = build_implementation_plan(
        service_id="ofertas",
        repos=["ofertas-api", "ofertas-bff"],
        repo_indexes=indexes,
    )
    deps = plan["dependencies"]
    observed = [d for d in deps if d["origin"] == "observed"]
    assert observed, "grafo deve ter arestas observadas"
    types = {d["type"] for d in observed}
    assert {"openapi-client", "import", "url", "event", "build"} <= types
    for dep in observed:
        assert dep["from"] and dep["to"] and dep["type"]
        assert dep["file"] or dep["symbol"]
        assert 0.0 <= dep["confidence"] <= 1.0
        assert dep["reason"]
        assert dep["from"] == "ofertas-bff"
        assert dep["to"] == "ofertas-api"
    assert plan["origin"] in {"observed", "mixed"}
    bff = next(t for t in plan["tasks"] if t["repo"] == "ofertas-bff")
    api = next(t for t in plan["tasks"] if t["repo"] == "ofertas-api")
    assert api["id"] in bff["depends_on"]
    assert bff["why_depends"][api["id"]]


def test_heuristic_fallback_marked_and_requires_review():
    plan = build_implementation_plan(
        service_id="s",
        repos=["ms-cliente", "bff-cliente"],
    )
    assert plan["origin"] == "heuristic"
    assert plan["requires_review"] is True
    assert all(d["type"] == "layer-fallback" for d in plan["dependencies"])
    assert all(d["requires_review"] is True for d in plan["dependencies"])
    assert all("fallback heurístico" in d["reason"] for d in plan["dependencies"])


def test_spec_contracts_derive_from_canonical_spec(tmp_path: Path):
    indexes = _write_observed_workspace(tmp_path)
    spec = build_canonical_spec(
        ui={"actions": [{"id": "listar", "method": "GET", "path": "/ofertas"}]},
        regras={},
        servico={"id": "ofertas", "repos": ["ofertas-api", "ofertas-bff"]},
    )
    assert any(op.method == "GET" and op.path == "/ofertas" for op in spec.operations)
    plan = build_implementation_plan(
        service_id="ofertas",
        repos=["ofertas-api", "ofertas-bff"],
        spec=spec,
        repo_indexes=indexes,
    )
    api = next(t for t in plan["tasks"] if t["repo"] == "ofertas-api")
    bff = next(t for t in plan["tasks"] if t["repo"] == "ofertas-bff")
    spec_ids = [c for c in api["produces"] if str(c).startswith("spec:")]
    assert spec_ids
    assert spec_ids[0] in bff["consumes"]
    assert "contract:v2" not in api["produces"]


def test_shared_repos_and_cycles_block_scheduler(tmp_path: Path):
    shared = {
        "servicos": {
            "a": {"repos": ["shared-lib", "svc-a-api"]},
            "b": {"repos": ["shared-lib", "svc-b-bff"]},
        }
    }
    result = build_plans_from_mapa(shared, reviewed=True)
    report = result["report"]
    assert any(item["repo"] == "shared-lib" for item in report["shared_repositories"])
    assert report["conflicts"]
    assert report["ready_for_parallel_execution"] is False

    coordinated = build_plans_from_mapa(
        {**shared, "coordenacao": {"shared-lib": "lock"}},
        reviewed=True,
    )
    assert coordinated["report"]["ready_for_parallel_execution"] is True

    api = tmp_path / "cycle-api"
    bff = tmp_path / "cycle-bff"
    (api / "src").mkdir(parents=True)
    (bff / "src").mkdir(parents=True)
    (api / "src" / "Peer.java").write_text(
        '@FeignClient("cycle-bff")\npublic class Peer {}\n', encoding="utf-8"
    )
    (bff / "src" / "Peer.java").write_text(
        '@FeignClient("cycle-api")\npublic class Peer {}\n', encoding="utf-8"
    )
    cyclic = build_implementation_plan(
        service_id="cycle",
        repos=["cycle-api", "cycle-bff"],
        repo_indexes={"cycle-api": index_repo(api), "cycle-bff": index_repo(bff)},
        reviewed=True,
    )
    assert cyclic["cycles"]
    assert any(b["kind"] == "cycle" for b in cyclic["scheduler_blockers"])
    assert cyclic["waves"] == []
    report = integrate_report([cyclic], coordination={})
    assert report["ready_for_parallel_execution"] is False
    assert report["cycles"] or report["scheduler_blockers"]


def test_missing_spec_contract_blocks_scheduler():
    spec = CanonicalSpec(
        version="1.0",
        service_id="orphan",
        repositories={"all": ["app-bff"]},
        claims=[],
        requirements=[],
        acceptance_criteria=[],
        operations=[
            Operation(id="OP-001", name="salvar", owner="orphan", method="POST", path="/x")
        ],
        errors=[],
        nfrs=[],
        open_questions=[],
    )
    plan = build_implementation_plan(
        service_id="orphan",
        repos=["app-bff"],
        spec=spec,
        reviewed=True,
    )
    assert any(b["kind"] == "missing_contract" for b in plan["scheduler_blockers"])
    report = integrate_report([plan])
    assert report["ready_for_parallel_execution"] is False


def test_ready_requires_reviewed_and_no_conflict():
    result = build_plans_from_mapa(FIXTURES_MAPA, reviewed=False)
    assert result["report"]["ready_for_parallel_execution"] is False
    ok = build_plans_from_mapa(FIXTURES_MAPA, reviewed=True)
    assert ok["report"]["ready_for_parallel_execution"] is True
