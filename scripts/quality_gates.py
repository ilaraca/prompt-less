#!/usr/bin/env python3
"""Espelho local dos quality-gates do GitHub Actions.

pytest sozinho **não** é o CI. Cada onda que só rodava pytest voltava a
quebrar no mypy/ruff depois do push. Filha, pai e Actions usam este script.

  PYTHONPATH=. python scripts/quality_gates.py
  PYTHONPATH=. python scripts/quality_gates.py --reports-dir reports

O workflow `.github/workflows/ci.yml` chama o mesmo comando. Um teste
trava essa equivalência — não reintroduzir `mypy src` solto no YAML.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
VENV_BIN = Path(PY).resolve().parent

# Nomes estáveis: o teste de acoplamento CI ↔ local lê esta tupla.
GATE_NAMES = (
    "compile",
    "lint",
    "types",
    "yaml",
    "secrets",
    "audit",
    "tests",
    "smoke",
)


def _tool(binary: str, module: str, args: list[str]) -> list[str]:
    """Prefere o executável do venv (mesmo CLI do Actions); cai no `-m`."""
    candidate = VENV_BIN / binary
    if candidate.exists():
        return [str(candidate), *args]
    return [PY, "-m", module, *args]


def gate_commands(reports_dir: Path) -> list[tuple[str, list[str]]]:
    reports = str(reports_dir)
    return [
        ("compile", [PY, "-m", "compileall", "-q", "src", "tests", "scripts"]),
        ("lint", _tool("ruff", "ruff", ["check", "src", "tests", "scripts"])),
        ("types", _tool("mypy", "mypy", ["src"])),
        (
            "yaml",
            [
                PY,
                "scripts/ci_reports.py",
                "validate-yaml",
            ],
        ),
        (
            "yaml-lint",
            _tool(
                "yamllint",
                "yamllint",
                [
                    "-c",
                    ".yamllint.yaml",
                    "config",
                    "inputs",
                    "templates",
                    ".github",
                    ".yamllint.yaml",
                ],
            ),
        ),
        (
            "secrets",
            _tool(
                "detect-secrets",
                "detect_secrets",
                ["scan", "--baseline", ".secrets.baseline"],
            ),
        ),
        (
            "audit",
            _tool("pip-audit", "pip_audit", ["--strict", "-r", "requirements-dev.lock"]),
        ),
        (
            "tests",
            [
                PY,
                "-m",
                "pytest",
                "-q",
                "--tb=short",
                "--cov=src",
                "--cov-report=term-missing",
                f"--cov-report=xml:{reports}/coverage.xml",
                f"--cov-report=json:{reports}/coverage.json",
                f"--cov-report=html:{reports}/coverage-html",
                "--cov-fail-under=70",
                f"--junitxml={reports}/pytest.xml",
            ],
        ),
        ("smoke", [PY, "-m", "src.plan_repos", "--help"]),
    ]


def run_gates(*, reports_dir: Path, skip_slow: bool = False) -> int:
    reports_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), env["PYTHONPATH"]] if env.get("PYTHONPATH") else [str(ROOT)]
    )
    skip = {"secrets", "audit"} if skip_slow else set()
    for name, argv in gate_commands(reports_dir):
        if name in skip or (name == "yaml-lint" and skip_slow):
            continue
        print(f"::group::{name}", flush=True)
        print("+", " ".join(argv), flush=True)
        proc = subprocess.run(argv, cwd=ROOT, env=env)
        print("::endgroup::", flush=True)
        if proc.returncode != 0:
            print(f"quality_gates FAIL: {name}", file=sys.stderr)
            return proc.returncode
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=ROOT / "reports",
        help="Onde gravar coverage/junit (igual ao artifact do CI)",
    )
    parser.add_argument(
        "--skip-slow",
        action="store_true",
        help="Pula detect-secrets, pip-audit e yamllint. Não use no CI.",
    )
    args = parser.parse_args(argv)
    reports_dir = args.reports_dir
    if not reports_dir.is_absolute():
        reports_dir = ROOT / reports_dir
    return run_gates(reports_dir=reports_dir, skip_slow=args.skip_slow)


if __name__ == "__main__":
    raise SystemExit(main())
