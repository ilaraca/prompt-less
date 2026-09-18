"""Consumidor SDD — pacote de arquitetura, contratos e tasks a partir do IR.

Fonte primária: Canonical Spec (`contract_operations()`). O renderer não fatia
operations (isso é o 29) e não inventa decisão crítica (método/path/status/dono).
Dependências reutilizam `build_implementation_plan` (grafo multi-repo).
Nenhuma task sai com despacho a executor.
"""
from __future__ import annotations

import re
from typing import Any

import yaml

from src.domain.spec import CanonicalSpec, OpenQuestion, Operation, ResolvedInt
from src.planning.plan import build_implementation_plan

HEADER = (
    "# Pacote SDD gerado por Prompt-less a partir do Canonical Spec (IR).\n"
    "# Não editar à mão: a fonte de verdade é canonical-spec.yaml.\n"
    "# Revisão humana obrigatória — executor_dispatch permanece false.\n"
)

GRAPH_SOURCE = "src.planning.plan.build_implementation_plan"
PACKAGE_VERSION = "1.0"

_OP_RE = re.compile(r"\b(OP-\d{3})\b")
_ERR_RE = re.compile(r"\b(ERR-\d{3})\b")

ALLOWED_DECISION_ORIGINS = {
    "declared",
    "observed",
    "heuristic",
    "inferred",
    "default",
    "canonical-spec",
    "multi-repo-graph",
}


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _repos(spec: CanonicalSpec) -> list[str]:
    seen: list[str] = []
    for group in (spec.repositories or {}).values():
        for repo in group or []:
            name = str(repo)
            if name and name not in seen:
                seen.append(name)
    return seen


def _plan_for_spec(spec: CanonicalSpec) -> dict[str, Any]:
    repos = _repos(spec)
    if not repos:
        return {
            "service_id": spec.service_id,
            "service_name": spec.service_name or spec.service_id,
            "origin": "canonical-spec",
            "requires_review": True,
            "tasks": [],
            "waves": [],
            "note": "Sem repositórios no IR — task única do serviço, sem grafo de camadas.",
        }
    return build_implementation_plan(
        service_id=spec.service_id,
        repos=repos,
        service_name=spec.service_name,
    )


def _trace_for_operation(spec: CanonicalSpec, op: Operation) -> tuple[list[str], list[str]]:
    """RF/AC ligados à operação; fallback = recorte já fatiado do spec (29)."""
    rf_ids: list[str] = []
    ac_ids: list[str] = []
    triggers = {
        (err.trigger or "").strip().lower()
        for err in spec.errors_of(op)
        if err.trigger
    }
    path = (op.path or "").lower()
    name = (op.name or "").lower()

    for ac in spec.acceptance_criteria:
        when = (ac.when or "").lower()
        then = (ac.then or "").lower()
        blob = f"{when} {then} {ac.given or ''}".lower()
        hit = any(t and t in blob for t in triggers)
        if path and path in blob:
            hit = True
        if name and name in blob:
            hit = True
        if hit:
            ac_ids.append(ac.id)
            if ac.requirement_id:
                rf_ids.append(ac.requirement_id)

    for rf in spec.requirements:
        text = (rf.text or "").lower()
        if text.startswith("decisão:") or text.startswith("permitir submissão"):
            rf_ids.append(rf.id)
            for ac in spec.acceptance_criteria:
                if ac.requirement_id == rf.id:
                    ac_ids.append(ac.id)

    rf_ids = _unique(rf_ids)
    ac_ids = _unique(ac_ids)
    if rf_ids and ac_ids:
        return rf_ids, ac_ids
    return (
        [r.id for r in spec.requirements],
        [a.id for a in spec.acceptance_criteria],
    )


def _service_trace(spec: CanonicalSpec) -> tuple[list[str], list[str]]:
    return (
        [r.id for r in spec.requirements],
        [a.id for a in spec.acceptance_criteria],
    )


