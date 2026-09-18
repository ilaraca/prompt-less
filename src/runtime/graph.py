"""Grafo declarativo de estágios a partir de `config/pipeline.yaml`."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.runtime.stage import GraphError, HandlerRegistry

FOREACH_CONTEXT = "context"


@dataclass(frozen=True)
class GateSpec:
    when: str
    then: str = "blocked"


@dataclass(frozen=True)
class StageSpec:
    id: str
    handler: str
    depends_on: tuple[str, ...] = ()
    optional: bool = False
    enabled: bool = True
    retry: int = 0
    timeout_s: float | None = None
    foreach: str | None = None
    gates: tuple[GateSpec, ...] = ()
    desc: str = ""

    @property
    def is_foreach_context(self) -> bool:
        return self.foreach == FOREACH_CONTEXT


def load_stage_graph(cfg: dict[str, Any], registry: HandlerRegistry) -> list[StageSpec]:
    """
    Lê `cfg["stages"]`, valida o DAG e devolve em ordem topológica.

    Estágios `optional` e desligados são mantidos no grafo mas marcados
    `enabled=False` — o orquestrador os pula sem exigir handler.
    """
    raw = cfg.get("stages")
    if not isinstance(raw, list) or not raw:
        raise GraphError("pipeline.yaml precisa declarar stages: como lista não vazia")

    specs = [_parse_stage(item, i) for i, item in enumerate(raw)]
    ids = [s.id for s in specs]
    if len(ids) != len(set(ids)):
        dup = sorted({i for i in ids if ids.count(i) > 1})
        raise GraphError(f"id de estágio duplicado: {dup}")

    by_id = {s.id: s for s in specs}
    for spec in specs:
        for dep in spec.depends_on:
            if dep not in by_id:
                raise GraphError(f"estágio {spec.id!r} depende de id desconhecido {dep!r}")
        if spec.enabled and spec.handler not in registry:
            raise GraphError(
                f"estágio {spec.id!r} declara handler {spec.handler!r} ausente no registry"
            )
        if spec.retry < 0:
            raise GraphError(f"estágio {spec.id!r}: retry negativo")
        if spec.timeout_s is not None and spec.timeout_s <= 0:
            raise GraphError(f"estágio {spec.id!r}: timeout_s deve ser > 0")
        if spec.foreach not in (None, FOREACH_CONTEXT):
            raise GraphError(
                f"estágio {spec.id!r}: foreach {spec.foreach!r} inválido "
                f"(use '{FOREACH_CONTEXT}' ou omita)"
            )
        for gate in spec.gates:
            if gate.then != "blocked":
                raise GraphError(
                    f"estágio {spec.id!r}: gate.then {gate.then!r} não suportado "
                    "(fail-closed: só 'blocked')"
                )
            if not gate.when:
                raise GraphError(f"estágio {spec.id!r}: gate.when vazio")

    return topological_sort(specs)


def topological_sort(specs: list[StageSpec]) -> list[StageSpec]:
    """Kahn. Ciclo → GraphError (fail-closed)."""
    by_id = {s.id: s for s in specs}
    remaining = {s.id: set(s.depends_on) for s in specs}
    ready = [sid for sid, deps in remaining.items() if not deps]
    ordered: list[StageSpec] = []
    while ready:
        ready.sort()
        sid = ready.pop(0)
        ordered.append(by_id[sid])
        for other, deps in remaining.items():
            if sid in deps:
                deps.remove(sid)
                if not deps and other not in {s.id for s in ordered} and other not in ready:
                    ready.append(other)
    if len(ordered) != len(specs):
        stuck = sorted(set(remaining) - {s.id for s in ordered})
        raise GraphError(f"ciclo em depends_on envolvendo: {stuck}")
    return ordered


def _parse_stage(item: Any, index: int) -> StageSpec:
    if not isinstance(item, dict):
        raise GraphError(f"stages[{index}] precisa ser um mapeamento")
    sid = str(item.get("id") or "").strip()
    if not sid:
        raise GraphError(f"stages[{index}] sem id")
    handler = str(item.get("handler") or sid).strip()
    depends = item.get("depends_on") or []
    if not isinstance(depends, list) or any(not isinstance(d, str) for d in depends):
        raise GraphError(f"estágio {sid!r}: depends_on deve ser lista de ids")
    optional = bool(item.get("optional"))
    if "enabled" in item:
        enabled = bool(item.get("enabled"))
    else:
        enabled = not optional
    timeout_raw = item.get("timeout_s")
    timeout_s = float(timeout_raw) if timeout_raw is not None else None
    gates = tuple(_parse_gate(g, sid) for g in (item.get("gates") or []))
    foreach = item.get("foreach")
    return StageSpec(
        id=sid,
        handler=handler,
        depends_on=tuple(str(d) for d in depends),
        optional=optional,
        enabled=enabled,
        retry=int(item.get("retry") or 0),
        timeout_s=timeout_s,
        foreach=str(foreach) if foreach else None,
        gates=gates,
        desc=str(item.get("desc") or ""),
    )


def _parse_gate(item: Any, stage_id: str) -> GateSpec:
    if not isinstance(item, dict):
        raise GraphError(f"estágio {stage_id!r}: gate deve ser mapeamento")
    return GateSpec(when=str(item.get("when") or "").strip(), then=str(item.get("then") or "blocked"))
