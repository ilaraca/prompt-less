"""Métrica de golden recall sobre claims esperados vs extraídos."""
from __future__ import annotations

from typing import Any


def _norm(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def _claim_matches(expected: dict[str, Any], claim: dict[str, Any]) -> bool:
    want_id = str(expected.get("id") or "").strip()
    if want_id and str(claim.get("id") or "") != want_id:
        return False
    needle = expected.get("text_contains")
    if needle:
        blob = _norm(str(claim.get("text") or ""))
        if _norm(str(needle)) not in blob:
            return False
    if not want_id and not needle:
        return False
    return True


def score_claim_recall(
    expected: list[dict[str, Any]],
    actual: list[dict[str, Any]],
    *,
    min_recall: float = 1.0,
) -> dict[str, Any]:
    """
    Recall = fração dos expected que casam em algum claim extraído.

    Casa por `id` exato e/ou `text_contains` (substring normalizada). Cai se
    o recall ficar abaixo de `min_recall`.
    """
    items = [e for e in expected if isinstance(e, dict)]
    missing: list[dict[str, Any]] = []
    matched = 0
    for item in items:
        hit = next((c for c in actual if isinstance(c, dict) and _claim_matches(item, c)), None)
        if hit is None:
            missing.append(item)
        else:
            matched += 1
    total = len(items)
    recall = 1.0 if total == 0 else round(matched / total, 4)
    return {
        "expected": total,
        "matched": matched,
        "missing": missing,
        "recall": recall,
        "min_recall": float(min_recall),
        "passed": recall + 1e-9 >= float(min_recall),
    }
