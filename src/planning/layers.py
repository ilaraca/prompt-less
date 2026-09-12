"""Camadas e ordem canônica entre repositórios."""
from __future__ import annotations

import re
from typing import Iterable

# ordem de rollout expand-contract (produtores de contrato primeiro)
LAYER_ORDER = ("api", "gtw", "bff", "mfe", "worker", "batch")

LAYER_ALIASES = {
    "api": "api",
    "ms": "api",
    "svc": "api",
    "service": "api",
    "gtw": "gtw",
    "gateway": "gtw",
    "bff": "bff",
    "mfe": "mfe",
    "web": "mfe",
    "front": "mfe",
    "worker": "worker",
    "batch": "batch",
}


def infer_layer(repo_name: str) -> str | None:
    tokens = [t for t in re.split(r"[-_.]", repo_name.lower()) if t]
    for t in tokens:
        if t in LAYER_ALIASES:
            return LAYER_ALIASES[t]
    return None


def layer_rank(layer: str | None) -> int:
    if not layer:
        return len(LAYER_ORDER)
    try:
        return LAYER_ORDER.index(layer)
    except ValueError:
        return len(LAYER_ORDER)


def sort_repos_by_layer(repos: Iterable[str]) -> list[tuple[str, str | None]]:
    tagged = [(r, infer_layer(r)) for r in repos]
    return sorted(tagged, key=lambda x: (layer_rank(x[1]), x[0]))
