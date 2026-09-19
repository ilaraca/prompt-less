#!/usr/bin/env python3
"""
Gera plano multi-repo a partir de mapa-servicos.yaml.

Dependências observadas (código/contratos) prevalecem; camada é fallback revisável.

Uso:
  python -m src.planning.plan_repos
  python -m src.planning.plan_repos --service ms-cliente
  python -m src.planning.plan_repos --mapa inputs/mapa-servicos.yaml --out runs/plan/
  python -m src.planning.plan_repos --workspace ~/dev/repos --index state/repo_index.json
  python -m src.planning.plan_repos --spec runs/x/artifacts/canonical-spec.yaml --reviewed
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.planning import build_plans_from_mapa  # noqa: E402
from src.repos.repo_index import index_workspace, load_index  # noqa: E402
from src.repos.servicos import load_mapa  # noqa: E402


def _load_spec(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise SystemExit(f"spec inválido: {path}")
    sid = (
        ((raw.get("service") or {}).get("id") if isinstance(raw.get("service"), dict) else None)
        or raw.get("service_id")
        or "default"
    )
    return {str(sid): raw}


def main() -> None:
    p = argparse.ArgumentParser(description="Prompt-less — multi-repo implementation plan")
    p.add_argument("--mapa", type=Path, default=None)
    p.add_argument("--service", action="append", dest="services", default=None)
    p.add_argument("--contract", default="v2")
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--workspace", type=Path, default=None, help="pasta com os repositórios a indexar")
    p.add_argument("--index", type=Path, default=None, help="repo_index.json pré-computado")
    p.add_argument("--spec", type=Path, default=None, help="canonical-spec.yaml (contratos)")
    p.add_argument(
        "--reviewed",
        action="store_true",
        help="marca o plano como revisado (gate de ready_for_parallel_execution)",
    )
    args = p.parse_args()

    mapa = load_mapa(args.mapa)
    if not mapa:
        raise SystemExit("mapa-servicos.yaml não encontrado ou sem serviços")

    repo_index = None
    if args.workspace:
        ws = args.workspace.expanduser()
        if not ws.is_dir():
            raise SystemExit(f"workspace inválido: {ws}")
        repo_index = index_workspace(ws, mapa)
    elif args.index:
        repo_index = load_index(args.index)

    specs = _load_spec(args.spec) if args.spec else None

    result = build_plans_from_mapa(
        mapa,
        service_ids=args.services,
        contract_version=args.contract,
        repo_index=repo_index,
        specs=specs,
        reviewed=args.reviewed,
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
