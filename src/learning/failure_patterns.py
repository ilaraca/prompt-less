"""Classificação de falhas em padrões conhecidos."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATTERNS = ROOT / "config" / "failure-patterns.yaml"


def load_patterns(path: Path | None = None) -> list[dict[str, Any]]:
    data = yaml.safe_load((path or DEFAULT_PATTERNS).read_text(encoding="utf-8")) or {}
    return list(data.get("patterns") or [])


def classify_issues(
    issues: list[dict[str, Any]],
    *,
    patterns: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    patterns = patterns or load_patterns()
    codes = {str(i.get("code") or "") for i in issues}
    matched: list[dict[str, Any]] = []
    for pat in patterns:
        pat_codes = set(pat.get("codes") or [])
        if not pat_codes:
            continue
        hit = codes & pat_codes
        if hit:
            matched.append(
                {
                    "pattern_id": pat["id"],
                    "matched_codes": sorted(hit),
                    "terminal_cause": pat.get("terminal_cause"),
                    "probable_owner": pat.get("probable_owner"),
                    "recommended_action": pat.get("recommended_action"),
                    "playbook": pat.get("playbook"),
                }
            )
    if not matched and issues:
        unknown = next((p for p in patterns if p.get("id") == "FP-UNKNOWN"), None)
        if unknown:
            matched.append(
                {
                    "pattern_id": unknown["id"],
                    "matched_codes": sorted(codes),
                    "terminal_cause": unknown.get("terminal_cause"),
                    "probable_owner": unknown.get("probable_owner"),
                    "recommended_action": unknown.get("recommended_action"),
                    "playbook": unknown.get("playbook"),
                }
            )
    return matched


def diagnose_verify_report(report: dict[str, Any]) -> dict[str, Any]:
    verify = report.get("verify") or report
    issues = list(verify.get("issues") or [])
    patterns = classify_issues(issues)
    return {
        "status": verify.get("status"),
        "failure": {
            "terminal_cause": patterns[0]["terminal_cause"] if patterns else "none",
            "patterns": patterns,
        },
        "harness_component": {
            "probable_owner": patterns[0]["probable_owner"] if patterns else "harness",
        },
        "recommended_action": {
            "primary": patterns[0]["recommended_action"] if patterns else None,
            "playbooks": [p["playbook"] for p in patterns],
        },
    }
