"""Renderiza OpenAPI 3.0 determinístico a partir do Canonical Spec.

Regra de ouro: nada entra no documento que não esteja no IR. Status, path,
método e campo sem evidência viram marcação `x-unresolved`, nunca um default
silencioso.
"""
from __future__ import annotations

import re
from typing import Any

import yaml

from src.domain.spec import CanonicalSpec, DataSchema, Operation

#: Métodos que podem carregar corpo — GET/DELETE não recebem `requestBody`.
BODY_METHODS = ("POST", "PUT", "PATCH")

UNRESOLVED_NOTE = "não resolvido no Canonical Spec — requer revisão humana"

HEADER = (
    "# Gerado por Prompt-less a partir do Canonical Spec (IR).\n"
    "# Não editar à mão: a fonte de verdade é canonical-spec.yaml.\n"
)

_PATH_PARAM_RE = re.compile(r"\{([^{}/]+)\}")

_ERROR_REF = {"$ref": "#/components/schemas/Error"}


def _base_document(template: str | None) -> dict[str, Any]:
    """Skeleton do projeto como base (mantém `components.schemas.Error`)."""
    if template:
        parsed = yaml.safe_load(template)
        if isinstance(parsed, dict) and parsed.get("openapi"):
            return parsed
    return {
        "openapi": "3.0.3",
        "components": {
            "schemas": {
                "Error": {
                    "type": "object",
                    "required": ["code", "message"],
                    "properties": {
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                    },
                }
            }
        },
    }


def _json_content(schema: dict[str, Any]) -> dict[str, Any]:
    return {"application/json": {"schema": schema}}


def _property_object(field_type: str | None, origin: str) -> dict[str, Any]:
    prop: dict[str, Any] = {} if not field_type else {"type": field_type}
    if not field_type:
        prop["x-unresolved"] = ["type"]
    if origin != "declared":
        prop["x-type-origin"] = origin
    return prop


