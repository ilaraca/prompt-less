#!/usr/bin/env python3
"""
Aplica propostas aceitas em config versionada com snapshot e rollback.

Uso:
  python -m src.apply --root . --proposal-json /tmp/prop.json
  python -m src.apply --root . --proposal-json /tmp/props.json --cases happy_path
  python -m src.apply --root . --proposal-json /tmp/medium.json \\
      --run-dir runs/RUN --run-id RUN
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.learning.apply_rollback import (  # noqa: E402
    ApplyGateError,
    apply_proposals_with_rollback,
)


def _load_proposals(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return list(raw)
    if isinstance(raw, dict) and "proposals" in raw:
        return list(raw["proposals"] or [])
    if isinstance(raw, dict):
        return [raw]
    raise ApplyGateError("proposal-json deve ser objeto, lista ou {proposals: [...]}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Prompt-less — apply de propostas em config com rollback"
    )
    p.add_argument("--root", type=Path, default=ROOT, help="raiz do pipeline")
    p.add_argument(
        "--proposal-json",
        type=Path,
        required=True,
        help="JSON com proposta(s) contendo change.key/value e risk",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="diretório de evals (default: state/knowledge/evals/apply)",
    )
    p.add_argument(
        "--cases",
        default="",
        help="casos de eval separados por vírgula (default: suíte completa)",
    )
    p.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help="runs/<id> com aprovação (obrigatório se risk medium+)",
    )
    p.add_argument(
        "--run-id",
        default=None,
        help="run_id para assert_promotable (obrigatório se risk medium+)",
    )
    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        proposals = _load_proposals(args.proposal_json)
        cases = tuple(c.strip() for c in str(args.cases).split(",") if c.strip()) or None
        result = apply_proposals_with_rollback(
            proposals,
            root=args.root,
            eval_root=args.out,
            cases=cases,
            run_dir=args.run_dir,
            run_id=args.run_id,
        )
    except ApplyGateError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        sys.exit(2)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") == "rejected":
        sys.exit(1)


if __name__ == "__main__":
    main()
