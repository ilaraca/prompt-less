"""Execução de argv sempre com shell=False.

Para limites efetivos (writes, rede, credenciais, recursos) use
``src.executors.runner.EnforcedRunner`` — ``run_argv`` sozinho só aplica
allowlist de comando quando ``profile`` é passado.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from src.executors.policy import check_command_allowed


class ShellForbidden(ValueError):
    """Tentativa de executar comando via shell."""


class CommandDenied(PermissionError):
    """Comando fora da allowlist semântica da policy."""


def run_argv(
    argv: list[str],
    profile: dict[str, Any] | None = None,
    *,
    cwd: Path | str | None = None,
    timeout: float | None = None,
    repo_root: Path | str | None = None,
    check: bool = False,
    capture_output: bool = True,
    text: bool = True,
    env: dict[str, str] | None = None,
    **kwargs: Any,
) -> subprocess.CompletedProcess[Any]:
    """subprocess.run com argv em lista. `shell` verdadeiro é recusado.

    Nota: ``profile=None`` **não** impõe policy — só `shell=False`. Worktree
    isolado também não é sandbox. Preferir ``EnforcedRunner`` para despacho.
    """
    if kwargs.pop("shell", False):
        raise ShellForbidden("execução via shell é proibida")
    if not argv or not isinstance(argv, list):
        raise CommandDenied("argv vazio ou inválido")
    argv = [str(a) for a in argv]
    if profile is not None and not check_command_allowed(argv, profile, repo_root=repo_root):
        raise CommandDenied(f"comando negado pela policy: {argv}")
    return subprocess.run(  # noqa: S603 — argv list, shell=False
        argv,
        shell=False,
        cwd=cwd,
        timeout=timeout,
        check=check,
        capture_output=capture_output,
        text=text,
        env=env,
        **kwargs,
    )
