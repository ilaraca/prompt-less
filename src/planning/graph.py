"""Grafo de dependências entre tasks/repos."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class PlanTask:
    id: str
    repo: str
    layer: str | None
    service_id: str
    changes: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    produces: list[str] = field(default_factory=list)
    consumes: list[str] = field(default_factory=list)
    why_depends: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "repo": self.repo,
            "layer": self.layer,
            "service_id": self.service_id,
            "changes": list(self.changes),
            "depends_on": list(self.depends_on),
            "produces": list(self.produces),
            "consumes": list(self.consumes),
            "why_depends": dict(self.why_depends),
        }


@dataclass
class GraphAnalysis:
    waves: list[list[str]]
    cycles: list[list[str]]
    missing: list[dict[str, Any]]
    blockers: list[dict[str, Any]]
    shared_in_wave: list[dict[str, Any]]


def find_cycles(nodes: Iterable[str], edges: Iterable[tuple[str, str]]) -> list[list[str]]:
    """Ciclos no grafo dirigido (lista de nós fechando o ciclo)."""
    adj: dict[str, list[str]] = defaultdict(list)
    node_set = list(dict.fromkeys(nodes))
    for src, dst in edges:
        adj[src].append(dst)
        if src not in node_set:
            node_set.append(src)
        if dst not in node_set:
            node_set.append(dst)
    cycles: list[list[str]] = []
    state = {n: 0 for n in node_set}
    stack: list[str] = []

    def dfs(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for nxt in adj.get(node, []):
            if nxt not in state:
                continue
            if state[nxt] == 1:
                start = stack.index(nxt)
                cycles.append(stack[start:] + [nxt])
            elif state[nxt] == 0:
                dfs(nxt)
        stack.pop()
        state[node] = 2

    for node in node_set:
        if state[node] == 0:
            dfs(node)
    return cycles


def analyze_tasks(
    tasks: list[PlanTask],
    *,
    spec_contracts_only: bool = False,
) -> GraphAnalysis:
    """Ondas, ciclos, dependências ausentes e repos compartilhado na mesma onda."""
    by_id = {t.id: t for t in tasks}
    missing: list[dict[str, Any]] = []
    produced = {c for t in tasks for c in t.produces}
    for task in tasks:
        for dep in task.depends_on:
            if dep not in by_id:
                missing.append(
                    {
                        "kind": "missing_dependency",
                        "from": task.id,
                        "to": dep,
                        "repo": task.repo,
                    }
                )
        for contract in task.consumes:
            if spec_contracts_only and not str(contract).startswith("spec:"):
                continue
            if contract not in produced:
                missing.append(
                    {
                        "kind": "missing_contract",
                        "from": task.repo,
                        "task": task.id,
                        "contract": contract,
                    }
                )

    edges = [
        (task.id, dep)
        for task in tasks
        for dep in task.depends_on
        if dep in by_id
    ]
    cycles = find_cycles([t.id for t in tasks], edges)
    blockers: list[dict[str, Any]] = []
    for cycle in cycles:
        blockers.append({"kind": "cycle", "nodes": cycle})
    for item in missing:
        blockers.append(item)

    waves: list[list[str]] = []
    if not cycles:
        try:
            waves = topological_waves(tasks)
        except ValueError:
            waves = []
            if not any(b.get("kind") == "cycle" for b in blockers):
                blockers.append({"kind": "cycle", "nodes": []})

    shared_in_wave: list[dict[str, Any]] = []
    for wave in waves:
        repos: dict[str, list[str]] = defaultdict(list)
        for tid in wave:
            task = by_id.get(tid)
            if task:
                repos[task.repo].append(tid)
        for repo, tids in repos.items():
            if len(tids) > 1:
                shared_in_wave.append(
                    {
                        "kind": "uncoordinated_shared_repo",
                        "repo": repo,
                        "tasks": tids,
                        "wave": list(wave),
                    }
                )
                blockers.append(
                    {
                        "kind": "uncoordinated_shared_repo",
                        "repo": repo,
                        "tasks": tids,
                    }
                )

    return GraphAnalysis(
        waves=waves,
        cycles=cycles,
        missing=missing,
        blockers=blockers,
        shared_in_wave=shared_in_wave,
    )


def global_repo_graph(
    dependencies: Iterable[dict[str, Any]],
) -> tuple[list[str], list[tuple[str, str]]]:
    nodes: list[str] = []
    edges: list[tuple[str, str]] = []
    for dep in dependencies:
        src = str(dep.get("from") or "")
        dst = str(dep.get("to") or "")
        if not src or not dst:
            continue
        if src not in nodes:
            nodes.append(src)
        if dst not in nodes:
            nodes.append(dst)
        edges.append((src, dst))
    return nodes, edges


def topological_waves(tasks: list[PlanTask]) -> list[list[str]]:
    """Retorna ondas de task ids que podem rodar em paralelo."""
    by_id = {t.id: t for t in tasks}
    indegree = {t.id: 0 for t in tasks}
    children: dict[str, list[str]] = defaultdict(list)
    for t in tasks:
        for dep in t.depends_on:
            if dep not in by_id:
                continue
            indegree[t.id] += 1
            children[dep].append(t.id)

    ready = deque(sorted(tid for tid, d in indegree.items() if d == 0))
    waves: list[list[str]] = []
    seen = 0
    while ready:
        wave = list(ready)
        waves.append(wave)
        ready.clear()
        for tid in wave:
            seen += 1
            for child in children[tid]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
        ready = deque(sorted(ready))

    if seen != len(tasks):
        raise ValueError("ciclo detectado no grafo de dependências")
    return waves
