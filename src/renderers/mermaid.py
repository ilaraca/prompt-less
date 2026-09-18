"""Renderiza diagrama de sequência Mermaid determinístico a partir do IR.

Os atores (FE → BFF → API) vêm do template de arquitetura do projeto; método,
path, status e erros vêm **só** do Canonical Spec. Sem evidência no IR, o
diagrama declara `unresolved` em vez de inventar um 200.
"""
from __future__ import annotations

import re

from src.domain.spec import CanonicalSpec, Operation

UNRESOLVED_NOTE = "sucesso não resolvido no IR — requer revisão humana"

DEFAULT_TEMPLATE = """```mermaid
sequenceDiagram
    actor FE as Frontend (Tela)
    participant BFF as BFF
    participant API as API de Domínio

    %% {{happy_path}}
    %% {{alt_blocks}}
```
"""

_INDENT = "    "


def _placeholder_re(name: str) -> re.Pattern[str]:
    return re.compile(r"^[ \t]*%% \{\{" + name + r"\}\}[ \t]*$", re.MULTILINE)


def _fill(template: str, name: str, lines: list[str]) -> str:
    body = "\n".join(lines) if lines else f"{_INDENT}%% (sem {name} no IR)"
    return _placeholder_re(name).sub(lambda _: body, template, count=1)


def _call(op: Operation) -> str:
    return f"{(op.method or '').strip().upper()} {op.path}"


def _happy_path_lines(spec: CanonicalSpec) -> list[str]:
    lines: list[str] = []
    for op in spec.operations:
        if not op.method or not op.path:
            faltando = ", ".join(op.unresolved) or "method, path"
            lines.append(
                f"{_INDENT}%% {op.id} {op.name} — unresolved: {faltando} "
                "(sem evidência no IR)"
            )
            continue
        call = _call(op)
        lines.append(f"{_INDENT}%% {op.id} {op.name}")
        lines.append(f"{_INDENT}FE->>BFF: {call}")
        lines.append(f"{_INDENT}BFF->>API: {call}")
        success = op.resolved_success_status()
        if success is None:
            lines.append(f"{_INDENT}API-->>BFF: {UNRESOLVED_NOTE}")
            lines.append(f"{_INDENT}BFF-->>FE: {UNRESOLVED_NOTE}")
        else:
            payload = op.response_schema.id if op.response_schema else "sem payload no IR"
            lines.append(f"{_INDENT}API-->>BFF: {success}")
            lines.append(f"{_INDENT}BFF-->>FE: {success} {payload}")
    return lines


def _alt_lines(spec: CanonicalSpec) -> list[str]:
    lines: list[str] = []
    for op in spec.operations:
        if not op.method or not op.path:
            continue
        for err in spec.errors_of(op):
            rotulo = f"{op.id} {err.trigger} ({err.id})"
            resposta = f"{err.status} {err.code}" if err.code else str(err.status)
            lines.append(f"{_INDENT}alt {rotulo}")
            lines.append(f"{_INDENT * 2}API-->>BFF: {resposta}")
            lines.append(f"{_INDENT * 2}BFF-->>FE: {resposta}")
            lines.append(f"{_INDENT}end")
    return lines


def _open_question_lines(spec: CanonicalSpec) -> list[str]:
    return [
        f"{_INDENT}%% unresolved {q.id}: {q.text}"
        for q in spec.open_questions
    ]


def render_mermaid(spec: CanonicalSpec, template: str | None = None) -> str:
    """Sequência Mermaid determinística (mesmo IR ⇒ mesmos bytes)."""
    base = template if template and "{{happy_path}}" in template else DEFAULT_TEMPLATE
    out = _fill(base, "happy_path", _happy_path_lines(spec))
    out = _fill(out, "alt_blocks", _alt_lines(spec) + _open_question_lines(spec))
    return out
