"""Defaults de engenharia (stack, NFRs, documentação) — baseline mínimo, extensível."""
from __future__ import annotations

from typing import Any


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

DEFAULT_ENGENHARIA: dict[str, Any] = {
    "version": 1,
    "stack": {"bff": ["(definir)"], "mfe": ["(definir)"]},
    "padroes": ["openapi-first"],
    "arquitetura": {"fluxo": "MFE -> BFF -> API Domínio", "contrato": "openapi"},
    "resiliencia": {
        "timeout_ms": 2000,
        "retry": {"max_attempts": 2, "backoff": "exponential"},
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
        }
    },
    "seguranca": {"validar_input": True},
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


def dehydrate_engenharia(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Normaliza engenharia.yaml; preenche baseline se arquivo vazio/ausente."""
    src = {**DEFAULT_ENGENHARIA, **(raw or {})}
    for key in (
        "stack",
        "arquitetura",
        "resiliencia",
        "observabilidade",
        "seguranca",
        "documentacao",
    ):
        base = dict(DEFAULT_ENGENHARIA.get(key) or {})
        override = raw.get(key) if isinstance(raw, dict) else None
        if isinstance(override, dict):
            merged = {**base, **override}
            if key == "resiliencia" and isinstance(override.get("retry"), dict):
                merged["retry"] = {**(base.get("retry") or {}), **override["retry"]}
            if key == "observabilidade" and isinstance(override.get("logs"), dict):
                merged["logs"] = {**(base.get("logs") or {}), **override["logs"]}
            if key == "documentacao":
                for sub in ("readme", "changelog", "api_docs"):
                    if isinstance(override.get(sub), dict):
                        merged[sub] = {**(base.get(sub) or {}), **override[sub]}
                        if sub == "api_docs" and isinstance(
                            override[sub].get("por_linguagem"), dict
                        ):
                            merged[sub]["por_linguagem"] = {
                                **((base.get(sub) or {}).get("por_linguagem") or {}),
                                **override[sub]["por_linguagem"],
                            }
            src[key] = merged
    if raw and isinstance(raw.get("padroes"), list):
        src["padroes"] = raw["padroes"]
    return {
        "version": src.get("version", 1),
        "stack": src.get("stack") or {},
        "padroes": src.get("padroes") or [],
        "arquitetura": src.get("arquitetura") or {},
        "resiliencia": src.get("resiliencia") or {},
        "observabilidade": src.get("observabilidade") or {},
        "seguranca": src.get("seguranca") or {},
        "documentacao": src.get("documentacao") or {},
    }


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


def format_resiliencia(eng: dict[str, Any], *, with_ids: bool = False) -> str:
    r = eng.get("resiliencia") or {}
    retry = r.get("retry") if isinstance(r.get("retry"), dict) else {}
    lines = []
    prefix = "**NFR-R-01** " if with_ids else ""
    if r.get("timeout_ms") is not None:
        lines.append(f"- {prefix}Timeout: `{r['timeout_ms']}ms`".replace("  ", " "))
    if retry:
        p2 = "**NFR-R-02** " if with_ids else ""
        attempts = retry.get("max_attempts", "?")
        backoff = retry.get("backoff", "?")
        lines.append(f"- {p2}Retry: `{attempts}` tentativas, backoff `{backoff}`")
    if not lines:
        lines.append("- (baseline ausente — definir timeout/retry)")
    lines.append("- _(futuro: circuit breaker, idempotência, bulkhead)_")
    return "\n".join(lines)


def format_observabilidade(eng: dict[str, Any], *, with_ids: bool = False) -> str:
    o = eng.get("observabilidade") or {}
    logs = o.get("logs") if isinstance(o.get("logs"), dict) else {}
    lines = []
    p1 = "**NFR-O-01** " if with_ids else ""
    if logs:
        fmt = logs.get("formato", "structured")
        campos = ", ".join(str(c) for c in (logs.get("campos_minimos") or []))
        lines.append(f"- {p1}Logs `{fmt}` com campos: {campos or '(mínimos a definir)'}")
        if logs.get("sem_pii"):
            p2 = "**NFR-O-02** " if with_ids else ""
            lines.append(f"- {p2}Não logar PII / dados sensíveis")
    if not lines:
        lines.append("- (baseline ausente — definir logs estruturados)")
    lines.append("- _(futuro: metrics, tracing, alerting)_")
    return "\n".join(lines)


def format_seguranca(eng: dict[str, Any], *, with_ids: bool = False) -> str:
    s = eng.get("seguranca") or {}
    lines = []
    p1 = "**NFR-S-01** " if with_ids else ""
    if s.get("validar_input"):
        lines.append(f"- {p1}Validar input na borda (BFF/API)")
    if not lines:
        lines.append("- (mínimo: validar input)")
    lines.append("- _(futuro: authn/authz explícitos, secrets, threat model)_")
    return "\n".join(lines)


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
        # sem stack reconhecida: usa o mapa declarado ou javadoc como default
        if por_lang:
            return sorted(por_lang.items())
        return [("java", "javadoc")]
    out: list[tuple[str, str]] = []
    for lang in langs:
        standard = por_lang.get(lang) or _LANG_DOC.get(lang, "api-docs")
        out.append((lang, standard))
    return out


def format_documentacao(eng: dict[str, Any], *, with_ids: bool = False) -> str:
    """DoD de documentação: README estruturado, CHANGELOG, docs de API por linguagem."""
    doc = eng.get("documentacao") or {}
    if not doc:
        return "- (definir `documentacao` em inputs/engenharia.yaml)"

    lines: list[str] = []
    n = 1

    def pid() -> str:
        nonlocal n
        if not with_ids:
            return ""
        label = f"**NFR-D-{n:02d}** "
        n += 1
        return label

    readme = doc.get("readme") if isinstance(doc.get("readme"), dict) else {}
    if readme.get("obrigatorio", True):
        secoes = readme.get("secoes_minimas") or []
        secoes_txt = ", ".join(f"`{s}`" for s in secoes) if secoes else "(a definir)"
        lines.append(
            f"- {pid()}README.md estruturado na raiz do repo, com seções mínimas: {secoes_txt}"
        )

    changelog = doc.get("changelog") if isinstance(doc.get("changelog"), dict) else {}
    if changelog.get("obrigatorio", True):
        path = changelog.get("path") or "CHANGELOG.md"
        fmt = changelog.get("formato") or "keep-a-changelog"
        lines.append(
            f"- {pid()}`{path}` no formato `{fmt}` "
            f"(entrada por release/PR relevante deste fluxo)"
        )

    api = doc.get("api_docs") if isinstance(doc.get("api_docs"), dict) else {}
    if api.get("obrigatorio", True):
        standards = _api_doc_standards(eng)
        detalhe = ", ".join(f"**{lang}** → `{std}`" for lang, std in standards)
        lines.append(
            f"- {pid()}Documentação de API/código pública: {detalhe} "
            f"(tipos/métodos públicos, params, erros)"
        )

    if not lines:
        lines.append("- (baseline de documentação ausente)")
    lines.append("- _(futuro: ADRs, OpenAPI publicado, diagramas gerados)_")
    return "\n".join(lines)


def format_nfr_stack_arch(eng: dict[str, Any]) -> str:
    return "\n".join(
        [
            format_stack(eng),
            format_padroes(eng),
            format_arquitetura(eng),
        ]
    )


def rag_snippet(eng: dict[str, Any]) -> str:
    """Chunk curto p/ consolidated (sem dump do YAML)."""
    r = eng.get("resiliencia") or {}
    retry = r.get("retry") if isinstance(r.get("retry"), dict) else {}
    logs = (eng.get("observabilidade") or {}).get("logs") or {}
    doc = eng.get("documentacao") or {}
    api_std = ",".join(std for _, std in _api_doc_standards(eng)[:3])
    return (
        f"eng stack_bff={','.join(str(x) for x in ((eng.get('stack') or {}).get('bff') or []))}"
        f" resiliencia timeout_ms={r.get('timeout_ms')} retry={retry.get('max_attempts')}"
        f" logs={logs.get('formato')} correlation_id=required"
        f" docs readme={bool((doc.get('readme') or {}).get('obrigatorio', True))}"
        f" changelog={bool((doc.get('changelog') or {}).get('obrigatorio', True))}"
        f" api_docs={api_std or 'javadoc'}"
    )
