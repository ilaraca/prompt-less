"""Golden recall: fixtures com expected claims; o teste falha se o recall cair."""
from __future__ import annotations

from pathlib import Path

import yaml

from src.hardening.recall import score_claim_recall
from src.run import run

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
GOLDEN = FIXTURES / "golden" / "expected_claims.yaml"


def _expected() -> dict:
    return yaml.safe_load(GOLDEN.read_text(encoding="utf-8")) or {}


def test_recall_metric_drops_when_claim_missing():
    expected = [{"id": "CLM-R001", "text_contains": "CPF"}]
    ok = score_claim_recall(
        expected, [{"id": "CLM-R001", "text": "block CPF inválido"}], min_recall=1.0
    )
    assert ok["passed"] and ok["recall"] == 1.0
    bad = score_claim_recall(expected, [{"id": "CLM-X", "text": "outro"}], min_recall=1.0)
    assert bad["passed"] is False
    assert bad["missing"][0]["id"] == "CLM-R001"


def test_golden_claim_recall_does_not_drop(tmp_path: Path):
    spec = _expected()
    min_recall = float(spec.get("min_recall") or 1.0)
    for case_id, items in (spec.get("cases") or {}).items():
        result = run(
            "historia",
            dry_run=True,
            inputs_dir=FIXTURES / case_id,
            output_root=tmp_path / case_id,
            run_id=f"recall-{case_id.replace('_', '-')}",
        )
        claims = list(result.get("claims") or [])
        for ctx in result.get("by_context") or []:
            claims.extend(ctx.get("claims") or [])
        scored = score_claim_recall(list(items), claims, min_recall=min_recall)
        assert scored["passed"], (
            f"recall de {case_id} caiu para {scored['recall']} "
            f"(mínimo {min_recall}); missing={scored['missing']}"
        )
