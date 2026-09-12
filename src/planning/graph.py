"""Grafo de dependências entre tasks/repos."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any


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
        }


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
