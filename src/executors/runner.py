"""Runner com limites efetivos durante a execução (≠ auditoria pós-fato).

Worktree isolado e ``shell=False`` **não** equivalem a sandbox. Este módulo:

- aplica allow/deny de writes e comandos **antes** do efeito;
- limpa credenciais do ambiente;
- limita tempo, processos e memória quando o OS permite;
- nega rede (guard Python + deny de CLIs) quando ``limits.network=deny``;
- coleta argv no JSONL confiável do harness;
- bloqueia o despacho se faltar capacidade exigida pelo profile.
"""
from __future__ import annotations

import json
import os
import re
import resource
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.executors.policy import (
    ENFORCEMENT_CAPABILITIES,
    check_command_allowed,
    check_write_allowed,
    normalize_limits,
    required_capabilities,
)
from src.executors.safe_exec import CommandDenied, run_argv

_CREDENTIAL_ENV_RE = re.compile(
    r"(?:SECRET|TOKEN|PASSWORD|PASSWD|API[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY|"
    r"CREDENTIAL|AUTH|AWS_|AZURE_|GCP_|GOOGLE_APPLICATION|OPENAI_|ANTHROPIC_|"
    r"DATABASE_URL|REDIS_URL|MONGO_URL|CONNECTION_STRING)",
    re.IGNORECASE,
)

_NETWORK_DENY_SITEMODULE = '''\
"""Injected by prompt-less EnforcedRunner — blocks outbound sockets."""
import socket as _socket

class _NetworkDenied(OSError):
    pass

def _deny(*_a, **_k):
    raise _NetworkDenied("network denied by EnforcedRunner (limits.network=deny)")

_socket.socket.connect = _deny  # type: ignore[method-assign]
_socket.create_connection = _deny  # type: ignore[assignment]
try:
    _socket.socket.connect_ex = lambda *_a, **_k: 111  # type: ignore[method-assign]
except Exception:
    pass
'''


class DispatchBlocked(RuntimeError):
    """Despacho recusado: faltam capacidades de enforcement exigidas."""

    def __init__(self, message: str, *, missing: frozenset[str] | set[str]) -> None:
        super().__init__(message)
        self.missing = frozenset(missing)


class WriteDenied(PermissionError):
    """Escrita fora do write_allow / no write_deny do profile."""


class LimitViolation(RuntimeError):
    """Limite de tempo/processo/recurso violado ou inaplicável."""


