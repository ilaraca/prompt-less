"""Dependências observadas (código/contratos) para o plano multi-repo."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from src.domain.spec import CanonicalSpec, Operation
from src.planning.layers import infer_layer
from src.spec.evidence import parse_route

_LAYER_FALLBACK = "layer-fallback"
_MIN_ALIAS = 8


@dataclass
class ObservedDependency:
    """Aresta from → to com evidência e motivo."""

    source: str
    target: str
    type: str
    file: str | None = None
    symbol: str | None = None
    confidence: float = 0.5
    origin: str = "observed"
    reason: str = ""
    requires_review: bool = False
    line: int | None = None
    route: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "from": self.source,
            "to": self.target,
            "type": self.type,
            "file": self.file,
            "symbol": self.symbol,
            "confidence": self.confidence,
            "origin": self.origin,
            "reason": self.reason,
            "requires_review": self.requires_review,
        }
        if self.line is not None:
            data["line"] = self.line
        if self.route:
            data["route"] = self.route
        return data


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _repo_aliases(repo: str) -> list[str]:
    name = repo.lower()
    aliases = [name]
    layer = infer_layer(repo)
    if layer:
        suffix = f"-{layer}"
        if name.endswith(suffix) and len(name) > len(suffix):
            aliases.append(name[: -len(suffix)])
        prefix = f"{layer}-"
        if name.startswith(prefix) and len(name) > len(prefix):
            aliases.append(name[len(prefix) :])
    return aliases


def resolve_target(raw: str, repos: Iterable[str], source: str) -> str | None:
    """Resolve um alvo textual para um repositório único, ou None se ambíguo."""
    text = (raw or "").lower()
    if not text:
        return None
    compact_text = _compact(text)
    others = [r for r in repos if r != source]

    exact = [r for r in others if r.lower() in text]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        exact.sort(key=len, reverse=True)
        longest = exact[0]
        if all(longest.lower() in r.lower() for r in exact):
            return longest
        return None

    compact_hits: list[str] = []
    for repo in others:
        for alias in _repo_aliases(repo):
            compact_alias = _compact(alias)
            if len(compact_alias) >= _MIN_ALIAS and compact_alias in compact_text:
                compact_hits.append(repo)
                break
    unique = list(dict.fromkeys(compact_hits))
    if len(unique) == 1:
        return unique[0]
    return None


def _indexes_by_repo(repo_indexes: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Aceita índice por repo ou o índice de workspace (`servicos.*.repos`)."""
    if not repo_indexes:
        return {}
    if any(k in repo_indexes for k in ("rotas", "dependencias", "evidencias", "stack")):
        return {}
    if "servicos" in repo_indexes:
        merged: dict[str, dict[str, Any]] = {}
        for meta in (repo_indexes.get("servicos") or {}).values():
            for nome, idx in (meta.get("repos") or {}).items():
                merged[nome] = idx
        return merged
    # mapa repo → índice, possivelmente aninhado em um serviço
    if all(isinstance(v, dict) for v in repo_indexes.values()):
        sample: dict[str, Any] = next(iter(repo_indexes.values()), {})
        if "repos" in sample and "dependencias" not in sample:
            merged = {}
            for meta in repo_indexes.values():
                for nome, idx in (meta.get("repos") or {}).items():
                    merged[nome] = idx
            return merged
        return {k: v for k, v in repo_indexes.items() if isinstance(v, dict)}
    return {}


