"""Validadores do Canonical Spec."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.domain.spec import CanonicalSpec


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
    nfr_ids = {n.id for n in spec.nfrs}
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

    # claims duplicados
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

    # silencia unused var warning conceptually
    _ = nfr_ids
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


class PipelineBlocked(Exception):
    """Spec inválido — renderização bloqueada."""

    def __init__(
        self,
        validation: ValidationResult,
        spec: CanonicalSpec | None = None,
        *,
        discarded: list[dict[str, Any]] | None = None,
        context: str | None = None,
    ):
        self.validation = validation
        self.spec = spec
        self.discarded = list(discarded or [])
        self.context = context
        super().__init__(f"pipeline blocked: {len(validation.errors)} errors")
