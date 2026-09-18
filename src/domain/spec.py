"""Canonical Spec — representação intermediária canônica."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.domain.claim import Claim


@dataclass
class ClaimLink:
    """Vínculo claim → requisito/AC/erro com método e score de matching."""

    claim_id: str
    method: str = "lexical"
    score: float = 1.0
    requires_review: bool = False
    context: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "claim_id": self.claim_id,
            "method": self.method,
            "score": self.score,
            "requires_review": self.requires_review,
        }
        if self.context:
            data["context"] = self.context
        return data


@dataclass
class Requirement:
    id: str
    text: str
    source_claims: list[str] = field(default_factory=list)
    status: str = "draft"
    claim_links: list[ClaimLink] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["claim_links"] = [
            link.to_dict() if isinstance(link, ClaimLink) else link
            for link in self.claim_links
        ]
        return data


@dataclass
class AcceptanceCriterion:
    id: str
    requirement_id: str
    given: str
    when: str
    then: str
    source_claims: list[str] = field(default_factory=list)
    claim_links: list[ClaimLink] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["claim_links"] = [
            link.to_dict() if isinstance(link, ClaimLink) else link
            for link in self.claim_links
        ]
        return data


@dataclass
class ResolvedInt:
    """Valor numérico com origem explícita (não confundir default com fato)."""

    value: int | None
    origin: str = "default"  # default | declared | inferred | observed
    confidence: float = 0.4
    requires_review: bool = True
    source_claims: list[str] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        """Só é resolvido quando há valor e evidência que não exige revisão."""
        return self.value is not None and not self.requires_review

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_raw(cls, raw: Any) -> "ResolvedInt":
        if isinstance(raw, ResolvedInt):
            return raw
        if isinstance(raw, dict):
            return cls(
                value=raw.get("value"),
                origin=str(raw.get("origin") or "default"),
                confidence=float(
                    0.4 if raw.get("confidence") is None else raw["confidence"]
                ),
                requires_review=bool(raw.get("requires_review", True)),
                source_claims=[str(c) for c in (raw.get("source_claims") or [])],
            )
        if raw is None:
            return cls(value=None, origin="default", confidence=0.4, requires_review=True)
        return cls(
            value=int(raw),
            origin="declared",
            confidence=1.0,
            requires_review=False,
        )


@dataclass
class SchemaField:
    """Campo de schema com tipo rastreado — tipo inferido exige revisão."""

    name: str
    type: str | None = None
    required: bool = False
    origin: str = "declared"  # declared | inferred | default
    requires_review: bool = False
    source_claims: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_raw(cls, raw: Any) -> "SchemaField":
        if isinstance(raw, SchemaField):
            return raw
        data = dict(raw or {})
        origin = str(data.get("origin") or "declared")
        return cls(
            name=str(data.get("name") or ""),
            type=data.get("type"),
            required=bool(data.get("required")),
            origin=origin,
            requires_review=bool(data.get("requires_review", origin != "declared")),
            source_claims=[str(c) for c in (data.get("source_claims") or [])],
        )


@dataclass
class DataSchema:
    """Schema de request/response derivado do IR (sem campo fora do IR)."""

    id: str
    fields: list[SchemaField] = field(default_factory=list)
    origin: str = "declared"

    def field_names(self) -> list[str]:
        return [f.name for f in self.fields]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "origin": self.origin,
            "fields": [f.to_dict() for f in self.fields],
        }

    @classmethod
    def from_raw(cls, raw: Any) -> "DataSchema":
        if isinstance(raw, DataSchema):
            return raw
        data = dict(raw or {})
        return cls(
            id=str(data.get("id") or ""),
            fields=[SchemaField.from_raw(f) for f in (data.get("fields") or [])],
            origin=str(data.get("origin") or "declared"),
        )


@dataclass
class Operation:
    id: str
    name: str
    owner: str | None = None
    method: str | None = None
    path: str | None = None
    success_status: ResolvedInt | int | None = None
    error_ids: list[str] = field(default_factory=list)
    request_schema: DataSchema | None = None
    response_schema: DataSchema | None = None
    unresolved: list[str] = field(default_factory=list)

    def resolved_success_status(self) -> int | None:
        """Status de sucesso apenas quando há evidência (nunca default)."""
        status = ResolvedInt.from_raw(self.success_status)
        return status.value if status.resolved else None

    def is_contract(self) -> bool:
        """Publicável: dono, método e path resolvidos — sem dono não vira contrato."""
        if not self.owner or "owner" in (self.unresolved or []):
            return False
        return bool(self.method) and bool(self.path)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        status = self.success_status
        if isinstance(status, ResolvedInt):
            data["success_status"] = status.to_dict()
        elif status is None:
            data["success_status"] = ResolvedInt(
                value=None, origin="default", confidence=0.4, requires_review=True
            ).to_dict()
        else:
            data["success_status"] = ResolvedInt(
                value=int(status),
                origin="declared",
                confidence=1.0,
                requires_review=False,
            ).to_dict()
        data["request_schema"] = (
            self.request_schema.to_dict() if self.request_schema else None
        )
        data["response_schema"] = (
            self.response_schema.to_dict() if self.response_schema else None
        )
        return data

    @classmethod
    def from_raw(cls, raw: Any) -> "Operation":
        if isinstance(raw, Operation):
            return raw
        data = {
            k: v for k, v in dict(raw or {}).items() if k in cls.__dataclass_fields__
        }
        if "success_status" in data:
            data["success_status"] = ResolvedInt.from_raw(data["success_status"])
        for key in ("request_schema", "response_schema"):
            if data.get(key) is not None:
                data[key] = DataSchema.from_raw(data[key])
        return cls(**data)


@dataclass
class SpecError:
    id: str
    trigger: str
    status: int
    code: str | None = None
    source_claims: list[str] = field(default_factory=list)
    claim_links: list[ClaimLink] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["claim_links"] = [
            link.to_dict() if isinstance(link, ClaimLink) else link
            for link in self.claim_links
        ]
        return data


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

    def errors_by_id(self) -> dict[str, SpecError]:
        return {e.id: e for e in self.errors}

    def contract_operations(self) -> list[Operation]:
        """Operações que consumidores derivados (OpenAPI/Mermaid/SDD) podem publicar."""
        return [op for op in self.operations if op.is_contract()]

    def errors_of(self, operation: Operation) -> list[SpecError]:
        """Erros do IR referenciados pela operação, na ordem do IR."""
        wanted = set(operation.error_ids)
        return [e for e in self.errors if e.id in wanted]

    def http_statuses(self) -> set[int]:
        """Único conjunto de status que artefatos derivados podem declarar.

        Só conta sucesso resolvido e erros *ancorados* em operação de contrato —
        erro órfão permanece no IR como unresolved e não autoriza status no artefato.
        """
        statuses: set[int] = set()
        for op in self.contract_operations():
            resolved = op.resolved_success_status()
            if resolved is not None:
                statuses.add(int(resolved))
            for err in self.errors_of(op):
                statuses.add(int(err.status))
        return statuses
