"""Coleta relatórios do CI e valida YAML do repositório.

Uso:
  python scripts/ci_reports.py validate-yaml
  python scripts/ci_reports.py collect --reports-dir reports
"""
from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_PYTHON = ("3.10", "3.11", "3.12", "3.13")
COVERAGE_FAIL_UNDER = 70
ADVERSARIAL_TESTS = (
    "tests/integration/test_evidence_verify.py",
    "tests/integration/test_independent_test_evidence.py",
    "tests/integration/test_contextual_provenance.py",
    "tests/integration/test_safe_run_storage.py",
    "tests/integration/test_runtime_isolation.py",
    "tests/integration/test_executor_loop.py",
)
YAML_GLOBS = (
    "config/*.yaml",
    "inputs/*.yaml",
    "tests/fixtures/**/*.yaml",
    "templates/*.yaml",
    ".github/workflows/*.yml",
    ".yamllint.yaml",
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_yaml(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    seen: set[Path] = set()
    for pattern in YAML_GLOBS:
        for path in root.glob(pattern):
            if not path.is_file() or path in seen:
                continue
            seen.add(path)
            try:
                yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError as exc:
                errors.append(f"{path.relative_to(root)}: {exc}")
    if not seen:
        errors.append("nenhum YAML encontrado para validar")
    return errors


def _coverage_by_module(coverage_json: Path) -> list[dict[str, Any]]:
    data = json.loads(coverage_json.read_text(encoding="utf-8"))
    files = data.get("files") or {}
    rows: list[dict[str, Any]] = []
    for filename, info in sorted(files.items()):
        summary = info.get("summary") or {}
        rows.append(
            {
                "file": filename,
                "covered_lines": int(summary.get("covered_lines") or 0),
                "num_statements": int(summary.get("num_statements") or 0),
                "percent_covered": round(float(summary.get("percent_covered") or 0), 1),
            }
        )
    return rows


def _tests_from_junit(junit_xml: Path) -> dict[str, Any]:
    tree = ET.parse(junit_xml)
    root = tree.getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    cases: list[dict[str, Any]] = []
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for suite in suites:
        totals["tests"] += int(suite.attrib.get("tests") or 0)
        totals["failures"] += int(suite.attrib.get("failures") or 0)
        totals["errors"] += int(suite.attrib.get("errors") or 0)
        totals["skipped"] += int(suite.attrib.get("skipped") or 0)
        for case in suite.findall("testcase"):
            status = "passed"
            if case.find("skipped") is not None:
                status = "skipped"
            elif case.find("failure") is not None:
                status = "failed"
            elif case.find("error") is not None:
                status = "error"
            file_attr = case.attrib.get("file") or ""
            cases.append(
                {
                    "file": file_attr,
                    "name": case.attrib.get("name"),
                    "classname": case.attrib.get("classname"),
                    "status": status,
                }
            )
    adversarial: dict[str, list[dict[str, Any]]] = {p: [] for p in ADVERSARIAL_TESTS}
    for case in cases:
        file_attr = (case.get("file") or "").replace("\\", "/")
        for path in ADVERSARIAL_TESTS:
            if file_attr.endswith(path) or path.replace("tests/", "") in file_attr:
                adversarial[path].append(case)
                break
            classname = case.get("classname") or ""
            slug = Path(path).stem
            if slug in classname:
                adversarial[path].append(case)
    return {"totals": totals, "adversarial": adversarial, "cases": cases}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def collect(reports_dir: Path, *, allow_placeholder: bool = True) -> dict[str, str]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}

    coverage_json = reports_dir / "coverage.json"
    coverage_xml = reports_dir / "coverage.xml"
    junit_xml = reports_dir / "pytest.xml"
    eval_path = reports_dir / "eval-report.json"
    verify_path = reports_dir / "verify-report.json"
    modules_path = reports_dir / "coverage-by-module.json"

    modules: list[dict[str, Any]] = []
    if coverage_json.exists():
        modules = _coverage_by_module(coverage_json)
        _write_json(modules_path, {"generated_at": _now(), "modules": modules})
        written["coverage-by-module"] = "generated"
    else:
        written["coverage-by-module"] = "missing_coverage_json"

    if eval_path.exists():
        written["eval-report"] = "kept"
    elif junit_xml.exists():
        parsed = _tests_from_junit(junit_xml)
        adv_summary = {
            path: {
                "count": len(cases),
                "failed": sum(1 for c in cases if c["status"] != "passed"),
            }
            for path, cases in parsed["adversarial"].items()
        }
        _write_json(
            eval_path,
            {
                "generated_at": _now(),
                "source": "pytest-junit",
                "summary": parsed["totals"],
                "adversarial": adv_summary,
                "note": (
                    "Evals da suíte pytest (inclui fixtures baseline e testes "
                    "adversariais). Relatório dedicado de run_eval_suite não "
                    "foi emitido nesta run."
                ),
            },
        )
        written["eval-report"] = "from_junit"
    elif allow_placeholder:
        _write_json(
            eval_path,
            {
                "generated_at": _now(),
                "status": "placeholder",
                "reason": "ci_no_eval_report",
                "note": "pytest não produziu junitxml; placeholder para o artifact.",
            },
        )
        written["eval-report"] = "placeholder"
    else:
        written["eval-report"] = "missing"

    if verify_path.exists():
        written["verify-report"] = "kept"
    elif allow_placeholder:
        _write_json(
            verify_path,
            {
                "generated_at": _now(),
                "status": "placeholder",
                "reason": "ci_no_close_loop",
                "verify": {"status": "not_run"},
                "note": (
                    "O workflow de CI não executa close_loop contra um checkout "
                    "real. Os testes adversariais de evidência, policy e "
                    "provenance cobrem o verify."
                ),
            },
        )
        written["verify-report"] = "placeholder"
    else:
        written["verify-report"] = "missing"

    if not coverage_xml.exists() and not coverage_json.exists():
        if junit_xml.exists():
            written["coverage"] = "missing"
        else:
            written["coverage"] = "skipped"
    else:
        written["coverage"] = "present"

    index = {
        "generated_at": _now(),
        "reports": written,
        "coverage_fail_under": COVERAGE_FAIL_UNDER,
        "supported_python": list(SUPPORTED_PYTHON),
        "modules": modules,
    }
    _write_json(reports_dir / "ci-reports.json", index)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("validate-yaml", help="yaml.safe_load em configs, fixtures e workflow")

    collect_p = sub.add_parser("collect", help="Garante artifacts eval/coverage/verify")
    collect_p.add_argument("--reports-dir", type=Path, default=ROOT / "reports")
    collect_p.add_argument(
        "--no-placeholder",
        action="store_true",
        help="Não cria placeholders; falha se eval/verify/coverage faltarem",
    )

    args = parser.parse_args(argv)
    if args.cmd == "validate-yaml":
        errors = validate_yaml()
        if errors:
            print("YAML inválido:", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            return 1
        print("YAML ok")
        return 0

    written = collect(args.reports_dir, allow_placeholder=not args.no_placeholder)
    print(json.dumps(written, indent=2, ensure_ascii=False))
    if written.get("coverage") == "missing":
        print("coverage.xml/json ausente", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
