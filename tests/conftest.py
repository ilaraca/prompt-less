"""Baseline de avaliações — fixtures isoladas (harness PR1)."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CASES = ("happy_path", "access_denied", "ambiguous_status", "two_services")


@pytest.fixture
def fixture_root() -> Path:
    return FIXTURES


@pytest.fixture
def load_expected():
    def _load(case_id: str) -> dict:
        path = FIXTURES / case_id / "expected.yaml"
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    return _load


@pytest.fixture
def run_case(tmp_path: Path):
    """Executa `run` dry-run com inputs/outputs/state isolados."""
    from src.run import run

    def _run(case_id: str, **kwargs):
        inputs_dir = FIXTURES / case_id
        out = tmp_path / case_id
        out.mkdir(parents=True, exist_ok=True)
        return run(
            kwargs.pop("tipo", "historia"),
            dry_run=True,
            inputs_dir=inputs_dir,
            output_root=out,
            state_path=out / "state" / "workflow.json",
            **kwargs,
        ), out

    return _run