def _routes_by_repo(indexes: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for repo, idx in indexes.items():
        paths: list[str] = []
        for raw in idx.get("rotas") or []:
            _method, path = parse_route(str(raw))
            if path and path not in {"/", "/health", "/actuator"}:
                paths.append(path)
        for hit in idx.get("evidencias") or []:
            if hit.get("kind") != "route":
                continue
            _method, path = parse_route(str(hit.get("route") or ""))
            if path and path not in {"/", "/health", "/actuator"}:
                paths.append(path)
        out[repo] = list(dict.fromkeys(paths))
    return out


def _match_path_to_repo(
    path: str, routes: dict[str, list[str]], source: str
) -> str | None:
    norm = path if path.startswith("/") else f"/{path}"
    hits = [
        repo
        for repo, paths in routes.items()
        if repo != source and any(p == norm or p.endswith(norm) for p in paths)
    ]
    unique = list(dict.fromkeys(hits))
    return unique[0] if len(unique) == 1 else None


def _reason(kind: str, source: str, target: str, file: str | None, extra: str = "") -> str:
    loc = f" em `{file}`" if file else ""
    extra_bit = f" ({extra})" if extra else ""
    if kind == "openapi-client":
        return f"{source} consome OpenAPI client de {target}{loc}{extra_bit}"
    if kind == "import":
        return f"{source} importa módulo/pacote de {target}{loc}{extra_bit}"
    if kind == "url":
        return f"{source} chama URL de {target}{loc}{extra_bit}"
    if kind == "event":
        return f"{source} consome evento produzido por {target}{loc}{extra_bit}"
    if kind == "build":
        return f"arquivo de build de {source} declara {target}{loc}{extra_bit}"
    if kind == "spec-contract":
        return f"{source} consome contrato do Canonical Spec produzido por {target}{extra_bit}"
    if kind == _LAYER_FALLBACK:
        return (
            f"Topologia por camada: {source} depois de {target} "
            "(fallback heurístico; exige revisão)"
        )
    return f"{source} depende de {target}{loc}{extra_bit}"


def _edge(
    *,
    source: str,
    target: str,
    kind: str,
    hit: dict[str, Any],
    extra: str = "",
) -> ObservedDependency | None:
    if source == target:
        return None
    origin = str(hit.get("origin") or "observed")
    file = hit.get("file")
    symbol = hit.get("symbol")
    if origin == "observed" and not file and not symbol:
        return None
    return ObservedDependency(
        source=source,
        target=target,
        type=kind,
        file=file,
        symbol=symbol,
        confidence=float(hit.get("confidence") or 0.5),
        origin=origin,
        reason=_reason(kind, source, target, file, extra),
        requires_review=origin != "observed",
        line=int(hit["line"]) if hit.get("line") is not None else None,
        route=hit.get("route"),
    )


def extract_observed_dependencies(
    repos: list[str],
    repo_indexes: dict[str, Any] | None,
) -> list[ObservedDependency]:
    """Monta arestas observadas a partir do índice (clients, imports, URLs, eventos, build)."""
    indexes = _indexes_by_repo(repo_indexes or {})
    indexes = {r: indexes[r] for r in repos if r in indexes}
    if not indexes:
        return []

    routes = _routes_by_repo(indexes)
    edges: list[ObservedDependency] = []
    seen: set[tuple[str, str, str, str | None]] = set()
    producers: dict[str, list[str]] = {}

    for repo, idx in indexes.items():
        for hit in idx.get("dependencias") or []:
            if str(hit.get("kind") or "") == "event" and str(hit.get("role") or "") == "produce":
                producers.setdefault(str(hit.get("target") or ""), []).append(repo)

    def _add(dep: ObservedDependency | None) -> None:
        if dep is None:
            return
        key = (dep.source, dep.target, dep.type, dep.file)
        if key in seen:
            return
        seen.add(key)
        edges.append(dep)

    for repo, idx in indexes.items():
        for hit in idx.get("dependencias") or []:
            kind = str(hit.get("kind") or "")
            role = str(hit.get("role") or "")
            raw_target = str(hit.get("target") or "")
            if kind == "event" and role == "produce":
                continue
            if kind == "event" and role == "consume":
                makers = [r for r in producers.get(raw_target, []) if r != repo]
                if len(makers) != 1:
                    resolved = resolve_target(raw_target, repos, repo)
                    if not resolved:
                        continue
                    makers = [resolved]
                _add(
                    _edge(
                        source=repo,
                        target=makers[0],
                        kind="event",
                        hit=hit,
                        extra=raw_target,
                    )
                )
                continue
            resolved = resolve_target(raw_target, repos, repo)
            if not resolved and kind == "url" and "/" in raw_target:
                path = raw_target.split("/", 1)[-1]
                resolved = _match_path_to_repo("/" + path.lstrip("/"), routes, repo)
            if not resolved and kind in {"url", "openapi-client"}:
                parsed_path = parse_route(
                    "GET " + (raw_target if raw_target.startswith("/") else f"/{raw_target}")
                )[1]
                if parsed_path:
                    resolved = _match_path_to_repo(parsed_path, routes, repo)
            if not resolved:
                continue
            edge_kind = (
                kind if kind in {"openapi-client", "import", "url", "event", "build"} else "import"
            )
            _add(
                _edge(
                    source=repo,
                    target=resolved,
                    kind=edge_kind,
                    hit=hit,
                    extra=raw_target,
                )
            )

    return edges


def _operations_from_spec(spec: CanonicalSpec | dict[str, Any] | None) -> list[Operation]:
    if spec is None:
        return []
    if isinstance(spec, CanonicalSpec):
        return list(spec.operations)
    raw = spec.get("operations") or []
    return [Operation.from_raw(item) for item in raw]


def spec_contracts(
    spec: CanonicalSpec | dict[str, Any] | None,
) -> list[tuple[str, Operation]]:
    """Contratos produzidos/consumidos derivados do Canonical Spec."""
    out: list[tuple[str, Operation]] = []
    for op in _operations_from_spec(spec):
        method = (op.method or "").strip().upper()
        path = (op.path or "").strip()
        if not method or not path:
            continue
        out.append((f"spec:{op.id}:{method} {path}", op))
    return out


def producers_for_operation(
    op: Operation,
    repos: list[str],
    repo_indexes: dict[str, Any] | None,
) -> list[str]:
    indexes = _indexes_by_repo(repo_indexes or {})
    routes = _routes_by_repo({r: indexes[r] for r in repos if r in indexes})
    path = op.path or ""
    hits = [
        repo
        for repo, paths in routes.items()
        if any(p == path or p.endswith(path) for p in paths)
    ]
    unique = list(dict.fromkeys(hits))
    if unique:
        return unique
    apis = [r for r in repos if infer_layer(r) == "api"]
    return apis


def layer_fallback_dependency(source: str, target: str) -> ObservedDependency:
    return ObservedDependency(
        source=source,
        target=target,
        type=_LAYER_FALLBACK,
        file=None,
        symbol=None,
        confidence=0.4,
        origin="heuristic",
        reason=_reason(_LAYER_FALLBACK, source, target, None),
        requires_review=True,
    )
