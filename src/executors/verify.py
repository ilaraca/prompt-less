"""Verifica ExecutionResult contra Canonical Spec + policy de camada."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.domain.spec import CanonicalSpec
from src.executors.base import ExecutionResult
from src.executors.policy import check_command_allowed, check_write_allowed, load_profiles


@dataclass
class VerifyIssue:
    code: str
    severity: str
    message: str
    subject_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VerifyResult:
    status: str  # passed | failed | needs_approval
    issues: list[VerifyIssue] = field(default_factory=list)
    coverage: dict[str, list[str]] = field(default_factory=dict)

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "errors": sum(1 for i in self.issues if i.severity == "error"),
            "warnings": sum(1 for i in self.issues if i.severity == "warning"),
            "issues": [i.to_dict() for i in self.issues],
            "coverage": self.coverage,
        }


def verify_execution(
    result: ExecutionResult,
    spec: CanonicalSpec,
    *,
    layer: str | None = None,
    profiles: dict[str, Any] | None = None,
    max_unresolved: int = 0,
) -> VerifyResult:
    issues: list[VerifyIssue] = []
    layer_name = layer or result.layer or _infer_layer(result.repository)
    profiles = profiles or load_profiles()
    profile = profiles.get(layer_name or "") or {}

    # arquivos fora da policy
    for path in result.changed_files:
        if profile and not check_write_allowed(path, profile):
            issues.append(
                VerifyIssue(
                    code="FILE_OUT_OF_SCOPE",
                    severity="error",
                    message=f"Arquivo fora do profile `{layer_name}`: {path}",
                    subject_id=path,
                )
            )

    # comandos negados
    for cmd in result.commands_executed:
        if profile and not check_command_allowed(cmd, profile):
            issues.append(
                VerifyIssue(
                    code="COMMAND_DENIED",
                    severity="error",
                    message=f"Comando negado pela policy: {cmd}",
                    subject_id=cmd,
                )
            )

    # testes
    if not result.tests:
        issues.append(
            VerifyIssue(
                code="NO_TESTS_REPORTED",
                severity="warning",
                message="Executor não reportou testes",
            )
        )
    else:
        failed = [t for t in result.tests if not t.get("passed", True)]
        for t in failed:
            issues.append(
                VerifyIssue(
                    code="TEST_FAILED",
                    severity="error",
                    message=f"Teste falhou: {t.get('name') or t}",
                    subject_id=str(t.get("name") or ""),
                )
            )

    # rastreabilidade RF/AC
    coverage: dict[str, list[str]] = dict(result.requirement_traceability or {})
    for rf in spec.requirements:
        files = coverage.get(rf.id) or []
        if not files:
            issues.append(
                VerifyIssue(
                    code="RF_NOT_MAPPED",
                    severity="error",
                    message=f"RF sem mapeamento de arquivos: {rf.id}",
                    subject_id=rf.id,
                )
            )
    for ac in spec.acceptance_criteria:
        files = coverage.get(ac.id) or []
        if not files:
            issues.append(
                VerifyIssue(
                    code="AC_NOT_MAPPED",
                    severity="warning",
                    message=f"AC sem teste/arquivo mapeado: {ac.id}",
                    subject_id=ac.id,
                )
            )

    if len(result.unresolved_items) > max_unresolved:
        issues.append(
            VerifyIssue(
                code="UNRESOLVED_ITEMS",
                severity="error",
                message=f"Itens não resolvidos: {result.unresolved_items}",
            )
        )

    # aprovação humana pendente
    if result.approved is False:
        issues.append(
            VerifyIssue(
                code="HUMAN_APPROVAL_REQUIRED",
                severity="error",
                message="Execução aguarda aprovação humana",
            )
        )

    if any(i.severity == "error" for i in issues):
        # se só falta aprovação, status needs_approval
        error_codes = {i.code for i in issues if i.severity == "error"}
        if error_codes == {"HUMAN_APPROVAL_REQUIRED"}:
            status = "needs_approval"
        else:
            status = "failed"
    else:
        status = "passed"

    return VerifyResult(status=status, issues=issues, coverage=coverage)


def _infer_layer(repository: str) -> str | None:
    name = repository.lower()
    for layer in ("bff", "mfe", "api", "gtw"):
        if layer in name.split("-") or name.endswith(f"-{layer}"):
            return layer
    return None