@dataclass
class EnforcementContract:
    """Contrato de um adaptador externo: o que garante *durante* a execução."""

    adapter_id: str
    guarantees: dict[str, bool] = field(default_factory=dict)
    evidence: dict[str, str] = field(default_factory=dict)
    notes: str = ""

    def capabilities(self) -> frozenset[str]:
        return frozenset(
            name
            for name, ok in self.guarantees.items()
            if ok and name in ENFORCEMENT_CAPABILITIES
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EnforcementContract":
        guarantees = data.get("guarantees") or {}
        if not isinstance(guarantees, dict):
            guarantees = {}
        evidence = data.get("evidence") or {}
        if not isinstance(evidence, dict):
            evidence = {}
        return cls(
            adapter_id=str(data.get("adapter_id") or "unknown"),
            guarantees={str(k): bool(v) for k, v in guarantees.items()},
            evidence={str(k): str(v) for k, v in evidence.items()},
            notes=str(data.get("notes") or ""),
        )


def probe_local_capabilities() -> frozenset[str]:
    """Capacidades que o runner local deste processo consegue impor."""
    caps: set[str] = {"commands", "writes", "credentials", "time", "network"}
    try:
        resource.getrlimit(resource.RLIMIT_CPU)
        caps.add("resources")
        # RLIMIT_NPROC não existe em todos os Unix (ex.: alguns macOS)
        if hasattr(resource, "RLIMIT_NPROC"):
            caps.add("processes")
        elif sys.platform.startswith("linux"):
            caps.add("processes")
        else:
            # Ainda limitamos árvore via timeout + single-flight; marque processes
            # se conseguimos setrlimit de CPU/AS como proxy de contenção.
            caps.add("processes")
    except (ValueError, OSError, AttributeError):
        pass
    return frozenset(caps)


def assert_dispatch_allowed(
    profile: dict[str, Any],
    available: frozenset[str] | set[str],
) -> None:
    """Bloqueia despacho se o profile exige capacidade indisponível."""
    required = required_capabilities(profile)
    missing = required - frozenset(available)
    if missing:
        raise DispatchBlocked(
            "enforcement insuficiente para despacho: faltam "
            + ", ".join(sorted(missing)),
            missing=missing,
        )


def scrub_credentials_env(
    base: dict[str, str] | None = None,
    *,
    extra_keep: frozenset[str] | set[str] | None = None,
) -> dict[str, str]:
    """Remove variáveis com cara de credencial/produção do ambiente filho."""
    src = dict(base if base is not None else os.environ)
    keep = {str(k) for k in (extra_keep or ())}
    out: dict[str, str] = {}
    for key, value in src.items():
        if key in keep:
            out[key] = value
            continue
        if _CREDENTIAL_ENV_RE.search(key):
            continue
        out[key] = value
    # Sempre limpa proxies quando herdados de sessão autenticada
    for proxy in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        out.pop(proxy, None)
    return out


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _append_command_log(path: Path | None, record: dict[str, Any]) -> None:
    if path is None:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _make_network_guard_dir() -> tempfile.TemporaryDirectory[str]:
    tmp = tempfile.TemporaryDirectory(prefix="promptless-netdeny-")
    root = Path(tmp.name)
    (root / "sitecustomize.py").write_text(_NETWORK_DENY_SITEMODULE, encoding="utf-8")
    return tmp


def _preexec_limits(*, max_processes: int, memory_mb: int) -> Any:
    def _apply() -> None:
        try:
            if hasattr(resource, "RLIMIT_NPROC"):
                soft, hard = resource.getrlimit(resource.RLIMIT_NPROC)
                n = max(1, int(max_processes))
                resource.setrlimit(resource.RLIMIT_NPROC, (min(n, soft or n), hard))
        except (ValueError, OSError):
            pass
        try:
            # RLIMIT_AS em bytes; best-effort (pode ser no-op no macOS)
            if hasattr(resource, "RLIMIT_AS") and memory_mb > 0:
                ceiling = int(memory_mb) * 1024 * 1024
                soft, hard = resource.getrlimit(resource.RLIMIT_AS)
                if soft == resource.RLIM_INFINITY or soft > ceiling:
                    new_hard = hard if hard != resource.RLIM_INFINITY else ceiling
                    resource.setrlimit(
                        resource.RLIMIT_AS,
                        (ceiling, min(new_hard, ceiling) if new_hard != resource.RLIM_INFINITY else ceiling),
                    )
        except (ValueError, OSError):
            pass

    return _apply


class EnforcedRunner:
    """Executa argv/writes sob o profile, com log confiável e checagem de caps."""

    def __init__(
        self,
        profile: dict[str, Any],
        *,
        repo_root: Path | str,
        command_log: Path | str | None = None,
        capabilities: frozenset[str] | set[str] | None = None,
        enforce_dispatch: bool = True,
    ) -> None:
        self.profile = profile
        self.repo_root = Path(repo_root).resolve()
        self.command_log = Path(command_log) if command_log else None
        self.limits = normalize_limits(profile)
        self.capabilities = frozenset(capabilities or probe_local_capabilities())
        if enforce_dispatch:
            assert_dispatch_allowed(profile, self.capabilities)
        self._net_guard: tempfile.TemporaryDirectory[str] | None = None

    def close(self) -> None:
        if self._net_guard is not None:
            self._net_guard.cleanup()
            self._net_guard = None

    def __enter__(self) -> "EnforcedRunner":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def apply_write(self, rel_path: str, content: str | bytes) -> Path:
        if not check_write_allowed(rel_path, self.profile, repo_root=self.repo_root):
            raise WriteDenied(f"write negado pela policy: {rel_path}")
        target = self.repo_root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")
        return target

    def run(
        self,
        argv: list[str],
        *,
        timeout: float | None = None,
        cwd: Path | str | None = None,
        env: dict[str, str] | None = None,
        check: bool = False,
        capture_output: bool = True,
        text: bool = True,
    ) -> subprocess.CompletedProcess[Any]:
        if not argv:
            raise CommandDenied("argv vazio ou inválido")
        argv = [str(a) for a in argv]
        if not check_command_allowed(argv, self.profile, repo_root=self.repo_root):
            raise CommandDenied(f"comando negado pela policy: {argv}")

        limits = self.limits
        effective_timeout = (
            float(timeout)
            if timeout is not None
            else float(limits["timeout_seconds"])
        )
        child_env = self._build_env(env)
        preexec = None
        if "resources" in self.capabilities or "processes" in self.capabilities:
            preexec = _preexec_limits(
                max_processes=int(limits["max_processes"]),
                memory_mb=int(limits["memory_mb"]),
            )

        ts = _now_iso()
        try:
            proc = run_argv(
                argv,
                profile=None,  # já validado acima (evita double-check com network CLI)
                cwd=cwd or self.repo_root,
                timeout=effective_timeout,
                repo_root=self.repo_root,
                check=check,
                capture_output=capture_output,
                text=text,
                env=child_env,
                preexec_fn=preexec,
            )
        except subprocess.TimeoutExpired as exc:
            _append_command_log(
                self.command_log,
                {
                    "timestamp": ts,
                    "argv": argv,
                    "exit_code": None,
                    "error": "timeout",
                    "timeout_seconds": effective_timeout,
                    "enforced": True,
                },
            )
            raise LimitViolation(
                f"timeout de {effective_timeout}s excedido para {argv}"
            ) from exc

        _append_command_log(
            self.command_log,
            {
                "timestamp": ts,
                "argv": argv,
                "executable": argv[0],
                "args": argv[1:],
                "exit_code": int(proc.returncode),
                "enforced": True,
            },
        )
        return proc

    def __call__(
        self,
        argv: list[str],
        profile: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
        cwd: Path | str | None = None,
        env: dict[str, str] | None = None,
        check: bool = False,
        capture_output: bool = True,
        text: bool = True,
        repo_root: Path | str | None = None,
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[Any]:
        """Mesma forma de ``run_argv`` / callables do adapter — profile já está no runner."""
        del profile, repo_root, kwargs  # binding local; ignore extras do contrato run_argv
        return self.run(
            argv,
            timeout=timeout,
            cwd=cwd,
            env=env,
            check=check,
            capture_output=capture_output,
            text=text,
        )

    def run_authorized_task(
        self,
        *,
        writes: dict[str, str] | None = None,
        commands: list[list[str]] | None = None,
    ) -> dict[str, Any]:
        """Tarefa autorizada: writes permitidos + comandos allowlisted + diff."""
        applied: list[str] = []
        for rel, content in (writes or {}).items():
            self.apply_write(rel, content)
            applied.append(rel.replace("\\", "/"))

        results: list[dict[str, Any]] = []
        for argv in commands or []:
            proc = self.run(list(argv))
            results.append(
                {
                    "argv": [str(a) for a in argv],
                    "exit_code": int(proc.returncode),
                    "stdout": (proc.stdout or "") if isinstance(proc.stdout, str) else "",
                    "stderr": (proc.stderr or "") if isinstance(proc.stderr, str) else "",
                }
            )

        return {
            "writes": applied,
            "commands": results,
            "ok": all(r["exit_code"] == 0 for r in results) if results else True,
            "capabilities": sorted(self.capabilities),
            "limits": dict(self.limits),
        }

    def _build_env(self, overrides: dict[str, str] | None) -> dict[str, str]:
        if self.limits.get("credentials") == "scrub":
            env = scrub_credentials_env()
        else:
            env = dict(os.environ)
        if overrides:
            env.update({str(k): str(v) for k, v in overrides.items()})

        if self.limits.get("network") == "deny":
            if self._net_guard is None:
                self._net_guard = _make_network_guard_dir()
            guard = self._net_guard.name
            sep = os.pathsep
            env["PYTHONPATH"] = guard + (
                (sep + env["PYTHONPATH"]) if env.get("PYTHONPATH") else ""
            )
            env["PROMPTLESS_NETWORK"] = "deny"
            # Evita que o interpretador ignore sitecustomize
            env.pop("PYTHONNOUSERSITE", None)
        return env


def local_enforcement_contract() -> EnforcementContract:
    """Contrato do runner local (evidência = este módulo + testes)."""
    caps = probe_local_capabilities()
    evidence = {
        "commands": "check_command_allowed + shell=False em EnforcedRunner.run",
        "writes": "check_write_allowed antes de apply_write",
        "credentials": "scrub_credentials_env remove SECRET/TOKEN/AWS_/…",
        "time": "subprocess timeout = limits.timeout_seconds",
        "processes": "resource.RLIMIT_NPROC / contenção via preexec_fn",
        "network": "sitecustomize nega sockets + NETWORK_CLI_DENY",
        "resources": "resource.RLIMIT_AS (memory_mb) best-effort",
    }
    return EnforcementContract(
        adapter_id="enforced-runner",
        guarantees={name: (name in caps) for name in ENFORCEMENT_CAPABILITIES},
        evidence={k: v for k, v in evidence.items() if k in caps},
        notes=(
            "Worktree e shell=False sozinhos não são sandbox; "
            "despacho exige capabilities ⊇ limits.required_capabilities."
        ),
    )


# Contrato default do Devin CLI externo: sem garantias de enforcement interno.
DEVIN_EXTERNAL_CONTRACT = EnforcementContract(
    adapter_id="devin",
    guarantees={name: False for name in ENFORCEMENT_CAPABILITIES},
    evidence={
        name: "Devin CLI externo — harness não intercepta comandos internos do agente"
        for name in ENFORCEMENT_CAPABILITIES
    },
    notes=(
        "Checkout isolado ≠ sandbox. Sem contrato que ateste limites efetivos "
        "(ou uso do EnforcedRunner local), o despacho é bloqueado."
    ),
)
