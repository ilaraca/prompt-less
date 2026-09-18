"""Defaults de engenharia (stack, NFRs, documentação) — baseline v2 selecionável.

Schema versionado em `config/engenharia.schema.yaml`. Templates v1 migram na
ingest (`dehydrate_engenharia`). NFRs têm IDs estáveis compartilhados entre
história, PRD e tasks SDD; a seleção corta por camada + criticidade para não
inflar o prompt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "config" / "engenharia.schema.yaml"
SCHEMA_VERSION = 2

# Mapeamento stack → padrão de doc de API (quando `api_docs.por_linguagem` não cobre)
_LANG_DOC = {
    "java": "javadoc",
    "kotlin": "kdoc",
    "scala": "scaladoc",
    "typescript": "tsdoc",
    "javascript": "jsdoc",
    "python": "docstring",
    "go": "godoc",
    "golang": "godoc",
    "csharp": "xml-doc",
    "c#": "xml-doc",
    ".net": "xml-doc",
    "rust": "rustdoc",
    "php": "phpdoc",
    "ruby": "yard",
    "swift": "docc",
}

CRITICIDADE_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
NFR_ORIGINS = frozenset({"baseline", "declared", "observed"})
ALL_LAYERS = ("api", "gtw", "bff", "mfe", "worker", "batch")

DEFAULT_ENGENHARIA: dict[str, Any] = {
    "version": SCHEMA_VERSION,
    "criticidade": "medium",
    "stack": {"bff": ["(definir)"], "mfe": ["(definir)"]},
    "padroes": ["openapi-first"],
    "arquitetura": {"fluxo": "MFE -> BFF -> API Domínio", "contrato": "openapi"},
    "resiliencia": {
        "timeout_ms": 2000,
        "retry": {"max_attempts": 2, "backoff": "exponential"},
        "circuit_breaker": {
            "enabled": True,
            "failure_threshold": 5,
            "reset_timeout_ms": 30000,
        },
        "idempotencia": {"enabled": True, "key_header": "Idempotency-Key"},
    },
    "observabilidade": {
        "logs": {
            "formato": "structured_json",
            "campos_minimos": [
                "timestamp",
                "level",
                "service",
                "correlation_id",
                "message",
            ],
            "sem_pii": True,
        },
        "metrics": {
            "enabled": True,
            "padrao": "red",  # rate, errors, duration
            "export": "prometheus",
        },
        "tracing": {
            "enabled": True,
            "padrao": "w3c-tracecontext",
            "sampler": "parentbased_traceidratio",
        },
    },
    "seguranca": {
        "validar_input": True,
        "authn": "required",
        "authz": "required",
    },
    "documentacao": {
        "readme": {
            "obrigatorio": True,
            "secoes_minimas": [
                "proposito",
                "como-rodar-local",
                "arquitetura",
                "endpoints-ou-contratos",
                "variaveis-de-ambiente",
                "ownership",
            ],
        },
        "changelog": {
            "obrigatorio": True,
            "formato": "keep-a-changelog",
            "path": "CHANGELOG.md",
        },
        "api_docs": {
            "obrigatorio": True,
            "por_linguagem": {
                "java": "javadoc",
                "kotlin": "kdoc",
                "typescript": "tsdoc",
                "javascript": "jsdoc",
                "python": "docstring",
                "go": "godoc",
                "csharp": "xml-doc",
                "rust": "rustdoc",
            },
        },
    },
}


@dataclass(frozen=True)
class NfrDef:
    """Definição canônica de um NFR — ID estável para história/PRD/SDD."""

    id: str
    category: str
    text_template: str
    layers: tuple[str, ...]
    min_criticidade: str
    # caminho no YAML para detectar override declared (ex.: resiliencia.timeout_ms)
    declared_paths: tuple[tuple[str, ...], ...] = ()
    # sinais no índice de código → origem observed
    signals: tuple[str, ...] = ()
    gap_if_missing: bool = False


@dataclass
class SelectedNfr:
    id: str
    category: str
    text: str
    origin: str  # baseline | declared | observed
    layers: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def to_requirement_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "origin": self.origin,
            "status": self.origin,
            "category": self.category,
            "layers": list(self.layers),
            "source_claims": [],
        }


# Catálogo v2 — IDs compartilhados (NFR-*-NN, dois dígitos).
NFR_CATALOG: tuple[NfrDef, ...] = (
    NfrDef(
        id="NFR-R-01",
        category="resiliencia",
        text_template="Timeout de `{timeout_ms}ms` nas chamadas síncronas",
        layers=("api", "gtw", "bff", "worker", "batch"),
        min_criticidade="low",
        declared_paths=(("resiliencia", "timeout_ms"),),
        signals=("timeout", "Timeout", "Duration.of", "@Timeout"),
        gap_if_missing=True,
    ),
    NfrDef(
        id="NFR-R-02",
        category="resiliencia",
        text_template="Retry: `{max_attempts}` tentativas, backoff `{backoff}`",
        layers=("api", "gtw", "bff", "worker", "batch"),
        min_criticidade="low",
        declared_paths=(("resiliencia", "retry"),),
        signals=("Retry", "@Retry", "retry", "Backoff", "Resilience4j"),
        gap_if_missing=True,
    ),
    NfrDef(
        id="NFR-R-03",
        category="resiliencia",
        text_template=(
            "Circuit breaker (threshold `{failure_threshold}`, "
            "reset `{reset_timeout_ms}ms`)"
        ),
        layers=("api", "gtw", "bff", "worker"),
        min_criticidade="medium",
        declared_paths=(("resiliencia", "circuit_breaker"),),
        signals=(
            "CircuitBreaker",
            "circuit_breaker",
            "circuitBreaker",
            "Resilience4j",
            "@CircuitBreaker",
        ),
        gap_if_missing=True,
    ),
    NfrDef(
        id="NFR-R-04",
        category="resiliencia",
        text_template="Idempotência via header `{key_header}` em mutações",
        layers=("api", "bff", "worker"),
        min_criticidade="high",
        declared_paths=(("resiliencia", "idempotencia"),),
        signals=(
            "Idempotency-Key",
            "Idempotent",
            "idempoten",
            "IdempotencyKey",
        ),
        gap_if_missing=True,
    ),
    NfrDef(
        id="NFR-O-01",
        category="observabilidade",
        text_template="Logs `{formato}` com campos: {campos}",
        layers=("api", "gtw", "bff", "mfe", "worker", "batch"),
        min_criticidade="low",
        declared_paths=(("observabilidade", "logs"),),
        signals=("correlation_id", "structured", "Logger", "slf4j", "pino"),
        gap_if_missing=False,
    ),
    NfrDef(
        id="NFR-O-02",
        category="observabilidade",
        text_template="Não logar PII / dados sensíveis",
        layers=("api", "gtw", "bff", "mfe", "worker", "batch"),
        min_criticidade="low",
        declared_paths=(("observabilidade", "logs", "sem_pii"),),
        signals=("sem_pii", "redact", "maskPii", "PII"),
        gap_if_missing=False,
    ),
    NfrDef(
        id="NFR-O-03",
        category="observabilidade",
        text_template="Métricas `{padrao}` export `{export}`",
        layers=("api", "gtw", "bff", "worker", "batch"),
        min_criticidade="medium",
        declared_paths=(("observabilidade", "metrics"),),
        signals=(
            "MeterRegistry",
            "micrometer",
            "prometheus",
            "Counter",
            "Timer",
            "metrics",
        ),
        gap_if_missing=True,
    ),
    NfrDef(
        id="NFR-O-04",
        category="observabilidade",
        text_template="Tracing `{padrao}` (sampler `{sampler}`)",
        layers=("api", "gtw", "bff", "worker"),
        min_criticidade="high",
        declared_paths=(("observabilidade", "tracing"),),
        signals=(
            "OpenTelemetry",
            "otel",
            "Tracer",
            "Span",
            "traceparent",
            "Brave",
            "Zipkin",
        ),
        gap_if_missing=True,
    ),
    NfrDef(
        id="NFR-S-01",
        category="seguranca",
        text_template="Validar input na borda (BFF/API)",
        layers=("api", "gtw", "bff", "mfe"),
        min_criticidade="low",
        declared_paths=(("seguranca", "validar_input"),),
        signals=("@Valid", "Validator", "zod", "joi", "BeanValidation"),
        gap_if_missing=False,
    ),
    NfrDef(
        id="NFR-S-02",
        category="seguranca",
        text_template="Autenticação (`authn`) obrigatória nas rotas protegidas",
        layers=("api", "gtw", "bff"),
        min_criticidade="medium",
        declared_paths=(("seguranca", "authn"),),
        signals=(
            "SecurityFilterChain",
            "Bearer",
            "JWT",
            "oauth2",
            "@PreAuthorize",
            "authenticate",
        ),
        gap_if_missing=True,
    ),
    NfrDef(
        id="NFR-S-03",
        category="seguranca",
        text_template="Autorização (`authz`) por papel/escopo",
        layers=("api", "gtw", "bff"),
        min_criticidade="high",
        declared_paths=(("seguranca", "authz"),),
        signals=("@PreAuthorize", "hasRole", "hasAuthority", "RBAC", "authorize"),
        gap_if_missing=True,
    ),
    NfrDef(
        id="NFR-D-01",
        category="documentacao",
        text_template="README.md estruturado com seções mínimas: {secoes}",
        layers=("api", "gtw", "bff", "mfe", "worker", "batch"),
        min_criticidade="low",
        declared_paths=(("documentacao", "readme"),),
        signals=("README.md",),
        gap_if_missing=False,
    ),
    NfrDef(
        id="NFR-D-02",
        category="documentacao",
        text_template="`{changelog_path}` no formato `{changelog_formato}`",
        layers=("api", "gtw", "bff", "mfe", "worker", "batch"),
        min_criticidade="low",
        declared_paths=(("documentacao", "changelog"),),
        signals=("CHANGELOG.md",),
        gap_if_missing=False,
    ),
    NfrDef(
        id="NFR-D-03",
        category="documentacao",
        text_template="Documentação de API/código pública: {api_docs}",
        layers=("api", "gtw", "bff", "mfe"),
        min_criticidade="low",
        declared_paths=(("documentacao", "api_docs"),),
        signals=("javadoc", "tsdoc", "godoc", "OpenAPI", "swagger"),
        gap_if_missing=False,
    ),
)

_CATALOG_BY_ID = {n.id: n for n in NFR_CATALOG}


def _deep_get(data: dict[str, Any] | None, path: tuple[str, ...]) -> Any:
    cur: Any = data or {}
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def _path_declared(raw: dict[str, Any] | None, path: tuple[str, ...]) -> bool:
    """True se o YAML original declara o caminho (mesmo que parcial)."""
    if not raw:
        return False
    cur: Any = raw
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return False
        cur = cur[key]
    return True


def _crit_ok(min_c: str, actual: str) -> bool:
    return CRITICIDADE_RANK.get(actual, 1) >= CRITICIDADE_RANK.get(min_c, 0)


def _merge_section(
    base: dict[str, Any], override: dict[str, Any] | None, *, nested: tuple[str, ...] = ()
) -> dict[str, Any]:
    if not isinstance(override, dict):
        return dict(base)
    merged = {**base, **override}
    for key in nested:
        if isinstance(override.get(key), dict) and isinstance(base.get(key), dict):
            merged[key] = {**(base.get(key) or {}), **override[key]}
    return merged


def migrate_engenharia(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Migra template v1 (ou ausente) para o envelope v2 sem perder overrides."""
    src = dict(raw or {})
    version = int(src.get("version") or 1)
    migrated_from = version if version < SCHEMA_VERSION else None

    # Defaults v2 + overrides do arquivo
    out = {**DEFAULT_ENGENHARIA, **src}
    out["version"] = SCHEMA_VERSION
    out["criticidade"] = str(src.get("criticidade") or DEFAULT_ENGENHARIA["criticidade"])

    out["stack"] = _merge_section(
        dict(DEFAULT_ENGENHARIA["stack"]),
        src.get("stack") if isinstance(src.get("stack"), dict) else None,
    )
    out["arquitetura"] = _merge_section(
        dict(DEFAULT_ENGENHARIA["arquitetura"]),
        src.get("arquitetura") if isinstance(src.get("arquitetura"), dict) else None,
    )
    out["resiliencia"] = _merge_section(
        dict(DEFAULT_ENGENHARIA["resiliencia"]),
        src.get("resiliencia") if isinstance(src.get("resiliencia"), dict) else None,
        nested=("retry", "circuit_breaker", "idempotencia"),
    )
    out["observabilidade"] = _merge_section(
        dict(DEFAULT_ENGENHARIA["observabilidade"]),
        src.get("observabilidade")
        if isinstance(src.get("observabilidade"), dict)
        else None,
        nested=("logs", "metrics", "tracing"),
    )
    out["seguranca"] = _merge_section(
        dict(DEFAULT_ENGENHARIA["seguranca"]),
        src.get("seguranca") if isinstance(src.get("seguranca"), dict) else None,
    )

    doc_base = dict(DEFAULT_ENGENHARIA["documentacao"])
    doc_over = src.get("documentacao") if isinstance(src.get("documentacao"), dict) else None
    if isinstance(doc_over, dict):
        merged_doc = {**doc_base, **doc_over}
        for sub in ("readme", "changelog", "api_docs"):
            if isinstance(doc_over.get(sub), dict):
                merged_doc[sub] = {**(doc_base.get(sub) or {}), **doc_over[sub]}
                if sub == "api_docs" and isinstance(
                    doc_over[sub].get("por_linguagem"), dict
                ):
                    merged_doc[sub]["por_linguagem"] = {
                        **((doc_base.get(sub) or {}).get("por_linguagem") or {}),
                        **doc_over[sub]["por_linguagem"],
                    }
        out["documentacao"] = merged_doc
    else:
        out["documentacao"] = doc_base

    if isinstance(src.get("padroes"), list):
        out["padroes"] = list(src["padroes"])
    else:
        out["padroes"] = list(DEFAULT_ENGENHARIA["padroes"])

    meta = {"schema_version": SCHEMA_VERSION}
    if migrated_from is not None:
        meta["migrated_from"] = migrated_from
    out["_meta"] = meta
    out["_raw_declared"] = src  # só em memória; removido no dehydrate público
    return out


