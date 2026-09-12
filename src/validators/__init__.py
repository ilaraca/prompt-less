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
    rf_ids = spec.requirement_ids()
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

    def __init__(self, validation: ValidationResult, spec: CanonicalSpec | None = None):
        self.validation = validation
        self.spec = spec
        super().__init__(f"pipeline blocked: {validation.errors} errors")