def _nfr_ids(spec: CanonicalSpec, *, layer: str | None = None) -> list[str]:
    """IDs de NFR do IR; com `layer`, só os aplicáveis à camada da task."""
    ids: list[str] = []
    for n in spec.nfrs:
        n_layers = getattr(n, "layers", None) or []
        if layer and n_layers and layer not in n_layers:
            continue
        ids.append(n.id)
    return ids


def _evidence_for(spec: CanonicalSpec, *, repo: str | None, op: Operation | None) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    applied = bool(spec.current_state and spec.current_state.applied)

    def _keep(ev) -> bool:
        if repo and ev.repo and ev.repo != repo:
            return False
        if op and ev.route and op.path:
            return op.path in str(ev.route)
        if op and ev.route and op.method:
            return str(op.method).upper() in str(ev.route).upper()
        return True

    for ev in spec.code_evidence:
        if _keep(ev):
            items.append(ev.to_dict())
    if applied:
        for ev in list(spec.current_state.routes) + list(spec.current_state.statuses):
            payload = ev.to_dict()
            if payload in items:
                continue
            if _keep(ev):
                items.append(payload)

    for gap in spec.gaps:
        related = gap.related_operation
        if op and related and related not in {op.id, op.name, op.path}:
            continue
        items.append(
            {
                "kind": "gap",
                "id": gap.id,
                "text": gap.text,
                "origin": gap.origin,
                "related_operation": related,
            }
        )

    if not applied:
        status = "index_not_applied"
    elif items:
        status = "observed"
    else:
        status = "none_observed"
    return {"status": status, "items": items}


def _ops_affected_by_question(
    question: OpenQuestion, spec: CanonicalSpec
) -> set[str] | None:
    """IDs de operação afetados, ou None se a pergunta não tem escopo atribuível."""
    found: set[str] = set()
    text = question.text or ""
    found.update(_OP_RE.findall(text))
    err_ids = set(_ERR_RE.findall(text))
    for op in spec.operations:
        if err_ids & set(op.error_ids or []):
            found.add(op.id)

    blob = text.lower()
    for err in spec.errors:
        trigger = (err.trigger or "").strip().lower()
        if trigger and trigger in blob:
            for op in spec.operations:
                if err.id in (op.error_ids or []):
                    found.add(op.id)

    q_claims = set(question.source_claims or [])
    if q_claims:
        for err in spec.errors:
            if q_claims & set(err.source_claims or []):
                for op in spec.operations:
                    if err.id in (op.error_ids or []):
                        found.add(op.id)
        for ac in spec.acceptance_criteria:
            if not (q_claims & set(ac.source_claims or [])):
                continue
            when = (ac.when or "").lower()
            for op in spec.operations:
                triggers = {
                    (e.trigger or "").lower() for e in spec.errors_of(op) if e.trigger
                }
                if any(t and t in when for t in triggers):
                    found.add(op.id)
                if op.path and op.path.lower() in when:
                    found.add(op.id)

    return found or None


def operations_affected_by_question(
    question: OpenQuestion, spec: CanonicalSpec
) -> set[str] | None:
    """Operações no escopo da pergunta, ou None se o recorte não for atribuível."""
    return _ops_affected_by_question(question, spec)


def question_affects_operation(
    question: OpenQuestion, spec: CanonicalSpec, operation_id: str | None
) -> bool:
    """True se a pergunta tem escopo e atinge a operação da task."""
    if not operation_id:
        return False
    affected = operations_affected_by_question(question, spec)
    return bool(affected is not None and operation_id in affected)


