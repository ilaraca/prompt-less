"""Agent Debugger — separa falha do executor, da spec e do harness."""
from __future__ import annotations

from typing import Any

from src.executors.base import ExecutionResult
from src.executors.verify import VerifyResult

_OWNER_TO_ROOT: dict[str, str] = {
    "canonical_spec": "requisito ou IR ambíguo/incompleto",
    "executor": "execução não mapeou RF/AC ou saiu da policy",
    "permission_profiles": "diff ou comando fora do profile da camada",
    "implementation": "teste falhou no repositório",
    "harness_governance": "execução aguarda aprovação humana",
    "harness": "falha sem padrão conhecido — investigar o harness",
    "input_scan": "input não confiável chegou ao pacote LLM",
}


def _as_verify_dict(verify: VerifyResult | dict[str, Any] | None) -> dict[str, Any]:
    if verify is None:
        return {}
    if isinstance(verify, VerifyResult):
        return verify.to_dict()
    return dict(verify)


def _as_execution_dict(execution: ExecutionResult | dict[str, Any] | None) -> dict[str, Any]:
    if execution is None:
        return {}
    if isinstance(execution, ExecutionResult):
        return execution.to_dict()
    return dict(execution)


def _issues_from(verify: dict[str, Any]) -> list[dict[str, Any]]:
    return list(verify.get("issues") or [])


def _symptom(issues: list[dict[str, Any]]) -> str:
    if not issues:
        return "sem issues"
    first = issues[0]
    return str(first.get("message") or first.get("code") or "issue")


def _agent_behavior(execution: dict[str, Any]) -> dict[str, Any]:
    if not execution:
        return {
            "implementation": "pipeline não invocou executor",
            "verification": "não houve ExecutionResult",
            "commands_executed": [],
            "changed_files": [],
        }
    tests = list(execution.get("tests") or [])
    passed = [t for t in tests if t.get("passed", True)]
    failed = [t for t in tests if not t.get("passed", True)]
    files = list(execution.get("changed_files") or [])
    commands = list(execution.get("commands_executed") or [])
    if failed:
        verification = f"executou {len(tests)} teste(s), {len(failed)} falhou"
    elif tests:
        verification = f"executou {len(tests)} teste(s), todos passaram"
    else:
        verification = "não reportou testes"
    if files:
        implementation = f"alterou {len(files)} arquivo(s)"
    else:
        implementation = "não reportou arquivos alterados"
    return {
        "implementation": implementation,
        "verification": verification,
        "tests_reported": len(tests),
        "tests_passed": len(passed),
        "tests_failed": len(failed),
        "commands_executed": commands,
        "changed_files": files,
        "layer": execution.get("layer"),
        "repository": execution.get("repository"),
        "approved": execution.get("approved"),
    }


def _root_cause(
    *,
    patterns: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    blocked_reason: str | None,
    scan: dict[str, Any] | None,
    exception: BaseException | None,
) -> dict[str, Any]:
    if scan and (scan.get("status") == "blocked" or scan.get("blocking_count")):
        findings = list(scan.get("findings") or [])
        blocking = [f for f in findings if f.get("severity") == "error"] or findings
        first = blocking[0] if blocking else {}
        return {
            "summary": first.get("message") or "input scan bloqueou o pacote LLM",
            "hypothesis": "documento ou payload não confiável contém secret, PII ou injection",
            "evidence": [f.get("code") for f in blocking[:8] if f.get("code")],
        }
    if blocked_reason == "input_scan_failed":
        return {
            "summary": "scan de inputs recusou o pacote LLM",
            "hypothesis": "achado fail-closed em secret, PII ou instrução suspeita",
            "evidence": [i.get("code") for i in issues[:8] if i.get("code")],
        }
    if patterns:
        owner = str(patterns[0].get("probable_owner") or "harness")
        return {
            "summary": _OWNER_TO_ROOT.get(owner, patterns[0].get("terminal_cause") or owner),
            "hypothesis": patterns[0].get("recommended_action"),
            "evidence": list(patterns[0].get("matched_codes") or []),
            "pattern_id": patterns[0].get("pattern_id"),
        }
    if exception is not None:
        return {
            "summary": str(exception),
            "hypothesis": type(exception).__name__,
            "evidence": [type(exception).__name__],
        }
    if issues:
        return {
            "summary": _symptom(issues),
            "hypothesis": "sem padrão de falha correspondente",
            "evidence": [i.get("code") for i in issues[:8] if i.get("code")],
        }
    return {
        "summary": None,
        "hypothesis": None,
        "evidence": [],
    }


