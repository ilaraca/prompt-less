"""Monta implementation_plan multi-repo a partir de evidência observada."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from src.domain.spec import CanonicalSpec
from src.planning.dependencies import (
    ObservedDependency,
    extract_observed_dependencies,
    layer_fallback_dependency,
    producers_for_operation,
    spec_contracts,
)
from src.planning.graph import (
    PlanTask,
    analyze_tasks,
    find_cycles,
    global_repo_graph,
)
from src.planning.layers import LAYER_ORDER, infer_layer, layer_rank, sort_repos_by_layer


def _task_id(layer: str | None, index: int) -> str:
    return f"TASK-{(layer or 'app').upper()}-{index:02d}"


def _heuristic_changes(layer: str | None, contract: str, facade: str, repos: list[str]) -> tuple[list[str], list[str], list[str]]:
    if layer == "api":
        return [contract], [], [
            f"Expor/ajustar contrato {contract} no domínio",
            "Manter backward-compatible nesta fase",
        ]
    if layer == "gtw":
        return [f"gtw:{contract.split(':', 1)[-1]}"], [contract], [
            f"Publicar rota/agregação consumindo {contract}"
        ]
    if layer == "bff":
        return [facade], [contract], [f"Consumir {contract} e adaptar agregação BFF"]
    if layer == "mfe":
        has_bff = any(infer_layer(r) == "bff" for r in repos)
        consumes = [facade] if has_bff else [contract]
        return [], consumes, ["Atualizar UI/contratos de tela para o novo fluxo"]
    return [], [contract], ["Aplicar mudança alinhada ao contrato"]


def _make_tasks(
    *,
    service_id: str,
    repos: list[str],
    contract_version: str,
    spec: CanonicalSpec | dict[str, Any] | None,
    repo_indexes: dict[str, Any] | None,
) -> list[PlanTask]:
    ordered = sort_repos_by_layer(repos)
    by_layer: dict[str | None, list[str]] = defaultdict(list)
    for repo, layer in ordered:
        by_layer[layer].append(repo)

    contracts = spec_contracts(spec)
    contract = f"contract:{contract_version}"
    facade = f"bff-facade:{contract_version}"
    tasks: list[PlanTask] = []
    counts: dict[str | None, int] = defaultdict(int)

    for repo, layer in ordered:
        counts[layer] += 1
        produces: list[str] = []
        consumes: list[str] = []
        if contracts:
            for cid, op in contracts:
                producers = producers_for_operation(op, repos, repo_indexes)
                if repo in producers:
                    produces.append(cid)
                else:
                    consumes.append(cid)
            changes = [
                f"Contrato {cid} derivado do Canonical Spec ({op.method} {op.path})"
                for cid, op in contracts
                if cid in produces or cid in consumes
            ] or ["Aplicar mudança alinhada ao Canonical Spec"]
        else:
            produces, consumes, changes = _heuristic_changes(
                layer, contract, facade, repos
            )
        tasks.append(
            PlanTask(
                id=_task_id(layer, counts[layer]),
                repo=repo,
                layer=layer,
                service_id=service_id,
                changes=list(changes),
                produces=list(dict.fromkeys(produces)),
                consumes=list(dict.fromkeys(consumes)),
            )
        )
    return tasks


def _layer_pairs(tasks: list[PlanTask]) -> list[tuple[str, str]]:
    """Pares (consumer_repo, producer_repo) da topologia por camada."""
    by_layer: dict[str | None, list[PlanTask]] = defaultdict(list)
    for task in tasks:
        by_layer[task.layer].append(task)
    present = sorted(by_layer, key=lambda L: layer_rank(L))
    pairs: list[tuple[str, str]] = []
    for layer in present:
        prev_layers = [L for L in present if layer_rank(L) < layer_rank(layer)]
        if not prev_layers:
            continue
        previous = by_layer[prev_layers[-1]]
        for consumer in by_layer[layer]:
            for producer in previous:
                pairs.append((consumer.repo, producer.repo))
    return pairs


def _apply_dependencies(tasks: list[PlanTask], deps: list[ObservedDependency]) -> None:
    by_repo = {t.repo: t for t in tasks}
    for dep in deps:
        consumer = by_repo.get(dep.source)
        producer = by_repo.get(dep.target)
        if consumer is None:
            continue
        if producer is None:
            continue
        if producer.id not in consumer.depends_on:
            consumer.depends_on.append(producer.id)
        consumer.why_depends[producer.id] = dep.reason


def _select_dependencies(
    tasks: list[PlanTask],
    observed: list[ObservedDependency],
) -> list[ObservedDependency]:
    """Autoridade = observado; camada só cobre nós sem evidência (fallback)."""
    observed_from = {d.source for d in observed}
    selected = list(observed)
    for source, target in _layer_pairs(tasks):
        if source in observed_from:
            continue
        selected.append(layer_fallback_dependency(source, target))
    return selected


def build_implementation_plan(
    *,
    service_id: str,
    repos: list[str],
    service_name: str | None = None,
    contract_version: str = "v2",
    spec: CanonicalSpec | dict[str, Any] | None = None,
    repo_indexes: dict[str, Any] | None = None,
    reviewed: bool = False,
) -> dict[str, Any]:
    tasks = _make_tasks(
        service_id=service_id,
        repos=repos,
        contract_version=contract_version,
        spec=spec,
        repo_indexes=repo_indexes,
    )
    observed = extract_observed_dependencies(repos, repo_indexes)
    dependencies = _select_dependencies(tasks, observed)
    _apply_dependencies(tasks, dependencies)

    has_spec_contracts = bool(spec_contracts(spec))
    analysis = analyze_tasks(tasks, spec_contracts_only=has_spec_contracts)

    origins = {d.origin for d in dependencies} if dependencies else {"heuristic"}
    if origins == {"observed"}:
        origin = "observed"
    elif "observed" in origins and "heuristic" in origins:
        origin = "mixed"
    else:
        origin = "heuristic"

    requires_review = origin != "observed" or any(d.requires_review for d in dependencies)
    by_layer: dict[str | None, list[str]] = defaultdict(list)
    for task in tasks:
        by_layer[task.layer].append(task.repo)

    note = (
        "Dependências observadas no código/contratos são a autoridade; "
        "topologia por camada permanece fallback heurístico e exige revisão."
    )
    if origin == "heuristic":
        note = (
            "Topologia por camada é fallback heurístico, não evidência arquitetural. "
            "Substituir por dependencies descobertas (openapi-client, etc.) quando disponíveis."
        )

    return {
        "service_id": service_id,
        "service_name": service_name or service_id,
        "contract_version": contract_version,
        "origin": origin,
        "requires_review": requires_review,
        "reviewed": bool(reviewed),
        "tasks": [t.to_dict() for t in tasks],
        "dependencies": [d.to_dict() for d in dependencies],
        "waves": analysis.waves,
        "cycles": analysis.cycles,
        "scheduler_blockers": analysis.blockers,
        "parallelism": {
            "max_wave_size": max((len(w) for w in analysis.waves), default=0),
            "wave_count": len(analysis.waves),
        },
        "rollout": {
            "strategy": "expand-contract",
            "origin": origin,
            "requires_review": requires_review,
            "order": [
                "api backward-compatible",
                "bff/gtw",
                "mfe",
                "remover contrato antigo",
            ],
            "layers_present": [L for L in LAYER_ORDER if L in by_layer],
        },
        "note": note,
    }


def build_plans_from_mapa(
    mapa: dict[str, Any],
    *,
    service_ids: list[str] | None = None,
    contract_version: str = "v2",
    repo_index: dict[str, Any] | None = None,
    specs: dict[str, CanonicalSpec | dict[str, Any]] | None = None,
    reviewed: bool = False,
    coordination: dict[str, str] | None = None,
) -> dict[str, Any]:
    servicos = mapa.get("servicos") or {}
    ids = service_ids or list(servicos.keys())
    coord = coordination if coordination is not None else (mapa.get("coordenacao") or {})
    plans = []
    for sid in ids:
        meta = servicos.get(sid) or {}
        repos = list(meta.get("repos") or [])
        if not repos:
            continue
        indexes = _indexes_for_service(repo_index, sid, repos)
        spec = (specs or {}).get(sid)
        plans.append(
            build_implementation_plan(
                service_id=sid,
                repos=repos,
                service_name=meta.get("nome"),
                contract_version=contract_version,
                spec=spec,
                repo_indexes=indexes,
                reviewed=reviewed,
            )
        )
    return {
        "plans": plans,
        "reviewed": bool(reviewed),
        "report": integrate_report(plans, coordination=coord),
    }


def _indexes_for_service(
    repo_index: dict[str, Any] | None, service_id: str, repos: list[str]
) -> dict[str, Any] | None:
    if not repo_index:
        return None
    servicos = repo_index.get("servicos")
    if isinstance(servicos, dict):
        meta = servicos.get(service_id) or {}
        per_repo = dict(meta.get("repos") or {})
        if per_repo:
            return per_repo
    # índice plano repo → dados
    return {r: repo_index[r] for r in repos if r in repo_index} or repo_index


def integrate_report(
    plans: list[dict[str, Any]],
    *,
    coordination: dict[str, str] | None = None,
) -> dict[str, Any]:
    coord = coordination or {}
    repos = sorted({t["repo"] for p in plans for t in p.get("tasks") or []})
    total_tasks = sum(len(p.get("tasks") or []) for p in plans)
    repo_services: dict[str, set[str]] = defaultdict(set)
    for plan in plans:
        for task in plan.get("tasks") or []:
            repo_services[task["repo"]].add(plan["service_id"])
    shared = [
        {"repo": repo, "services": sorted(services)}
        for repo, services in sorted(repo_services.items())
        if len(services) > 1
    ]

    all_deps = [d for p in plans for d in (p.get("dependencies") or [])]
    nodes, edges = global_repo_graph(all_deps)
    cycles = find_cycles(nodes, edges)

    conflicts: list[dict[str, Any]] = []
    for item in shared:
        repo = item["repo"]
        if not coord.get(repo):
            conflicts.append(
                {
                    "kind": "uncoordinated_shared_repo",
                    "repo": repo,
                    "services": item["services"],
                }
            )

    for plan in plans:
        for blocker in plan.get("scheduler_blockers") or []:
            if blocker.get("kind") == "uncoordinated_shared_repo":
                conflicts.append(dict(blocker, service_id=plan.get("service_id")))

    blockers: list[dict[str, Any]] = []
    for cycle in cycles:
        blockers.append({"kind": "cycle", "nodes": cycle})
    for plan in plans:
        for item in plan.get("scheduler_blockers") or []:
            if item.get("kind") in {"cycle", "missing_dependency", "missing_contract"}:
                blockers.append(dict(item, service_id=plan.get("service_id")))

    reviewed = bool(plans) and all(bool(p.get("reviewed")) for p in plans)
    has_waves = all((p.get("parallelism") or {}).get("wave_count", 0) >= 1 for p in plans)
    ready = (
        reviewed
        and not conflicts
        and not blockers
        and has_waves
    )
    return {
        "services": [p["service_id"] for p in plans],
        "repositories": repos,
        "total_tasks": total_tasks,
        "total_waves": sum(int((p.get("parallelism") or {}).get("wave_count") or 0) for p in plans),
        "rollout_strategy": "expand-contract",
        "shared_repositories": shared,
        "cycles": cycles,
        "conflicts": conflicts,
        "scheduler_blockers": blockers,
        "ready_for_parallel_execution": ready,
    }
