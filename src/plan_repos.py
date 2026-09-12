#!/usr/bin/env python3
"""
Gera plano multi-repo a partir de mapa-servicos.yaml.

Uso:
  python -m src.plan_repos
  python -m src.plan_repos --service ms-cliente
  python -m src.plan_repos --mapa inputs/mapa-servicos.yaml --out runs/plan/
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.planning import build_plans_from_mapa  # noqa: E402
from src.servicos import load_mapa  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Prompt-less — multi-repo implementation plan")
    p.add_argument("--mapa", type=Path, default=None)
    p.add_argument("--service", action="append", dest="services", default=None)
    p.add_argument("--contract", default="v2")
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()

    mapa = load_mapa(args.mapa)
    if not mapa:
        raise SystemExit("mapa-servicos.yaml não encontrado ou sem serviços")

    result = build_plans_from_mapa(
        mapa,
        service_ids=args.services,
        contract_version=args.contract,
    )
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "implementation_plan.yaml").write_text(
            yaml.safe_dump(result, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        (args.out / "implementation_plan.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