def build_debugger_report(
    *,
    verify: VerifyResult | dict[str, Any] | None = None,
    execution: ExecutionResult | dict[str, Any] | None = None,
    repair: dict[str, Any] | None = None,
    scan: dict[str, Any] | None = None,
    exception: BaseException | None = None,
    stage: str | None = None,
    run_status: str | None = None,
    blocked_reason: str | None = None,
    validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Monta o relatório com failure / agent_behavior / harness_component / root_cause."""
    from src.learning.failure_patterns import classify_issues, diagnose_verify_report
    verify_d = _as_verify_dict(verify)
    execution_d = _as_execution_dict(execution)
    issues = _issues_from(verify_d)
    if not issues and isinstance(validation, dict):
        issues = list(validation.get("issues") or [])

    if scan and scan.get("status") == "blocked":
        synthetic = {
            "verify": {
                "status": "failed",
                "issues": [
                    {
                        "code": f.get("code") or "INPUT_SCAN",
                        "severity": f.get("severity") or "error",
                        "message": f.get("message"),
                    }
                    for f in (scan.get("findings") or [])
                    if f.get("severity") == "error"
                ],
            }
        }
        diagnosis = diagnose_verify_report(synthetic)
        diagnosis["harness_component"] = {
            "probable_owner": "input_scan",
            "stage": stage or "reason",
        }
        diagnosis["failure"]["terminal_cause"] = "untrusted_input"
    elif issues or verify_d:
        diagnosis = diagnose_verify_report({"verify": verify_d or {"issues": issues}})
        owner = (diagnosis.get("harness_component") or {}).get("probable_owner")
        diagnosis["harness_component"] = {
            "probable_owner": owner or "harness",
            "stage": stage,
        }
    else:
        diagnosis = {
            "status": run_status or "unknown",
            "failure": {"terminal_cause": "none" if not exception else "harness_error", "patterns": []},
            "harness_component": {
                "probable_owner": "harness" if exception else "none",
                "stage": stage,
            },
            "recommended_action": {"primary": None, "playbooks": []},
        }
        if exception is not None:
            diagnosis["failure"]["terminal_cause"] = "harness_error"

    patterns = list((diagnosis.get("failure") or {}).get("patterns") or [])
    if not patterns and issues:
        patterns = classify_issues(issues)
        diagnosis["failure"]["patterns"] = patterns

    terminal = (diagnosis.get("failure") or {}).get("terminal_cause") or "none"
    if blocked_reason == "input_scan_failed":
        terminal = "untrusted_input"
        diagnosis["harness_component"] = {
            "probable_owner": "input_scan",
            "stage": stage or "reason",
        }

    failure = {
        "terminal_cause": terminal,
        "symptom": _symptom(issues) if issues else (str(exception) if exception else None),
        "codes": [str(i.get("code")) for i in issues if i.get("code")],
        "status": verify_d.get("status") or run_status,
        "patterns": patterns,
    }
    if blocked_reason:
        failure["blocked_reason"] = blocked_reason

    recommended = diagnosis.get("recommended_action") or {
        "primary": (patterns[0].get("recommended_action") if patterns else None),
        "playbooks": [p.get("playbook") for p in patterns],
    }

    return {
        "failure": failure,
        "agent_behavior": _agent_behavior(execution_d),
        "harness_component": diagnosis.get("harness_component")
        or {"probable_owner": "harness", "stage": stage},
        "root_cause": _root_cause(
            patterns=patterns,
            issues=issues,
            blocked_reason=blocked_reason,
            scan=scan,
            exception=exception,
        ),
        "recommended_action": recommended,
        "repair_status": (repair or {}).get("status") if repair else None,
    }


def from_verify_result(
    verify: VerifyResult,
    execution: ExecutionResult,
    *,
    repair: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_debugger_report(verify=verify, execution=execution, repair=repair, stage="close_loop")
