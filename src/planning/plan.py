"""Monta implementation_plan multi-repo a partir do mapa de serviços."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from src.planning.graph import PlanTask, topological_waves
from src.planning.layers import LAYER_ORDER, infer_layer, layer_rank, sort_repos_by_layer


def build_implementation_plan(
    *,
    service_id: str,
    repos: list[str],
    service_name: str | None = None,
    contract_version: str = "v2",
) -> dict[str, Any]:
    ordered = sort_repos_by_layer(repos)
    contract = f"contract:{contract_version}"
    facade = f"bff-facade:{contract_version}"

    # agrupa por camada preservando ordem
    by_layer: dict[str | None, list[str]] = defaultdict(list)
    for repo, layer in ordered:
        by_layer[layer].append(repo)

    tasks: list[PlanTask] = []
    layer_task_ids: dict[str | None, list[str]] = defaultdict(list)
    # camadas presentes ordenadas
    present_layers = sorted(
        {layer for _, layer in ordered},
        key=lambda L: layer_rank(L),
    )

    for layer in present_layers:
        prev_layers = [L for L in present_layers if layer_rank(L) < layer_rank(layer)]
        # dependência imediata: só a camada anterior presente
        immediate_prev = prev_layers[-1] if prev_layers else None
        depends = list(layer_task_ids.get(immediate_prev, [])) if immediate_prev is not None else []

        for i, repo in enumerate(by_layer[layer], start=1):
            layer_key = (layer or "app").upper()
            task_id = f"TASK-{layer_key}-{i:02d}"
            produces: list[str] = []
            consumes: list[str] = []
            changes: list[str] = []

            if layer == "api":
                produces = [contract]
                changes = [
                    f"Expor/ajustar contrato {contract} no domínio",
                    "Manter backward-compatible nesta fase",
                ]
            elif layer == "gtw":
                consumes = [contract]
                produces = [f"gtw:{contract_version}"]
                changes = [f"Publicar rota/agregação consumindo {contract}"]
            elif layer == "bff":
                consumes = [contract]
                produces = [facade]
                changes = [f"Consumir {contract} e adaptar agregação BFF"]
            elif layer == "mfe":
                has_bff = any(infer_layer(r) == "bff" for r in repos)
                consumes = [facade] if has_bff else [contract]
                changes = ["Atualizar UI/contratos de tela para o novo fluxo"]
            else:
                consumes = [contract]
                changes = ["Aplicar mudança alinhada ao contrato"]

            tasks.append(
                PlanTask(
                    id=task_id,
                    repo=repo,
                    layer=layer,
                    service_id=service_id,
                    changes=changes,
                    depends_on=list(depends),
                    produces=produces,
                    consumes=consumes,
                )
            )
            layer_task_ids[layer].append(task_id)

    waves = topological_waves(tasks)
    return {
        "service_id": service_id,
        "service_name": service_name or service_id,
        "contract_version": contract_version,
        "tasks": [t.to_dict() for t in tasks],
        "waves": waves,
        "parallelism": {
            "max_wave_size": max((len(w) for w in waves), default=0),
            "wave_count": len(waves),
        },
        "rollout": {
            "strategy": "expand-contract",
            "order": [
                "api backward-compatible",
                "bff/gtw",
                "mfe",
                "remover contrato antigo",
            ],
            "layers_present": [L for L in LAYER_ORDER if L in by_layer],
        },
    }


def build_plans_from_mapa(
    mapa: dict[str, Any],
    *,
    service_ids: list[str] | None = None,
    contract_version: str = "v2",
) -> dict[str, Any]:
    servicos = mapa.get("servicos") or {}
    ids = service_ids or list(servicos.keys())
    plans = []
    for sid in ids:
        meta = servicos.get(sid) or {}
        repos = list(meta.get("repos") or [])
        if not repos:
            continue
        plans.append(
            build_implementation_plan(
                service_id=sid,
                repos=repos,
                service_name=meta.get("nome"),
                contract_version=contract_version,
            )
        )
    return {
        "plans": plans,
        "report": integrate_report(plans),
    }


def integrate_report(plans: list[dict[str, Any]]) -> dict[str, Any]:
    repos = sorted({t["repo"] for p in plans for t in p.get("tasks") or []})
    total_tasks = sum(len(p.get("tasks") or []) for p in plans)
    return {
        "services": [p["service_id"] for p in plans],
        "repositories": repos,
        "total_tasks": total_tasks,
        "total_waves": sum(int((p.get("parallelism") or {}).get("wave_count") or 0) for p in plans),
        "rollout_strategy": "expand-contract",
        "ready_for_parallel_execution": all(
            (p.get("parallelism") or {}).get("wave_count", 0) >= 1 for p in plans
        ),
    }