def _questions_for_task(
    spec: CanonicalSpec,
    *,
    operation_id: str | None,
    rf_ids: list[str],
    ac_ids: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(blocked_by, review_notes). Pergunta sem escopo não entra em blocked_by."""
    blocked: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []
    rf_set, ac_set = set(rf_ids), set(ac_ids)
    for question in spec.open_questions:
        affected = _ops_affected_by_question(question, spec)
        in_scope = False
        if affected is not None:
            in_scope = bool(operation_id and operation_id in affected)
        else:
            q_claims = set(question.source_claims or [])
            if q_claims:
                for rf in spec.requirements:
                    if rf.id in rf_set and q_claims & set(rf.source_claims or []):
                        in_scope = True
                for ac in spec.acceptance_criteria:
                    if ac.id in ac_set and q_claims & set(ac.source_claims or []):
                        in_scope = True
        if not in_scope:
            continue
        payload = {
            "id": question.id,
            "text": question.text,
            "blocking": bool(question.blocking),
        }
        if question.blocking:
            blocked.append(payload)
        else:
            notes.append(payload)
    return blocked, notes


def _api_decision(spec: CanonicalSpec, op: Operation) -> dict[str, Any]:
    status = ResolvedInt.from_raw(op.success_status)
    origin = op.method_origin or op.path_origin or "declared"
    if origin not in ALLOWED_DECISION_ORIGINS:
        origin = "declared"
    return {
        "operation_id": op.id,
        "name": op.name,
        "owner": op.owner,
        "method": op.method,
        "path": op.path,
        "method_origin": op.method_origin,
        "path_origin": op.path_origin,
        "success_status": status.to_dict(),
        "errors": [e.to_dict() for e in spec.errors_of(op)],
        "request_schema": op.request_schema.to_dict() if op.request_schema else None,
        "response_schema": op.response_schema.to_dict() if op.response_schema else None,
        "unresolved": list(op.unresolved or []),
        "origin": origin,
        "requires_review": bool(op.unresolved) or status.requires_review,
    }


def _architecture(spec: CanonicalSpec, plan: dict[str, Any], ops: list[Operation]) -> dict[str, Any]:
    decisions: list[dict[str, Any]] = []
    for op in ops:
        origin = op.method_origin or op.path_origin or "declared"
        decisions.append(
            {
                "id": f"DEC-{op.id}",
                "kind": "contract",
                "text": f"{op.method} {op.path} — owner `{op.owner}`",
                "origin": origin,
                "source_ids": [op.id],
                "requires_review": bool(op.unresolved),
            }
        )
    return {
        "origin": "canonical-spec",
        "requires_review": True,
        "service_id": spec.service_id,
        "service_name": spec.service_name,
        "repositories": _repos(spec),
        "contract_operations": [op.id for op in ops],
        "current_state": spec.current_state.to_dict(),
        "gaps": [g.to_dict() for g in spec.gaps],
        "unresolved_operations": [
            {
                "id": op.id,
                "name": op.name,
                "unresolved": list(op.unresolved or []),
            }
            for op in spec.operations
            if not op.is_contract()
        ],
        "topology": {
            "source": GRAPH_SOURCE,
            "origin": plan.get("origin") or "heuristic",
            "requires_review": bool(plan.get("requires_review", True)),
            "note": plan.get("note"),
        },
        "decisions": decisions,
    }


def _plan_tasks(plan: dict[str, Any], spec: CanonicalSpec) -> list[dict[str, Any]]:
    tasks = list(plan.get("tasks") or [])
    if tasks:
        return tasks
    return [
        {
            "id": "TASK-APP-01",
            "repo": spec.service_id,
            "layer": None,
            "service_id": spec.service_id,
            "changes": ["Implementar requisitos do Canonical Spec"],
            "depends_on": [],
            "produces": [],
            "consumes": [],
        }
    ]


def _sdd_task(
    *,
    task_id: str,
    plan_task: dict[str, Any],
    spec: CanonicalSpec,
    op: Operation | None,
    depends_on: list[str],
    rf_ids: list[str],
    ac_ids: list[str],
) -> dict[str, Any]:
    blocked_by, notes = _questions_for_task(
        spec, operation_id=op.id if op else None, rf_ids=rf_ids, ac_ids=ac_ids
    )
    status = "blocked" if blocked_by else "pending_review"
    evidence = _evidence_for(spec, repo=plan_task.get("repo"), op=op)
    payload: dict[str, Any] = {
        "id": task_id,
        "plan_task_id": plan_task.get("id"),
        "repo": plan_task.get("repo"),
        "layer": plan_task.get("layer"),
        "service_id": spec.service_id,
        "operation_id": op.id if op else None,
        "rf_ids": list(rf_ids),
        "ac_ids": list(ac_ids),
        "nfr_ids": _nfr_ids(spec, layer=plan_task.get("layer")),
        "evidence": evidence["items"],
        "evidence_status": evidence["status"],
        "depends_on": list(depends_on),
        "produces": list(plan_task.get("produces") or []),
        "consumes": list(plan_task.get("consumes") or []),
        "changes": list(plan_task.get("changes") or []),
        "blocked_by": blocked_by,
        "review_notes": notes,
        "status": status,
        "executor_dispatch": False,
    }
    if op is not None:
        payload["changes"] = [
            f"Aplicar {op.method} {op.path} ({op.id}) em `{plan_task.get('repo')}`"
        ] + list(payload["changes"])
    return payload


def build_sdd_package(spec: CanonicalSpec) -> dict[str, Any]:
    """Pacote SDD derivado só do Canonical Spec + grafo multi-repo existente."""
    ops = spec.contract_operations()
    plan = _plan_for_spec(spec)
    plan_tasks = _plan_tasks(plan, spec)
    plan_ids = {t["id"] for t in plan_tasks}

    tasks: list[dict[str, Any]] = []
    if ops:
        for plan_task in plan_tasks:
            for op in ops:
                rf_ids, ac_ids = _trace_for_operation(spec, op)
                depends = [
                    f"{dep}::{op.id}"
                    for dep in (plan_task.get("depends_on") or [])
                    if dep in plan_ids
                ]
                tasks.append(
                    _sdd_task(
                        task_id=f"{plan_task['id']}::{op.id}",
                        plan_task=plan_task,
                        spec=spec,
                        op=op,
                        depends_on=depends,
                        rf_ids=rf_ids,
                        ac_ids=ac_ids,
                    )
                )
        waves = [
            [f"{tid}::{op.id}" for tid in wave for op in ops]
            for wave in (plan.get("waves") or [])
        ]
        if not waves:
            waves = [[t["id"] for t in tasks]]
    else:
        rf_ids, ac_ids = _service_trace(spec)
        for plan_task in plan_tasks:
            depends = [
                dep for dep in (plan_task.get("depends_on") or []) if dep in plan_ids
            ]
            tasks.append(
                _sdd_task(
                    task_id=str(plan_task["id"]),
                    plan_task=plan_task,
                    spec=spec,
                    op=None,
                    depends_on=depends,
                    rf_ids=rf_ids,
                    ac_ids=ac_ids,
                )
            )
        waves = list(plan.get("waves") or [])
        if not waves:
            waves = [[t["id"] for t in tasks]]

    any_blocked = any(t["status"] == "blocked" for t in tasks)
    unscoped = []
    for question in spec.open_questions:
        if _ops_affected_by_question(question, spec) is not None:
            continue
        unscoped.append(
            {
                "id": question.id,
                "text": question.text,
                "blocking": bool(question.blocking),
            }
        )

    return {
        "package_version": PACKAGE_VERSION,
        "source": "canonical-spec",
        "service_id": spec.service_id,
        "service_name": spec.service_name,
        "review": {
            "status": "blocked" if any_blocked else "pending_review",
            "executor_dispatch": False,
            "ready_for_executor": False,
            "note": (
                "Nenhuma task é enviada a executor antes de revisão humana. "
                "Este pacote não despacha implementação nem aplica/rollback."
            ),
            "unscoped_questions": unscoped,
        },
        "architecture": _architecture(spec, plan, ops),
        "api_decisions": [_api_decision(spec, op) for op in ops],
        "tasks": tasks,
        "graph": {
            "source": GRAPH_SOURCE,
            "origin": plan.get("origin") or "heuristic",
            "requires_review": bool(plan.get("requires_review", True)),
            "waves": waves,
            "note": plan.get("note"),
        },
    }


def render_sdd(spec: CanonicalSpec, template: str | None = None) -> str:
    """YAML determinístico do pacote SDD (mesmo IR ⇒ mesmos bytes)."""
    del template  # skeleton não contribui decisão — só o IR
    doc = build_sdd_package(spec)
    body = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)
    return HEADER + body
