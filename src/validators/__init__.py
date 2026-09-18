"""Validadores do Canonical Spec e dos artefatos derivados dele."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

import yaml

from src.domain.spec import CanonicalSpec

#: Métodos válidos num Path Item Object (OpenAPI 3.0).
OPENAPI_METHODS = (
    "get",
    "put",
    "post",
    "delete",
    "options",
    "head",
    "patch",
    "trace",
)
BODYLESS_METHODS = ("get", "head", "delete")

_STATUS_KEY_RE = re.compile(r"^[1-5](?:\d{2}|XX)$")
_HTTP_IN_TEXT_RE = re.compile(r"\b([1-5]\d{2})\b")
_PATH_IN_TEXT_RE = re.compile(r"(/[^\s,;:()\[\]`'\"]*)")
_PATH_PARAM_RE = re.compile(r"\{([^{}/]+)\}")


@dataclass
class ValidationIssue:
    code: str
    severity: str  # error | warning
    message: str
    subject_id: str | None = None
    source_claims: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationResult:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "blocked" if self.has_errors else "passed",
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "issues": [i.to_dict() for i in self.issues],
        }


def validate_traceability(spec: CanonicalSpec) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    claim_ids = {c.id for c in spec.claims}
    rf_ids = spec.requirement_ids()
    error_ids = {e.id for e in spec.errors}
    op_ids: set[str] = set()

    def _check_source_claims(subject_id: str, sources: list[str]) -> None:
        unknown = set(sources) - claim_ids
        if unknown:
            issues.append(
                ValidationIssue(
                    code="UNKNOWN_SOURCE_CLAIM",
                    severity="error",
                    message=f"{subject_id} referencia claims inexistentes: {sorted(unknown)}",
                    subject_id=subject_id,
                    source_claims=sorted(unknown),
                )
            )

    def _check_claim_sources(claim) -> None:
        origin = claim.origin.value if hasattr(claim.origin, "value") else str(claim.origin)
        if not claim.sources:
            # declared/observed exigem fonte; inferred/default/proposed sem fonte também falham
            issues.append(
                ValidationIssue(
                    code="CLAIM_WITHOUT_SOURCE",
                    severity="error",
                    message=f"Claim {claim.id} não possui SourceRef",
                    subject_id=claim.id,
                )
            )
            return
        for src in claim.sources:
            if not (src.document or "").strip():
                issues.append(
                    ValidationIssue(
                        code="CLAIM_SOURCE_INVALID",
                        severity="error",
                        message=f"Claim {claim.id} possui SourceRef sem document",
                        subject_id=claim.id,
                    )
                )
            if (
                src.start_line is not None
                and src.end_line is not None
                and src.start_line > src.end_line
            ):
                issues.append(
                    ValidationIssue(
                        code="CLAIM_SOURCE_INVALID",
                        severity="error",
                        message=(
                            f"Claim {claim.id} start_line ({src.start_line}) "
                            f"> end_line ({src.end_line})"
                        ),
                        subject_id=claim.id,
                    )
                )
        if origin == "declared" and not claim.sources:
            issues.append(
                ValidationIssue(
                    code="CLAIM_WITHOUT_SOURCE",
                    severity="error",
                    message=f"Claim declared {claim.id} exige SourceRef",
                    subject_id=claim.id,
                )
            )
        if origin == "observed" and not claim.sources:
            issues.append(
                ValidationIssue(
                    code="CLAIM_WITHOUT_SOURCE",
                    severity="error",
                    message=f"Claim observed {claim.id} exige evidência/fonte",
                    subject_id=claim.id,
                )
            )

    for rf in spec.requirements:
        if not rf.source_claims and rf.status != "baseline":
            issues.append(
                ValidationIssue(
                    code="REQUIREMENT_WITHOUT_SOURCE",
                    severity="error",
                    message=f"Requisito {rf.id} sem source_claims",
                    subject_id=rf.id,
                )
            )
        _check_source_claims(rf.id, list(rf.source_claims))

    for ac in spec.acceptance_criteria:
        if ac.requirement_id not in rf_ids:
            issues.append(
                ValidationIssue(
                    code="AC_UNKNOWN_REQUIREMENT",
                    severity="error",
                    message=f"{ac.id} referencia RF inexistente: {ac.requirement_id}",
                    subject_id=ac.id,
                )
            )
        _check_source_claims(ac.id, list(ac.source_claims))

    for err in spec.errors:
        _check_source_claims(err.id, list(err.source_claims))

    for q in spec.open_questions:
        _check_source_claims(q.id, list(q.source_claims))

    for nfr in spec.nfrs:
        _check_source_claims(nfr.id, list(nfr.source_claims))

    for op in spec.operations:
        if op.id in op_ids:
            issues.append(
                ValidationIssue(
                    code="DUPLICATE_ID",
                    severity="error",
                    message=f"ID duplicado: {op.id}",
                    subject_id=op.id,
                )
            )
        op_ids.add(op.id)
        unknown_errs = set(op.error_ids) - error_ids
        if unknown_errs:
            issues.append(
                ValidationIssue(
                    code="UNKNOWN_ERROR_ID",
                    severity="error",
                    message=f"{op.id} referencia errors inexistentes: {sorted(unknown_errs)}",
                    subject_id=op.id,
                )
            )

    # claims: duplicados, confidence, SourceRef obrigatório
    seen_claims: set[str] = set()
    for c in spec.claims:
        if c.id in seen_claims:
            issues.append(
                ValidationIssue(
                    code="DUPLICATE_ID",
                    severity="error",
                    message=f"Claim ID duplicado: {c.id}",
                    subject_id=c.id,
                )
            )
        seen_claims.add(c.id)
        if not (0.0 <= float(c.confidence) <= 1.0):
            issues.append(
                ValidationIssue(
                    code="INVALID_CONFIDENCE",
                    severity="error",
                    message=f"Claim {c.id} confidence fora de [0,1]: {c.confidence}",
                    subject_id=c.id,
                )
            )
        _check_claim_sources(c)

    # NFRs duplicados
    seen_nfr: set[str] = set()
    for nfr in spec.nfrs:
        if nfr.id in seen_nfr:
            issues.append(
                ValidationIssue(
                    code="DUPLICATE_ID",
                    severity="error",
                    message=f"NFR ID duplicado: {nfr.id}",
                    subject_id=nfr.id,
                )
            )
        seen_nfr.add(nfr.id)

    seen: set[str] = set()
    for obj_id in (
        [r.id for r in spec.requirements]
        + [a.id for a in spec.acceptance_criteria]
        + [e.id for e in spec.errors]
    ):
        if obj_id in seen:
            issues.append(
                ValidationIssue(
                    code="DUPLICATE_ID",
                    severity="error",
                    message=f"ID duplicado: {obj_id}",
                    subject_id=obj_id,
                )
            )
        seen.add(obj_id)

    # claims órfãos (existem mas ninguém referencia)
    referenced: set[str] = set()
    for rf in spec.requirements:
        referenced.update(rf.source_claims)
    for ac in spec.acceptance_criteria:
        referenced.update(ac.source_claims)
    for err in spec.errors:
        referenced.update(err.source_claims)
    for q in spec.open_questions:
        referenced.update(q.source_claims)
    for nfr in spec.nfrs:
        referenced.update(nfr.source_claims)
    orphans = claim_ids - referenced
    for oid in sorted(orphans):
        issues.append(
            ValidationIssue(
                code="ORPHAN_CLAIM",
                severity="warning",
                message=f"Claim sem uso: {oid}",
                subject_id=oid,
            )
        )

    return issues


def validate_ambiguity(spec: CanonicalSpec) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for q in spec.open_questions:
        if q.blocking:
            issues.append(
                ValidationIssue(
                    code="AMBIGUOUS_HTTP_STATUS",
                    severity="error",
                    message=q.text,
                    subject_id=q.id,
                    source_claims=list(q.source_claims),
                )
            )
    return issues


def validate_ownership(spec: CanonicalSpec) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if spec.service_id not in {"default", "_unassigned"}:
        repos = []
        for v in (spec.repositories or {}).values():
            repos.extend(v or [])
        if not repos:
            issues.append(
                ValidationIssue(
                    code="SERVICE_WITHOUT_OWNERSHIP",
                    severity="warning",
                    message=f"Serviço {spec.service_id} sem repositórios",
                    subject_id=spec.service_id,
                )
            )
    return issues


def validate_spec(spec: CanonicalSpec) -> ValidationResult:
    issues: list[ValidationIssue] = []
    issues.extend(validate_traceability(spec))
    issues.extend(validate_ambiguity(spec))
    issues.extend(validate_ownership(spec))
    for nfr in spec.nfrs:
        if nfr.status == "baseline":
            issues.append(
                ValidationIssue(
                    code="NFR_FROM_BASELINE",
                    severity="warning",
                    message=f"{nfr.id} veio do baseline de engenharia",
                    subject_id=nfr.id,
                )
            )
    return ValidationResult(issues=issues)


#: Envelope de erro do `templates/openapi.skeleton.yaml` — convenção do projeto,
#: não vem do IR; por isso é o único conjunto de campos fora do Canonical Spec.
ERROR_ENVELOPE_FIELDS = ("code", "message", "details")


def _collect_refs(node: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                refs.append(value)
            else:
                refs.extend(_collect_refs(value))
    elif isinstance(node, list):
        for item in node:
            refs.extend(_collect_refs(item))
    return refs


def _resolve_ref(doc: dict[str, Any], ref: str) -> bool:
    if not ref.startswith("#/"):
        return False
    node: Any = doc
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


def _operations_of(path_item: Any) -> dict[str, Any]:
    if not isinstance(path_item, dict):
        return {}
    return {
        method: obj
        for method, obj in path_item.items()
        if method in OPENAPI_METHODS and isinstance(obj, dict)
    }


def validate_openapi_document(doc: Any) -> ValidationResult:
    """Validação estrutural do OpenAPI gerado (sem dependência externa)."""
    if not isinstance(doc, dict):
        return ValidationResult(
            issues=[
                ValidationIssue(
                    code="OPENAPI_NOT_A_DOCUMENT",
                    severity="error",
                    message="OpenAPI gerado não é um mapeamento YAML",
                )
            ]
        )

    issues: list[ValidationIssue] = []
    if not str(doc.get("openapi") or "").startswith("3."):
        issues.append(
            ValidationIssue(
                code="OPENAPI_INVALID_VERSION",
                severity="error",
                message=f"campo `openapi` inválido: {doc.get('openapi')!r}",
            )
        )

    info = doc.get("info")
    if not isinstance(info, dict) or not str(info.get("title") or "").strip():
        issues.append(
            ValidationIssue(
                code="OPENAPI_MISSING_INFO",
                severity="error",
                message="`info.title` ausente ou vazio",
            )
        )
    if not isinstance(info, dict) or not str(info.get("version") or "").strip():
        issues.append(
            ValidationIssue(
                code="OPENAPI_MISSING_INFO",
                severity="error",
                message="`info.version` ausente ou vazio",
            )
        )

    paths = doc.get("paths")
    if not isinstance(paths, dict):
        issues.append(
            ValidationIssue(
                code="OPENAPI_INVALID_PATHS",
                severity="error",
                message="`paths` ausente ou não é um mapeamento",
            )
        )
        paths = {}
    elif not paths:
        issues.append(
            ValidationIssue(
                code="OPENAPI_WITHOUT_PATHS",
                severity="warning",
                message="nenhum path emitido — operações do IR sem method/path",
            )
        )

    for path, item in paths.items():
        if not str(path).startswith("/"):
            issues.append(
                ValidationIssue(
                    code="OPENAPI_INVALID_PATH",
                    severity="error",
                    message=f"path deve começar com '/': {path!r}",
                    subject_id=str(path),
                )
            )
        operations = _operations_of(item)
        if not operations:
            issues.append(
                ValidationIssue(
                    code="OPENAPI_PATH_WITHOUT_OPERATION",
                    severity="error",
                    message=f"path sem operação HTTP válida: {path}",
                    subject_id=str(path),
                )
            )
        for method, obj in operations.items():
            subject = f"{method.upper()} {path}"
            if not str(obj.get("operationId") or "").strip():
                issues.append(
                    ValidationIssue(
                        code="OPENAPI_MISSING_OPERATION_ID",
                        severity="error",
                        message=f"{subject} sem operationId",
                        subject_id=subject,
                    )
                )
            responses = obj.get("responses")
            if not isinstance(responses, dict) or not responses:
                issues.append(
                    ValidationIssue(
                        code="OPENAPI_EMPTY_RESPONSES",
                        severity="error",
                        message=f"{subject} sem responses",
                        subject_id=subject,
                    )
                )
            else:
                for key in responses:
                    if key == "default" or _STATUS_KEY_RE.match(str(key)):
                        continue
                    issues.append(
                        ValidationIssue(
                            code="OPENAPI_INVALID_STATUS",
                            severity="error",
                            message=f"{subject} declara response inválido: {key!r}",
                            subject_id=subject,
                        )
                    )
            params = [p for p in (obj.get("parameters") or []) if isinstance(p, dict)]
            declared = {
                str(p.get("name")) for p in params if p.get("in") == "path"
            }
            for name in _PATH_PARAM_RE.findall(str(path)):
                if name not in declared:
                    issues.append(
                        ValidationIssue(
                            code="OPENAPI_UNDECLARED_PATH_PARAM",
                            severity="error",
                            message=f"{subject} não declara o parâmetro `{name}`",
                            subject_id=subject,
                        )
                    )
            for p in params:
                if p.get("in") == "path" and not p.get("required"):
                    issues.append(
                        ValidationIssue(
                            code="OPENAPI_PATH_PARAM_NOT_REQUIRED",
                            severity="error",
                            message=(
                                f"{subject} declara `{p.get('name')}` em path "
                                "sem required: true"
                            ),
                            subject_id=subject,
                        )
                    )
            if method in BODYLESS_METHODS and obj.get("requestBody"):
                issues.append(
                    ValidationIssue(
                        code="OPENAPI_BODY_ON_BODYLESS_METHOD",
                        severity="warning",
                        message=f"{subject} declara requestBody num método sem corpo",
                        subject_id=subject,
                    )
                )

    for ref in _collect_refs(doc):
        if not _resolve_ref(doc, ref):
            issues.append(
                ValidationIssue(
                    code="OPENAPI_UNRESOLVED_REF",
                    severity="error",
                    message=f"$ref não resolve no documento: {ref}",
                    subject_id=ref,
                )
            )

    schemas = ((doc.get("components") or {}).get("schemas") or {})
    for name, schema in schemas.items():
        if not isinstance(schema, dict):
            continue
        for prop, definition in (schema.get("properties") or {}).items():
            if isinstance(definition, dict) and not (
                definition.get("type")
                or definition.get("$ref")
                or definition.get("x-unresolved")
            ):
                issues.append(
                    ValidationIssue(
                        code="OPENAPI_PROPERTY_WITHOUT_TYPE",
                        severity="warning",
                        message=f"{name}.{prop} sem type declarado",
                        subject_id=f"{name}.{prop}",
                    )
                )

    return ValidationResult(issues=issues)


def _ir_field_names(spec: CanonicalSpec) -> tuple[set[str], set[str]]:
    todos: set[str] = set(ERROR_ENVELOPE_FIELDS)
    obrigatorios: set[str] = set()
    for op in spec.operations:
        for schema in (op.request_schema, op.response_schema):
            if schema is None:
                continue
            for f in schema.fields:
                todos.add(f.name)
                if f.required:
                    obrigatorios.add(f.name)
    return todos, obrigatorios | {"code", "message"}


def validate_openapi_against_spec(
    spec: CanonicalSpec, doc: Any
) -> ValidationResult:
    """Nenhum status, path, campo ou operação pode existir fora do IR."""
    if not isinstance(doc, dict):
        return ValidationResult(
            issues=[
                ValidationIssue(
                    code="ARTIFACT_NOT_A_DOCUMENT",
                    severity="error",
                    message="OpenAPI gerado não é um mapeamento YAML",
                )
            ]
        )

    issues: list[ValidationIssue] = []
    allowed_statuses = spec.http_statuses()
    ir_paths = {op.path for op in spec.operations if op.path}
    ir_calls = {
        (op.path, (op.method or "").strip().lower())
        for op in spec.operations
        if op.path and op.method
    }
    by_op_id = {op.id: op for op in spec.operations}
    error_ids = {e.id for e in spec.errors}

    for path, item in (doc.get("paths") or {}).items():
        if path not in ir_paths:
            issues.append(
                ValidationIssue(
                    code="ARTIFACT_PATH_NOT_IN_IR",
                    severity="error",
                    message=f"path ausente no Canonical Spec: {path}",
                    subject_id=str(path),
                )
            )
        for method, obj in _operations_of(item).items():
            subject = f"{method.upper()} {path}"
            if (path, method) not in ir_calls:
                issues.append(
                    ValidationIssue(
                        code="ARTIFACT_OPERATION_NOT_IN_IR",
                        severity="error",
                        message=f"operação ausente no Canonical Spec: {subject}",
                        subject_id=subject,
                    )
                )
            ir_op = by_op_id.get(str(obj.get("x-operation-id") or ""))
            for key in (obj.get("responses") or {}):
                if key == "default":
                    continue
                try:
                    status = int(str(key))
                except ValueError:
                    continue
                if status not in allowed_statuses:
                    issues.append(
                        ValidationIssue(
                            code="ARTIFACT_STATUS_NOT_IN_IR",
                            severity="error",
                            message=f"{subject} declara HTTP {status} ausente no IR",
                            subject_id=subject,
                        )
                    )
                if 200 <= status < 300 and (
                    ir_op is None or ir_op.resolved_success_status() != status
                ):
                    issues.append(
                        ValidationIssue(
                            code="ARTIFACT_RESOLVED_WITHOUT_EVIDENCE",
                            severity="error",
                            message=(
                                f"{subject} declara sucesso HTTP {status} sem "
                                "success_status resolvido no IR"
                            ),
                            subject_id=subject,
                        )
                    )
            for response in (obj.get("responses") or {}).values():
                if not isinstance(response, dict):
                    continue
                for err_id in response.get("x-error-ids") or []:
                    if err_id not in error_ids:
                        issues.append(
                            ValidationIssue(
                                code="ARTIFACT_ERROR_NOT_IN_IR",
                                severity="error",
                                message=f"{subject} referencia erro inexistente: {err_id}",
                                subject_id=subject,
                            )
                        )
            if ir_op is not None and ir_op.unresolved and not obj.get("x-unresolved"):
                issues.append(
                    ValidationIssue(
                        code="ARTIFACT_MISSING_UNRESOLVED_MARK",
                        severity="error",
                        message=(
                            f"{subject} omite unresolved do IR: "
                            f"{sorted(ir_op.unresolved)}"
                        ),
                        subject_id=subject,
                    )
                )

    known_fields, required_fields = _ir_field_names(spec)
    schemas = ((doc.get("components") or {}).get("schemas") or {})
    for name, schema in schemas.items():
        if not isinstance(schema, dict):
            continue
        for prop in (schema.get("properties") or {}):
            if prop not in known_fields:
                issues.append(
                    ValidationIssue(
                        code="ARTIFACT_FIELD_NOT_IN_IR",
                        severity="error",
                        message=f"{name}.{prop} não existe no Canonical Spec",
                        subject_id=f"{name}.{prop}",
                    )
                )
        for prop in schema.get("required") or []:
            if prop not in required_fields:
                issues.append(
                    ValidationIssue(
                        code="ARTIFACT_FIELD_NOT_IN_IR",
                        severity="error",
                        message=f"{name}.{prop} exigido sem ser obrigatório no IR",
                        subject_id=f"{name}.{prop}",
                    )
                )

    return ValidationResult(issues=issues)


def validate_mermaid_against_spec(spec: CanonicalSpec, content: str) -> ValidationResult:
    """Sequência não pode citar status ou path ausente no Canonical Spec."""
    issues: list[ValidationIssue] = []
    allowed_statuses = spec.http_statuses()
    ir_paths = {op.path for op in spec.operations if op.path}

    for match in re.finditer(r"(?<![-\w.])([1-5]\d{2})(?![\w.])", content):
        status = int(match.group(1))
        if status not in allowed_statuses:
            issues.append(
                ValidationIssue(
                    code="ARTIFACT_STATUS_NOT_IN_IR",
                    severity="error",
                    message=f"sequência declara HTTP {status} ausente no IR",
                    subject_id=str(status),
                )
            )
    for path in _PATH_IN_TEXT_RE.findall(content):
        if path not in ir_paths:
            issues.append(
                ValidationIssue(
                    code="ARTIFACT_PATH_NOT_IN_IR",
                    severity="error",
                    message=f"sequência declara path ausente no IR: {path}",
                    subject_id=path,
                )
            )
    return ValidationResult(issues=issues)


def validate_derived_artifact(
    tipo: str, content: str, spec: CanonicalSpec
) -> ValidationResult:
    """Gate dos artefatos derivados: estrutura + alinhamento com o IR."""
    if tipo == "openapi":
        try:
            doc = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            return ValidationResult(
                issues=[
                    ValidationIssue(
                        code="OPENAPI_NOT_PARSEABLE",
                        severity="error",
                        message=f"OpenAPI gerado não é YAML válido: {exc}",
                    )
                ]
            )
        return ValidationResult(
            issues=(
                validate_openapi_document(doc).issues
                + validate_openapi_against_spec(spec, doc).issues
            )
        )
    if tipo == "mermaid":
        return validate_mermaid_against_spec(spec, content)
    return ValidationResult()


class PipelineBlocked(Exception):
    """Spec ou artefato derivado inválido — renderização bloqueada."""

    def __init__(
        self,
        validation: ValidationResult,
        spec: CanonicalSpec | None = None,
        *,
        discarded: list[dict[str, Any]] | None = None,
        context: str | None = None,
        reason: str = "spec_validation_failed",
        report_path: str | None = None,
    ):
        self.validation = validation
        self.spec = spec
        self.discarded = list(discarded or [])
        self.context = context
        self.reason = reason
        self.report_path = report_path
        super().__init__(f"pipeline blocked: {len(validation.errors)} errors")
