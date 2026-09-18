"""Verifica ExecutionResult contra evidência real (Git + logs), spec e policy."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from src.domain.spec import CanonicalSpec
from src.executors.base import ExecutionResult
from src.executors.evidence import (
    AdapterLog,
    GitInspection,
    build_evidence_hashes,
    canonical_command_set,
    command_argv,
    inspect_commits,
    load_adapter_log,
    policy_paths_for,
    test_evidence_errors,
    trace_in_result_commit,
)
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
    evidence_hashes: dict[str, Any] = field(default_factory=dict)

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
            "evidence_hashes": self.evidence_hashes,
        }


def verify_execution(
    result: ExecutionResult,
    spec: CanonicalSpec,
    *,
    layer: str | None = None,
    profiles: dict[str, Any] | None = None,
    max_unresolved: int = 0,
    tests_required: bool | None = None,
    repo_path: Path | str | None = None,
    adapter_log: Path | str | None = None,
) -> VerifyResult:
    issues: list[VerifyIssue] = []
    layer_name = layer or result.layer or _infer_layer(result.repository)
    profiles = profiles or load_profiles()

    # Fail-closed: camada desconhecida ou profile ausente
    if not layer_name:
        issues.append(
            VerifyIssue(
                code="UNKNOWN_EXECUTION_LAYER",
                severity="error",
                message=f"Não foi possível determinar a camada de {result.repository}",
                subject_id=result.repository,
            )
        )
        return VerifyResult(status="failed", issues=issues)

    if layer_name not in profiles:
        issues.append(
            VerifyIssue(
                code="UNKNOWN_EXECUTION_LAYER",
                severity="error",
                message=f"Profile inexistente para camada `{layer_name}` ({result.repository})",
                subject_id=layer_name,
            )
        )
        return VerifyResult(status="failed", issues=issues)

    profile = profiles[layer_name]
    repo = Path(repo_path) if repo_path else None
    log_path = _resolve_adapter_log_path(result, adapter_log)

    git = _verify_git_evidence(result, repo, profile, issues)
    adapter = _verify_adapter_commands(result, log_path, profile, issues)
    _verify_tests(result, adapter, repo, log_path, tests_required, issues)
    coverage = _verify_traceability(result, spec, git, repo, issues)

    if len(result.unresolved_items) > max_unresolved:
        issues.append(
            VerifyIssue(
                code="UNRESOLVED_ITEMS",
                severity="error",
                message=f"Itens não resolvidos: {result.unresolved_items}",
            )
        )

    if result.approved is False:
        issues.append(
            VerifyIssue(
                code="HUMAN_APPROVAL_REQUIRED",
                severity="error",
                message="Execução aguarda aprovação humana",
            )
        )

    evidence_hashes = build_evidence_hashes(
        git=git, adapter=adapter, tests=list(result.tests or [])
    )

    if any(i.severity == "error" for i in issues):
        error_codes = {i.code for i in issues if i.severity == "error"}
        if error_codes == {"HUMAN_APPROVAL_REQUIRED"}:
            status = "needs_approval"
        else:
            status = "failed"
    else:
        status = "passed"

    return VerifyResult(
        status=status,
        issues=issues,
        coverage=coverage,
        evidence_hashes=evidence_hashes,
    )


def _resolve_adapter_log_path(
    result: ExecutionResult, adapter_log: Path | str | None
) -> Path | None:
    if adapter_log:
        return Path(adapter_log)
    if result.adapter_log:
        return Path(result.adapter_log)
    return None


def _verify_git_evidence(
    result: ExecutionResult,
    repo: Path | None,
    profile: dict[str, Any],
    issues: list[VerifyIssue],
) -> GitInspection | None:
    if not (result.base_commit and str(result.base_commit).strip()):
        issues.append(
            VerifyIssue(
                code="MISSING_BASE_COMMIT",
                severity="error",
                message="base_commit é obrigatório — o payload sem commit não é evidência",
                subject_id=result.repository,
            )
        )
    if not (result.result_commit and str(result.result_commit).strip()):
        issues.append(
            VerifyIssue(
                code="MISSING_RESULT_COMMIT",
                severity="error",
                message="result_commit é obrigatório — o payload sem commit não é evidência",
                subject_id=result.repository,
            )
        )
    if repo is None:
        issues.append(
            VerifyIssue(
                code="MISSING_REPO_EVIDENCE",
                severity="error",
                message="repositório Git ausente — changed_files do payload não é evidência",
                subject_id=result.repository,
            )
        )
        return None
    if not (result.base_commit and result.result_commit):
        return None

    git = inspect_commits(repo, str(result.base_commit), str(result.result_commit))
    for code, message in git.issues:
        issues.append(VerifyIssue(code=code, severity="error", message=message))
    if not git.ok:
        return git

    declared = {p.replace("\\", "/") for p in result.changed_files}
    actual = set(git.changed_files)
    if declared != actual:
        issues.append(
            VerifyIssue(
                code="EVIDENCE_DIVERGENCE",
                severity="error",
                message=(
                    "changed_files do payload diverge do diff Git: "
                    f"declarado={sorted(declared)} evidência={sorted(actual)}"
                ),
            )
        )

    for path in git.changed_files:
        decision = policy_paths_for(repo, git.result_sha or str(result.result_commit), path)
        if decision.escaped:
            issues.append(
                VerifyIssue(
                    code="PATH_ESCAPES_REPO",
                    severity="error",
                    message=f"realpath/symlink de `{path}` escapa do repositório",
                    subject_id=path,
                )
            )
            continue
        if not decision.paths:
            issues.append(
                VerifyIssue(
                    code="FILE_OUT_OF_SCOPE",
                    severity="error",
                    message=f"Arquivo fora do profile (path inválido): {path}",
                    subject_id=path,
                )
            )
            continue
        for candidate in decision.paths:
            if not check_write_allowed(candidate, profile):
                issues.append(
                    VerifyIssue(
                        code="FILE_OUT_OF_SCOPE",
                        severity="error",
                        message=(
                            f"Arquivo fora do profile (diff/realpath): {path}"
                            + (f" → {candidate}" if candidate != path else "")
                        ),
                        subject_id=path,
                    )
                )
                break

    result.changed_files = list(git.changed_files)
    if git.base_sha:
        result.base_commit = git.base_sha
    if git.result_sha:
        result.result_commit = git.result_sha
    return git


def _verify_adapter_commands(
    result: ExecutionResult,
    log_path: Path | None,
    profile: dict[str, Any],
    issues: list[VerifyIssue],
) -> AdapterLog:
    adapter = load_adapter_log(log_path)
    for code, message in adapter.issues:
        issues.append(VerifyIssue(code=code, severity="error", message=message))
    if not adapter.ok:
        return adapter

    declared = canonical_command_set(list(result.commands_executed))
    actual = canonical_command_set(list(adapter.commands))
    if declared != actual:
        issues.append(
            VerifyIssue(
                code="EVIDENCE_DIVERGENCE",
                severity="error",
                message=(
                    "commands_executed do payload diverge do log do adapter: "
                    f"declarado={sorted(declared)} evidência={sorted(actual)}"
                ),
            )
        )

    for cmd in adapter.commands:
        if not check_command_allowed(cmd, profile):
            issues.append(
                VerifyIssue(
                    code="COMMAND_DENIED",
                    severity="error",
                    message=f"Comando negado pela policy: {cmd}",
                    subject_id=str(cmd),
                )
            )

    normalized_cmds: list[str] = []
    for cmd in adapter.commands:
        argv = command_argv(cmd)
        normalized_cmds.append(" ".join(argv) if argv else str(cmd))
    result.commands_executed = normalized_cmds
    return adapter


def _verify_tests(
    result: ExecutionResult,
    adapter: AdapterLog,
    repo: Path | None,
    log_path: Path | None,
    tests_required: bool | None,
    issues: list[VerifyIssue],
) -> None:
    code_change = _is_code_change(result.changed_files)
    require_tests = tests_required if tests_required is not None else code_change
    if not result.tests:
        issues.append(
            VerifyIssue(
                code="NO_TESTS_REPORTED",
                severity="error" if require_tests else "warning",
                message="Executor não reportou testes",
            )
        )
        return

    roots: list[Path] = []
    if repo is not None:
        roots.append(Path(repo).resolve())
    if log_path is not None:
        roots.append(Path(log_path).resolve().parent)
    if not roots:
        roots.append(Path(".").resolve())

    for test in result.tests:
        if not isinstance(test, dict):
            issues.append(
                VerifyIssue(
                    code="TEST_NOT_EVIDENCED",
                    severity="error",
                    message=f"Teste não estruturado: {test}",
                    subject_id=str(test),
                )
            )
            continue
        name = str(test.get("name") or test)
        for code, message in test_evidence_errors(
            test, adapter=adapter, artifact_roots=roots
        ):
            issues.append(
                VerifyIssue(
                    code=code,
                    severity="error",
                    message=message,
                    subject_id=name,
                )
            )
        if any(
            i.code == "TEST_NOT_EVIDENCED" and i.subject_id == name for i in issues
        ):
            continue
        if not test.get("passed", True):
            issues.append(
                VerifyIssue(
                    code="TEST_FAILED",
                    severity="error",
                    message=f"Teste falhou: {name}",
                    subject_id=name,
                )
            )


def _verify_traceability(
    result: ExecutionResult,
    spec: CanonicalSpec,
    git: GitInspection | None,
    repo: Path | None,
    issues: list[VerifyIssue],
) -> dict[str, list[str]]:
    coverage: dict[str, list[str]] = dict(result.requirement_traceability or {})
    commit = (git.result_sha if git else None) or result.result_commit
    can_check_tree = bool(repo and git and git.ok and commit)

    def _check_locs(subject_id: str, locators: list[Any], *, required: bool) -> None:
        if not locators:
            issues.append(
                VerifyIssue(
                    code="RF_NOT_MAPPED" if required else "AC_NOT_MAPPED",
                    severity="error" if required else "warning",
                    message=(
                        f"RF sem mapeamento de arquivos: {subject_id}"
                        if required
                        else f"AC sem teste/arquivo mapeado: {subject_id}"
                    ),
                    subject_id=subject_id,
                )
            )
            return
        if not can_check_tree:
            return
        assert repo is not None and commit is not None
        for loc in locators:
            ok, reason = trace_in_result_commit(repo, commit, loc)
            if not ok:
                issues.append(
                    VerifyIssue(
                        code="TRACE_NOT_IN_RESULT_COMMIT",
                        severity="error",
                        message=reason or f"rastreio inválido em {subject_id}",
                        subject_id=subject_id,
                    )
                )

    for rf in spec.requirements:
        _check_locs(rf.id, coverage.get(rf.id) or [], required=True)
    for ac in spec.acceptance_criteria:
        _check_locs(ac.id, coverage.get(ac.id) or [], required=False)
    return coverage


def _is_code_change(changed_files: list[str]) -> bool:
    """True se há alteração além de documentação pura."""
    if not changed_files:
        return False
    doc_suffixes = (".md", ".txt", ".rst", ".adoc")
    doc_prefixes = ("docs/", "README", "CHANGELOG", "LICENSE")
    for path in changed_files:
        norm = path.replace("\\", "/")
        if any(norm.startswith(p) or norm.upper().startswith(p.upper()) for p in doc_prefixes):
            continue
        if norm.lower().endswith(doc_suffixes):
            continue
        return True
    return False


def _infer_layer(repository: str) -> str | None:
    name = repository.lower()
    for layer in ("bff", "mfe", "api", "gtw"):
        if layer in name.split("-") or name.endswith(f"-{layer}"):
            return layer
    return None