def dehydrate_engenharia(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Normaliza engenharia.yaml; migra v1→v2 e preenche baseline se ausente."""
    if (
        isinstance(raw, dict)
        and raw.get("_declared_nfrs") is not None
        and int(raw.get("version") or 0) >= SCHEMA_VERSION
    ):
        # idempotente — evita remarcar defaults como declared
        return raw
    migrated = migrate_engenharia(raw)
    raw_declared = migrated.pop("_raw_declared", raw or {})
    # expõe mapa de paths declared para seleção de origem
    declared_flags: dict[str, bool] = {}
    for nfr in NFR_CATALOG:
        declared_flags[nfr.id] = any(
            _path_declared(raw_declared if isinstance(raw_declared, dict) else None, p)
            for p in nfr.declared_paths
        )
    migrated["_declared_nfrs"] = declared_flags
    return migrated


def validate_engenharia_schema(eng: dict[str, Any]) -> list[str]:
    """Validação estrutural leve alinhada a `config/engenharia.schema.yaml`."""
    errors: list[str] = []
    if not isinstance(eng, dict):
        return ["engenharia não é um objeto"]
    version = eng.get("version")
    if version not in (1, 2, SCHEMA_VERSION):
        errors.append(f"version inválida: {version!r} (espere 1 ou 2)")
    crit = eng.get("criticidade")
    if crit is not None and crit not in CRITICIDADE_RANK:
        errors.append(f"criticidade inválida: {crit!r}")
    for key in ("resiliencia", "observabilidade", "seguranca", "documentacao", "stack"):
        if key in eng and eng[key] is not None and not isinstance(eng[key], dict):
            errors.append(f"{key} deve ser objeto")
    res = eng.get("resiliencia") or {}
    if isinstance(res, dict):
        if "timeout_ms" in res and res["timeout_ms"] is not None:
            try:
                if int(res["timeout_ms"]) <= 0:
                    errors.append("resiliencia.timeout_ms deve ser > 0")
            except (TypeError, ValueError):
                errors.append("resiliencia.timeout_ms deve ser inteiro")
        cb = res.get("circuit_breaker")
        if cb is not None and not isinstance(cb, dict):
            errors.append("resiliencia.circuit_breaker deve ser objeto")
        idem = res.get("idempotencia")
        if idem is not None and not isinstance(idem, (dict, bool)):
            errors.append("resiliencia.idempotencia deve ser objeto ou bool")
    obs = eng.get("observabilidade") or {}
    if isinstance(obs, dict):
        for sub in ("metrics", "tracing", "logs"):
            if sub in obs and obs[sub] is not None and not isinstance(obs[sub], dict):
                errors.append(f"observabilidade.{sub} deve ser objeto")
    return errors


def _render_text(defn: NfrDef, eng: dict[str, Any]) -> str:
    r = eng.get("resiliencia") or {}
    retry = r.get("retry") if isinstance(r.get("retry"), dict) else {}
    cb = r.get("circuit_breaker") if isinstance(r.get("circuit_breaker"), dict) else {}
    idem = r.get("idempotencia")
    if isinstance(idem, bool):
        idem = {"enabled": idem, "key_header": "Idempotency-Key"}
    if not isinstance(idem, dict):
        idem = {}
    o = eng.get("observabilidade") or {}
    logs = o.get("logs") if isinstance(o.get("logs"), dict) else {}
    metrics = o.get("metrics") if isinstance(o.get("metrics"), dict) else {}
    tracing = o.get("tracing") if isinstance(o.get("tracing"), dict) else {}
    doc = eng.get("documentacao") or {}
    readme = doc.get("readme") if isinstance(doc.get("readme"), dict) else {}
    changelog = doc.get("changelog") if isinstance(doc.get("changelog"), dict) else {}
    campos = ", ".join(str(c) for c in (logs.get("campos_minimos") or [])) or "(mínimos)"
    secoes = ", ".join(f"`{s}`" for s in (readme.get("secoes_minimas") or [])) or "(a definir)"
    api_std = ", ".join(f"**{lang}** → `{std}`" for lang, std in _api_doc_standards(eng))
    return defn.text_template.format(
        timeout_ms=r.get("timeout_ms", "?"),
        max_attempts=retry.get("max_attempts", "?"),
        backoff=retry.get("backoff", "?"),
        failure_threshold=cb.get("failure_threshold", "?"),
        reset_timeout_ms=cb.get("reset_timeout_ms", "?"),
        key_header=idem.get("key_header") or "Idempotency-Key",
        formato=logs.get("formato", "structured"),
        campos=campos,
        padrao=metrics.get("padrao") or tracing.get("padrao") or "?",
        export=metrics.get("export", "?"),
        sampler=tracing.get("sampler", "?"),
        secoes=secoes,
        changelog_path=changelog.get("path") or "CHANGELOG.md",
        changelog_formato=changelog.get("formato") or "keep-a-changelog",
        api_docs=api_std or "api-docs",
    )


def _nfr_enabled(defn: NfrDef, eng: dict[str, Any]) -> bool:
    """Respeita flags enabled=false / validar_input=false no YAML."""
    if defn.id == "NFR-R-03":
        cb = (eng.get("resiliencia") or {}).get("circuit_breaker")
        if isinstance(cb, dict) and cb.get("enabled") is False:
            return False
    if defn.id == "NFR-R-04":
        idem = (eng.get("resiliencia") or {}).get("idempotencia")
        if idem is False:
            return False
        if isinstance(idem, dict) and idem.get("enabled") is False:
            return False
    if defn.id == "NFR-O-03":
        m = (eng.get("observabilidade") or {}).get("metrics")
        if isinstance(m, dict) and m.get("enabled") is False:
            return False
    if defn.id == "NFR-O-04":
        t = (eng.get("observabilidade") or {}).get("tracing")
        if isinstance(t, dict) and t.get("enabled") is False:
            return False
    if defn.id == "NFR-S-01":
        if (eng.get("seguranca") or {}).get("validar_input") is False:
            return False
    if defn.id == "NFR-O-02":
        logs = (eng.get("observabilidade") or {}).get("logs") or {}
        if isinstance(logs, dict) and logs.get("sem_pii") is False:
            return False
    if defn.id.startswith("NFR-D-"):
        doc = eng.get("documentacao") or {}
        key = {"NFR-D-01": "readme", "NFR-D-02": "changelog", "NFR-D-03": "api_docs"}[
            defn.id
        ]
        section = doc.get(key) if isinstance(doc.get(key), dict) else {}
        if section.get("obrigatorio") is False:
            return False
    return True


def select_nfrs(
    eng: dict[str, Any],
    *,
    layers: list[str] | None = None,
    criticidade: str | None = None,
    observed: dict[str, list[dict[str, Any]]] | None = None,
) -> list[SelectedNfr]:
    """Seleciona NFRs proporcionais a camada(s) e criticidade — não o catálogo integral."""
    crit = str(criticidade or eng.get("criticidade") or "medium")
    if crit not in CRITICIDADE_RANK:
        crit = "medium"
    layer_set = set(layers) if layers else set(ALL_LAYERS)
    declared_flags = eng.get("_declared_nfrs") or {}
    observed = observed or {}
    selected: list[SelectedNfr] = []
    for defn in NFR_CATALOG:
        if not _crit_ok(defn.min_criticidade, crit):
            continue
        applicable = [L for L in defn.layers if L in layer_set]
        if not applicable:
            continue
        if not _nfr_enabled(defn, eng):
            continue
        origin = "baseline"
        if declared_flags.get(defn.id):
            origin = "declared"
        ev_hits = observed.get(defn.id) or []
        if ev_hits:
            origin = "observed"
        selected.append(
            SelectedNfr(
                id=defn.id,
                category=defn.category,
                text=_render_text(defn, eng),
                origin=origin,
                layers=applicable,
                evidence=list(ev_hits),
            )
        )
    return selected


def layers_from_repos(repos: list[str] | None) -> list[str]:
    """Infere camadas presentes a partir dos nomes de repositório."""
    from src.planning.layers import infer_layer

    found: list[str] = []
    for repo in repos or []:
        layer = infer_layer(str(repo))
        if layer and layer not in found:
            found.append(layer)
    return found or list(ALL_LAYERS)


def detect_nfr_signals(indice: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    """Varre o índice de código por sinais de NFR → evidências por id."""
    if not indice:
        return {}
    blob_parts: list[str] = []
    pointers: list[dict[str, Any]] = []
    for raw in indice.get("evidencias") or []:
        if not isinstance(raw, dict):
            continue
        text = " ".join(
            str(raw.get(k) or "")
            for k in ("symbol", "file", "route", "snippet", "text")
        )
        blob_parts.append(text)
        pointers.append(raw)
    for key in ("rotas", "simbolos", "arquivos", "status"):
        for item in indice.get(key) or []:
            blob_parts.append(str(item))
    blob = "\n".join(blob_parts)
    found: dict[str, list[dict[str, Any]]] = {}
    for defn in NFR_CATALOG:
        hits: list[dict[str, Any]] = []
        for signal in defn.signals:
            if signal and signal in blob:
                matched = [
                    p
                    for p in pointers
                    if signal
                    in " ".join(str(p.get(k) or "") for k in ("symbol", "file", "route"))
                ]
                hits.append(
                    {
                        "signal": signal,
                        "origin": "observed",
                        "pointers": matched[:3],
                    }
                )
        if hits:
            found[defn.id] = hits
    return found


def nfr_gaps_from_code(
    selected: list[SelectedNfr],
    *,
    indice_applied: bool,
    start: int = 1,
) -> list[dict[str, Any]]:
    """Conflitos/ausências: NFR exigido pelo baseline sem sinal no código → gap."""
    if not indice_applied:
        return []
    gaps: list[dict[str, Any]] = []
    gn = start
    for nfr in selected:
        defn = _CATALOG_BY_ID.get(nfr.id)
        if not defn or not defn.gap_if_missing:
            continue
        if nfr.origin == "observed":
            continue
        # baseline/declared sem evidência → missing_in_code
        gaps.append(
            {
                "id": f"GAP-NFR-{gn:03d}",
                "kind": "missing_in_code",
                "text": (
                    f"{nfr.id} ({nfr.category}) exigido pela engenharia "
                    f"(origem {nfr.origin}) sem evidência no código"
                ),
                "origin": "heuristic",
                "declared": nfr.id,
                "observed": None,
            }
        )
        gn += 1
    return gaps


def selected_nfr_ids(selected: list[SelectedNfr], *, layer: str | None = None) -> list[str]:
    if layer is None:
        return [n.id for n in selected]
    return [n.id for n in selected if layer in n.layers]


def format_selected_nfrs(
    selected: list[SelectedNfr],
    *,
    category: str,
    with_ids: bool = False,
) -> str:
    lines: list[str] = []
    for nfr in selected:
        if nfr.category != category:
            continue
        prefix = f"**{nfr.id}** " if with_ids else ""
        origin_mark = f" _(origem: {nfr.origin})_"
        lines.append(f"- {prefix}{nfr.text}{origin_mark}")
    if not lines:
        return f"- _(nenhum NFR de {category} selecionado para este contexto)_"
    return "\n".join(lines)


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {x}" for x in items) if items else "- (não definido)"


def format_stack(eng: dict[str, Any]) -> str:
    stack = eng.get("stack") or {}
    lines: list[str] = []
    for side in ("bff", "mfe", "api"):
        vals = stack.get(side)
        if isinstance(vals, list) and vals:
            lines.append(f"- **{side.upper()}:** {', '.join(str(v) for v in vals)}")
        elif isinstance(vals, str) and vals:
            lines.append(f"- **{side.upper()}:** {vals}")
    return "\n".join(lines) if lines else "- (definir em inputs/engenharia.yaml)"


def format_padroes(eng: dict[str, Any]) -> str:
    return _bullets([str(p) for p in (eng.get("padroes") or [])])


def format_arquitetura(eng: dict[str, Any]) -> str:
    arch = eng.get("arquitetura") or {}
    lines = []
    if arch.get("fluxo"):
        lines.append(f"- Fluxo: `{arch['fluxo']}`")
    if arch.get("contrato"):
        lines.append(f"- Contrato: `{arch['contrato']}`")
    for k, v in arch.items():
        if k in {"fluxo", "contrato"}:
            continue
        lines.append(f"- {k}: `{v}`")
    return "\n".join(lines) if lines else "- (definir)"


def _selected_or_default(
    eng: dict[str, Any], *, layers: list[str] | None = None
) -> list[SelectedNfr]:
    cached = eng.get("_selected_nfrs")
    if isinstance(cached, list) and cached and all(isinstance(x, SelectedNfr) for x in cached):
        if layers is None:
            return cached
        layer_set = set(layers)
        return [n for n in cached if layer_set & set(n.layers)]
    return select_nfrs(eng, layers=layers)


def format_resiliencia(
    eng: dict[str, Any], *, with_ids: bool = False, layers: list[str] | None = None
) -> str:
    return format_selected_nfrs(
        _selected_or_default(eng, layers=layers), category="resiliencia", with_ids=with_ids
    )


def format_observabilidade(
    eng: dict[str, Any], *, with_ids: bool = False, layers: list[str] | None = None
) -> str:
    return format_selected_nfrs(
        _selected_or_default(eng, layers=layers),
        category="observabilidade",
        with_ids=with_ids,
    )


def format_seguranca(
    eng: dict[str, Any], *, with_ids: bool = False, layers: list[str] | None = None
) -> str:
    return format_selected_nfrs(
        _selected_or_default(eng, layers=layers), category="seguranca", with_ids=with_ids
    )


def _detect_langs(eng: dict[str, Any]) -> list[str]:
    """Línguas presentes no stack (para escolher Javadoc/TSDoc/…)."""
    found: list[str] = []
    stack = eng.get("stack") or {}
    blob = " ".join(
        str(v)
        for vals in stack.values()
        for v in (vals if isinstance(vals, list) else [vals])
    ).lower()
    for lang in _LANG_DOC:
        if lang in blob or (lang == "csharp" and ("c#" in blob or ".net" in blob)):
            if lang not in found:
                found.append(lang)
    return found


def _api_doc_standards(eng: dict[str, Any]) -> list[tuple[str, str]]:
    """[(linguagem, padrão)] a partir do stack + override em documentacao.api_docs."""
    doc = eng.get("documentacao") or {}
    api = doc.get("api_docs") if isinstance(doc.get("api_docs"), dict) else {}
    por_lang = {str(k).lower(): str(v) for k, v in (api.get("por_linguagem") or {}).items()}
    langs = _detect_langs(eng)
    if not langs:
        if por_lang:
            return sorted(por_lang.items())
        return [("java", "javadoc")]
    out: list[tuple[str, str]] = []
    for lang in langs:
        standard = por_lang.get(lang) or _LANG_DOC.get(lang, "api-docs")
        out.append((lang, standard))
    return out


def format_documentacao(
    eng: dict[str, Any], *, with_ids: bool = False, layers: list[str] | None = None
) -> str:
    return format_selected_nfrs(
        _selected_or_default(eng, layers=layers),
        category="documentacao",
        with_ids=with_ids,
    )


def format_nfr_stack_arch(eng: dict[str, Any]) -> str:
    return "\n".join(
        [
            format_stack(eng),
            format_padroes(eng),
            format_arquitetura(eng),
        ]
    )


def rag_snippet(eng: dict[str, Any], *, layers: list[str] | None = None) -> str:
    """Chunk curto p/ consolidated — só NFRs selecionados (não dump do YAML)."""
    selected = select_nfrs(eng, layers=layers)
    ids = ",".join(n.id for n in selected)
    crit = eng.get("criticidade") or "medium"
    r = eng.get("resiliencia") or {}
    return (
        f"eng v{eng.get('version', SCHEMA_VERSION)} criticidade={crit}"
        f" nfrs=[{ids}]"
        f" timeout_ms={r.get('timeout_ms')}"
        f" stack_bff={','.join(str(x) for x in ((eng.get('stack') or {}).get('bff') or []))}"
    )


def slim_engenharia_for_prompt(
    eng: dict[str, Any], *, layers: list[str] | None = None
) -> dict[str, Any]:
    """Recorte para state/economia: IDs selecionados, sem catálogo integral."""
    selected = select_nfrs(eng, layers=layers)
    return {
        "version": eng.get("version", SCHEMA_VERSION),
        "criticidade": eng.get("criticidade") or "medium",
        "stack": eng.get("stack") or {},
        "nfr_ids": [n.id for n in selected],
        "nfrs": [
            {"id": n.id, "origin": n.origin, "category": n.category} for n in selected
        ],
    }
