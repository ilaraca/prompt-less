"""Canonical Spec — representação intermediária canônica."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.domain.claim import Claim


@dataclass
class Requirement:
    id: str
    text: str
    source_claims: list[str] = field(default_factory=list)
    status: str = "draft"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AcceptanceCriterion:
    id: str
    requirement_id: str
    given: str
    when: str
    then: str
    source_claims: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Operation:
    id: str
    name: str
    owner: str | None = None
    method: str | None = None
    path: str | None = None
    success_status: int | None = 200
    error_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SpecError:
    id: str
    trigger: str
    status: int
    code: str | None = None
    source_claims: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OpenQuestion:
    id: str
    text: str
    source_claims: list[str] = field(default_factory=list)
    blocking: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CanonicalSpec:
    version: str
    service_id: str
    repositories: dict[str, list[str]]
    claims: list[Claim]
    requirements: list[Requirement]
    acceptance_criteria: list[AcceptanceCriterion]
    operations: list[Operation]
    errors: list[SpecError]
    nfrs: list[Requirement]
    open_questions: list[OpenQuestion]
    service_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec_version": self.version,
            "service": {
                "id": self.service_id,
                "nome": self.service_name,
                "repositories": self.repositories,
            },
            "claims": [c.to_dict() for c in self.claims],
            "requirements": [r.to_dict() for r in self.requirements],
            "acceptance_criteria": [a.to_dict() for a in self.acceptance_criteria],
            "operations": [o.to_dict() for o in self.operations],
            "errors": [e.to_dict() for e in self.errors],
            "nfrs": [n.to_dict() for n in self.nfrs],
            "open_questions": [q.to_dict() for q in self.open_questions],
        }

    def requirement_ids(self) -> set[str]:
        return {r.id for r in self.requirements}
