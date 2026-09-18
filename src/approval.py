#!/usr/bin/env python3
"""
Aprovação auditável: pedido, decisão humana e promoção vinculada.

Uso:
  python -m src.approval request-approval --root . --run-id <id>
  python -m src.approval approve --root . --run-id <id> --actor alice --justification "..."
  python -m src.approval approve --root . --run-id <id> --actor alice --justification "..." --reject
  python -m src.approval promote --root . --run-id <id>
  python -m src.approval show --root . --run-id <id>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.runtime.approval import (  # noqa: E402
    ApprovalError,
    approve,
    promote,
    request_approval,
    show_history,
)
from src.runtime.run_context import (  # noqa: E402
    RunContext,
    validate_run_id,
)


def _resolve_run(args: argparse.Namespace) -> tuple[Path, str]:
    if args.run_dir is not None:
        run_dir = Path(args.run_dir)
        run_id = args.run_id or run_dir.name
        return run_dir, validate_run_id(run_id)
    if not args.root or not args.run_id:
        raise ApprovalError("informe --run-dir ou o par --root + --run-id")
    ctx = RunContext.create(
        root=Path(args.root),
        objective="approval",
        run_id=args.run_id,
    )
    return ctx.run_dir, ctx.run_id


def _add_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", type=Path, default=None, help="raiz do pipeline")
    parser.add_argument("--run-id", default=None, help="identificador da run")
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help="atalho: diretório runs/<id> (dispensa --root)",
    )


def _cmd_request(args: argparse.Namespace) -> dict:
    run_dir, run_id = _resolve_run(args)
    return request_approval(
        run_dir,
        run_id=run_id,
        spec_path=args.spec,
        verify_report_path=args.verify_report,
        result_path=args.result,
        actor=args.actor or "",
        justification=args.justification or "",
        origin=args.origin,
    )


def _cmd_approve(args: argparse.Namespace) -> dict:
    run_dir, run_id = _resolve_run(args)
    return approve(
        run_dir,
        run_id=run_id,
        actor=args.actor,
        justification=args.justification,
        origin=args.origin,
        reject=bool(args.reject),
    )


def _cmd_promote(args: argparse.Namespace) -> dict:
    run_dir, run_id = _resolve_run(args)
    return promote(run_dir, run_id=run_id)


def _cmd_show(args: argparse.Namespace) -> dict:
    run_dir, run_id = _resolve_run(args)
    return show_history(run_dir, run_id=run_id)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prompt-less — aprovação auditável (request / approve / promote)"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    req = sub.add_parser("request-approval", help="vincula spec, verify-report e commit")
    _add_run_args(req)
    req.add_argument("--spec", type=Path, default=None, help="canonical-spec.yaml")
    req.add_argument("--verify-report", type=Path, default=None)
    req.add_argument("--result", type=Path, default=None, help="execution.json")
    req.add_argument("--actor", default="")
    req.add_argument("--justification", default="")
    req.add_argument("--origin", default="cli")
    req.set_defaults(func=_cmd_request)

    appr = sub.add_parser("approve", help="aprova ou rejeita o pedido pendente")
    _add_run_args(appr)
    appr.add_argument("--actor", required=True)
    appr.add_argument("--justification", required=True)
    appr.add_argument("--origin", default="cli")
    appr.add_argument(
        "--reject",
        action="store_true",
        help="persiste rejeição (não é só ausência de approve)",
    )
    appr.set_defaults(func=_cmd_approve)

    promo = sub.add_parser(
        "promote",
        help="promove a run se a aprovação vigente ainda estiver vinculada",
    )
    _add_run_args(promo)
    promo.set_defaults(func=_cmd_promote)

    shown = sub.add_parser("show", help="consulta o histórico tamper-evident")
    _add_run_args(shown)
    shown.set_defaults(func=_cmd_show)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
    except ApprovalError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        sys.exit(2)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