def _schema_object(schema: DataSchema, *, skip: set[str]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    claims: list[str] = []
    for f in schema.fields:
        if f.name in skip:
            continue
        properties[f.name] = _property_object(f.type, f.origin)
        if f.required:
            required.append(f.name)
        for claim in f.source_claims:
            if claim not in claims:
                claims.append(claim)
    obj: dict[str, Any] = {"type": "object"}
    if required:
        obj["required"] = required
    obj["properties"] = properties
    if schema.origin != "declared":
        obj["x-origin"] = schema.origin
    if claims:
        obj["x-source-claims"] = claims
    return obj


def _register(
    registry: dict[str, dict[str, Any]], name: str, obj: dict[str, Any]
) -> str:
    """Registra o schema evitando colisão silenciosa entre operações."""
    candidate = name
    suffix = 2
    while candidate in registry and registry[candidate] != obj:
        candidate = f"{name}{suffix}"
        suffix += 1
    registry[candidate] = obj
    return candidate


def _path_parameters(op: Operation) -> list[dict[str, Any]]:
    fields = {f.name: f for f in (op.request_schema.fields if op.request_schema else [])}
    params: list[dict[str, Any]] = []
    for name in _PATH_PARAM_RE.findall(op.path or ""):
        param: dict[str, Any] = {"name": name, "in": "path", "required": True}
        field = fields.get(name)
        if field is None:
            param["schema"] = {}
            param["x-unresolved"] = ["schema"]
        else:
            param["schema"] = _property_object(field.type, field.origin)
        params.append(param)
    return params


def _error_responses(spec: CanonicalSpec, op: Operation) -> dict[str, Any]:
    grouped: dict[int, dict[str, Any]] = {}
    for err in spec.errors_of(op):
        entry = grouped.get(int(err.status))
        if entry is None:
            grouped[int(err.status)] = {
                "description": err.trigger,
                "content": _json_content(dict(_ERROR_REF)),
                "x-error-ids": [err.id],
                "x-error-codes": [err.code] if err.code else [],
                "x-source-claims": list(err.source_claims),
            }
            continue
        entry["description"] = f"{entry['description']}; {err.trigger}"
        entry["x-error-ids"].append(err.id)
        if err.code and err.code not in entry["x-error-codes"]:
            entry["x-error-codes"].append(err.code)
        for claim in err.source_claims:
            if claim not in entry["x-source-claims"]:
                entry["x-source-claims"].append(claim)

    responses: dict[str, Any] = {}
    for status in sorted(grouped):
        entry = grouped[status]
        if not entry["x-error-codes"]:
            entry.pop("x-error-codes")
        if not entry["x-source-claims"]:
            entry.pop("x-source-claims")
        responses[str(status)] = entry
    return responses


def _operation_object(
    spec: CanonicalSpec, op: Operation, registry: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    obj: dict[str, Any] = {"operationId": op.name, "x-operation-id": op.id}
    if op.owner:
        obj["x-owner"] = op.owner

    params = _path_parameters(op)
    if params:
        obj["parameters"] = params

    path_params = set(_PATH_PARAM_RE.findall(op.path or ""))
    method = (op.method or "").strip().upper()
    if method in BODY_METHODS and op.request_schema:
        body = _schema_object(op.request_schema, skip=path_params)
        if body["properties"]:
            name = _register(registry, op.request_schema.id, body)
            obj["requestBody"] = {
                "required": bool(body.get("required")),
                "content": _json_content({"$ref": f"#/components/schemas/{name}"}),
            }

    responses: dict[str, Any] = {}
    success = op.resolved_success_status()
    if success is not None:
        entry: dict[str, Any] = {"description": f"Sucesso da operação {op.id}"}
        if op.response_schema:
            body = _schema_object(op.response_schema, skip=set())
            name = _register(registry, op.response_schema.id, body)
            entry["content"] = _json_content({"$ref": f"#/components/schemas/{name}"})
        responses[str(success)] = entry
    responses.update(_error_responses(spec, op))
    if not responses:
        responses["default"] = {
            "description": f"Resposta {UNRESOLVED_NOTE}",
            "x-unresolved": ["success_status"],
        }
    obj["responses"] = responses

    if op.unresolved:
        obj["x-unresolved"] = list(op.unresolved)
    return obj


def build_openapi_document(
    spec: CanonicalSpec, *, template: str | None = None
) -> dict[str, Any]:
    """Documento OpenAPI (dict) derivado exclusivamente do IR."""
    base = _base_document(template)
    registry: dict[str, dict[str, Any]] = {}
    paths: dict[str, Any] = {}
    pendentes: list[dict[str, Any]] = []
    for op in spec.operations:
        if not op.method or not op.path:
            pendentes.append(
                {
                    "id": op.id,
                    "name": op.name,
                    "unresolved": list(op.unresolved),
                    "description": f"Operação {UNRESOLVED_NOTE}",
                }
            )
            continue
        item = paths.setdefault(op.path, {})
        item[op.method.strip().lower()] = _operation_object(spec, op, registry)

    # ordem canônica das chaves — o resto do skeleton é preservado ao final
    doc: dict[str, Any] = {
        "openapi": base.get("openapi") or "3.0.3",
        "info": {
            "title": spec.service_name or spec.service_id,
            "version": spec.version,
            "x-service-id": spec.service_id,
        },
        "paths": paths,
    }
    if pendentes:
        doc["x-unresolved-operations"] = pendentes
    if spec.open_questions:
        doc["x-open-questions"] = [
            {"id": q.id, "text": q.text, "blocking": q.blocking}
            for q in spec.open_questions
        ]

    components = dict(base.get("components") or {})
    schemas = dict(components.get("schemas") or {})
    for name in sorted(registry):
        schemas[name] = registry[name]
    components["schemas"] = schemas
    doc["components"] = components
    for key, value in base.items():
        if key not in doc:
            doc[key] = value
    return doc


def render_openapi(spec: CanonicalSpec, template: str | None = None) -> str:
    """OpenAPI YAML determinístico (mesmo IR ⇒ mesmos bytes)."""
    doc = build_openapi_document(spec, template=template)
    body = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)
    return HEADER + body
