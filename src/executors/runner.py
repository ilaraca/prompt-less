"""Runner com limites efetivos durante a execução (≠ auditoria pós-fato).

Worktree isolado e ``shell=False`` **não** equivalem a sandbox. Este módulo:

- aplica allow/deny de writes e comandos **antes** do efeito;
- contém escritas dos **processos filhos** (guard Python + sandbox OS quando
  disponível); só declara ``writes`` se a contenção for verificada;
- limpa credenciais do ambiente;
- limita tempo, processos e memória quando o OS permite;
- nega rede (guard Python + deny de CLIs) quando ``limits.network=deny``;
- coleta argv no JSONL confiável do harness;
- bloqueia o despacho se faltar capacidade exigida pelo profile;
- é **callable** com a mesma forma de ``run_argv`` (contrato compartilhado com
  adapters / ticket 35): ``runner(argv, profile=..., **kwargs)``.
"""
from __future__ import annotations

import json
import os
import re
import resource
import shutil
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

# Contém escritas de processos Python filhos (open / pathlib / os.open).
# Complementado por sandbox OS (sandbox-exec / bwrap) quando disponível.
_FS_DENY_SITEMODULE = '''\
"""Injected by prompt-less EnforcedRunner — blocks writes outside repo_root."""
from __future__ import annotations

import builtins
import io
import os
from pathlib import Path

_REPO = Path(os.environ.get("PROMPTLESS_REPO_ROOT", "") or ".").resolve()
_ORIG_OPEN = builtins.open
_ORIG_IO_OPEN = io.open
_ORIG_OS_OPEN = os.open
_ORIG_WRITE_TEXT = Path.write_text
_ORIG_WRITE_BYTES = Path.write_bytes
_ORIG_TOUCH = Path.touch
_ORIG_MKDIR = Path.mkdir
_ORIG_UNLINK = Path.unlink
_ORIG_PATH_OPEN = Path.open

def _allowed(path: object) -> bool:
    try:
        resolved = Path(path).resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    return resolved == _REPO or _REPO in resolved.parents

def _deny_outside(path: object, *, mode: str = "w") -> None:
    read_only = isinstance(mode, str) and (
        mode == "r"
        or mode.startswith("r")
        and "+" not in mode
        and "w" not in mode
        and "a" not in mode
        and "x" not in mode
    )
    if read_only:
        return
    if not _allowed(path):
        raise PermissionError(
            f"write outside repo denied by EnforcedRunner: {path!s} (repo={_REPO})"
        )

def _open_guard(file, mode="r", *args, **kwargs):
    _deny_outside(file, mode=str(mode) if mode is not None else "r")
    return _ORIG_OPEN(file, mode, *args, **kwargs)

builtins.open = _open_guard  # type: ignore[assignment]
io.open = _open_guard  # type: ignore[assignment]

def _os_open(path, flags, mode=0o777, *args, **kwargs):
    write_bits = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
    if flags & write_bits:
        _deny_outside(path, mode="w")
    return _ORIG_OS_OPEN(path, flags, mode, *args, **kwargs)

os.open = _os_open  # type: ignore[assignment]

def _write_text(self, *args, **kwargs):
    _deny_outside(self, mode="w")
    return _ORIG_WRITE_TEXT(self, *args, **kwargs)

def _write_bytes(self, *args, **kwargs):
    _deny_outside(self, mode="w")
    return _ORIG_WRITE_BYTES(self, *args, **kwargs)

def _touch(self, *args, **kwargs):
    _deny_outside(self, mode="w")
    return _ORIG_TOUCH(self, *args, **kwargs)

def _mkdir(self, *args, **kwargs):
    _deny_outside(self, mode="w")
    return _ORIG_MKDIR(self, *args, **kwargs)

def _unlink(self, *args, **kwargs):
    _deny_outside(self, mode="w")
    return _ORIG_UNLINK(self, *args, **kwargs)

def _path_open(self, mode="r", *args, **kwargs):
    _deny_outside(self, mode=str(mode) if mode is not None else "r")
    return _ORIG_PATH_OPEN(self, mode, *args, **kwargs)

Path.write_text = _write_text  # type: ignore[method-assign]
Path.write_bytes = _write_bytes  # type: ignore[method-assign]
Path.touch = _touch  # type: ignore[method-assign]
Path.mkdir = _mkdir  # type: ignore[method-assign]
Path.unlink = _unlink  # type: ignore[method-assign]
Path.open = _path_open  # type: ignore[method-assign]
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


def _darwin_sandbox_available() -> bool:
    return sys.platform == "darwin" and shutil.which("sandbox-exec") is not None


def _bwrap_available() -> bool:
    return shutil.which("bwrap") is not None


def os_fs_sandbox_available() -> bool:
    """True se há sandbox OS utilizável para conter writes de filhos não-Python."""
    return _darwin_sandbox_available() or _bwrap_available()


def _write_seatbelt_profile(path: Path, repo_root: Path) -> None:
    """Perfil Seatbelt: writes só sob repo_root (+ /dev para runtime)."""
    root = str(repo_root.resolve())
    # macOS resolve /var → /private/var; listar ambos.
    roots = {root}
    if root.startswith("/var/"):
        roots.add("/private" + root)
    if root.startswith("/tmp"):
        roots.add(root.replace("/tmp", "/private/tmp", 1))
    allow_lines = "\n".join(
        f'(allow file-write* (subpath "{r}"))' for r in sorted(roots)
    )
    body = f"""(version 1)
(allow default)
(deny file-write*)
{allow_lines}
(allow file-write-data (literal "/dev/null"))
(allow file-write-data (regex #"^/dev/"))
"""
    path.write_text(body, encoding="utf-8")


def _wrap_argv_os_sandbox(
    argv: list[str],
    *,
    repo_root: Path,
    seatbelt_path: Path | None,
) -> list[str]:
    """Envolve argv com sandbox-exec (Darwin) ou bwrap (Linux)."""
    root = str(repo_root.resolve())
    if _darwin_sandbox_available() and seatbelt_path is not None:
        return ["sandbox-exec", "-f", str(seatbelt_path), *argv]
    if _bwrap_available():
        # Sistema RO; repo RW; /tmp privado (não vaza writes para o host /tmp).
        return [
            "bwrap",
            "--die-with-parent",
            "--ro-bind",
            "/",
            "/",
            "--dev",
            "/dev",
            "--proc",
            "/proc",
            "--bind",
            root,
            root,
            "--tmpfs",
            "/tmp",
            "--chdir",
            root,
            *argv,
        ]
    return list(argv)


def _verify_python_write_containment() -> bool:
    """Sonda: filho Python não deve criar arquivo fora do repo com o guard ativo."""
    try:
        with tempfile.TemporaryDirectory(prefix="promptless-writecap-") as td:
            base = Path(td)
            repo = base / "repo"
            outside = base / "outside"
            repo.mkdir()
            outside.mkdir()
            marker = outside / "marker.txt"
            guard = base / "guard"
            guard.mkdir()
            (guard / "sitecustomize.py").write_text(_FS_DENY_SITEMODULE, encoding="utf-8")
            env = {
                **os.environ,
                "PROMPTLESS_REPO_ROOT": str(repo.resolve()),
                "PYTHONPATH": str(guard)
                + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else ""),
                "TMPDIR": str(repo / ".tmp"),
                "TEMP": str(repo / ".tmp"),
                "TMP": str(repo / ".tmp"),
            }
            (repo / ".tmp").mkdir(exist_ok=True)
            probe = (
                "from pathlib import Path\n"
                f"p = Path({str(marker)!r})\n"
                "try:\n"
                "    p.write_text('leaked')\n"
                "    print('LEAKED')\n"
                "except PermissionError:\n"
                "    print('DENIED')\n"
            )
            proc = subprocess.run(  # noqa: S603
                [sys.executable, "-c", probe],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if marker.exists():
                return False
            return "DENIED" in (proc.stdout or "") and "LEAKED" not in (proc.stdout or "")
    except (OSError, subprocess.SubprocessError, TimeoutError):
        return False


def _verify_os_write_containment() -> bool:
    """Sonda OS: redirect de shell para fora do repo deve falhar."""
    if not os_fs_sandbox_available():
        return False
    try:
        with tempfile.TemporaryDirectory(prefix="promptless-ossb-") as td:
            base = Path(td)
            repo = base / "repo"
            outside = base / "outside"
            repo.mkdir()
            outside.mkdir()
            marker = outside / "marker.txt"
            seatbelt = base / "profile.sb"
            if _darwin_sandbox_available():
                _write_seatbelt_profile(seatbelt, repo)
            argv = _wrap_argv_os_sandbox(
                ["/bin/sh", "-c", f"echo leaked > {marker}"],
                repo_root=repo,
                seatbelt_path=seatbelt if _darwin_sandbox_available() else None,
            )
            subprocess.run(  # noqa: S603
                argv,
                cwd=str(repo),
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            return not marker.exists()
    except (OSError, subprocess.SubprocessError, TimeoutError):
        return False


_CAPABILITIES_CACHE: frozenset[str] | None = None
_OS_WRITE_SANDBOX_OK: bool | None = None


def os_write_sandbox_verified() -> bool:
    """True se a sonda OS (sandbox-exec/bwrap) bloqueou write fora do repo."""
    global _OS_WRITE_SANDBOX_OK
    if _OS_WRITE_SANDBOX_OK is None:
        _OS_WRITE_SANDBOX_OK = _verify_os_write_containment()
    return bool(_OS_WRITE_SANDBOX_OK)


def probe_local_capabilities(*, refresh: bool = False) -> frozenset[str]:
    """Capacidades que o runner local deste processo consegue impor de fato."""
    global _CAPABILITIES_CACHE
    if _CAPABILITIES_CACHE is not None and not refresh:
        return _CAPABILITIES_CACHE
    caps: set[str] = {"commands", "credentials", "time", "network"}
    # writes: só se contenção de filhos for verificada (não basta apply_write).
    py_ok = _verify_python_write_containment()
    os_ok = os_write_sandbox_verified()
    if py_ok or os_ok:
        caps.add("writes")
    try:
        resource.getrlimit(resource.RLIMIT_CPU)
        caps.add("resources")
        caps.add("processes")
    except (ValueError, OSError, AttributeError):
        pass
    _CAPABILITIES_CACHE = frozenset(caps)
    return _CAPABILITIES_CACHE


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


def _make_guard_dir(module_source: str, *, prefix: str) -> tempfile.TemporaryDirectory[str]:
    tmp = tempfile.TemporaryDirectory(prefix=prefix)
    (Path(tmp.name) / "sitecustomize.py").write_text(module_source, encoding="utf-8")
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
            if hasattr(resource, "RLIMIT_AS") and memory_mb > 0:
                ceiling = int(memory_mb) * 1024 * 1024
                soft, hard = resource.getrlimit(resource.RLIMIT_AS)
                if soft == resource.RLIM_INFINITY or soft > ceiling:
                    new_hard = hard if hard != resource.RLIM_INFINITY else ceiling
                    resource.setrlimit(
                        resource.RLIMIT_AS,
                        (
                            ceiling,
                            min(new_hard, ceiling)
                            if new_hard != resource.RLIM_INFINITY
                            else ceiling,
                        ),
                    )
        except (ValueError, OSError):
            pass

    return _apply


class EnforcedRunner:
    """Executa argv/writes sob o profile, com log confiável e checagem de caps.

    Contrato callable (compatível com ``run_argv`` / adapters)::

        runner(argv, profile=None, *, cwd=..., timeout=..., ...)

    - ``profile is not None`` → aplica allowlist de comandos da camada.
    - ``profile is None`` → meta-invocação (ex.: binário Devin): **não** aplica
      allowlist de camada, mas **mantém** FS/rede/credenciais/tempo/recursos.
    Nunca substitua este objeto por ``run_argv`` — isso remove os limites.
    """

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
        self._fs_guard: tempfile.TemporaryDirectory[str] | None = None
        self._seatbelt: Path | None = None
        self._seatbelt_dir: tempfile.TemporaryDirectory[str] | None = None
        # Só envolve com sandbox OS se a sonda passou (fail-closed: binário
        # presente mas inaplicável → não quebra o filho; Python FS-guard cobre).
        self._os_sandbox = (
            "writes" in self.capabilities and os_write_sandbox_verified()
        )
        if self._os_sandbox and _darwin_sandbox_available():
            self._seatbelt_dir = tempfile.TemporaryDirectory(prefix="promptless-seatbelt-")
            self._seatbelt = Path(self._seatbelt_dir.name) / "profile.sb"
            _write_seatbelt_profile(self._seatbelt, self.repo_root)

    def close(self) -> None:
        for attr in ("_net_guard", "_fs_guard", "_seatbelt_dir"):
            tmp = getattr(self, attr)
            if tmp is not None:
                tmp.cleanup()
                setattr(self, attr, None)
        self._seatbelt = None

    def __enter__(self) -> "EnforcedRunner":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __call__(
        self,
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
        skip_command_policy: bool | None = None,
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[Any]:
        """API alinhada a ``run_argv`` — adapters chamam o runner como callable."""
        if kwargs.pop("shell", False):
            from src.executors.safe_exec import ShellForbidden

            raise ShellForbidden("execução via shell é proibida")
        # profile=None ⇒ meta-CLI (mantém limites; não exige allowlist de camada).
        if skip_command_policy is None:
            skip_command_policy = profile is None
        # repo_root no call é informativo; contenção usa self.repo_root.
        _ = repo_root
        return self.run(
            argv,
            timeout=timeout,
            cwd=cwd,
            env=env,
            check=check,
            capture_output=capture_output,
            text=text,
            skip_command_policy=bool(skip_command_policy),
            **kwargs,
        )

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
        skip_command_policy: bool = False,
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[Any]:
        if not argv:
            raise CommandDenied("argv vazio ou inválido")
        argv = [str(a) for a in argv]
        if not skip_command_policy:
            if not check_command_allowed(argv, self.profile, repo_root=self.repo_root):
                raise CommandDenied(f"comando negado pela policy: {argv}")

        if "writes" not in self.capabilities:
            raise DispatchBlocked(
                "enforcement insuficiente: contenção de writes de processos "
                "filhos indisponível nesta plataforma",
                missing=frozenset({"writes"}),
            )

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

        exec_argv = list(argv)
        if self._os_sandbox:
            exec_argv = _wrap_argv_os_sandbox(
                exec_argv,
                repo_root=self.repo_root,
                seatbelt_path=self._seatbelt,
            )

        ts = _now_iso()
        try:
            proc = run_argv(
                exec_argv,
                profile=None,  # já validado (ou meta-CLI)
                cwd=cwd or self.repo_root,
                timeout=effective_timeout,
                repo_root=self.repo_root,
                check=check,
                capture_output=capture_output,
                text=text,
                env=child_env,
                preexec_fn=preexec,
                **kwargs,
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
                    "os_sandbox": self._os_sandbox,
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
                "os_sandbox": self._os_sandbox,
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

    def _ensure_child_tmpdir(self) -> Path:
        tmp = self.repo_root / ".promptless-tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        return tmp

    def _build_env(self, overrides: dict[str, str] | None) -> dict[str, str]:
        if self.limits.get("credentials") == "scrub":
            env = scrub_credentials_env()
        else:
            env = dict(os.environ)
        if overrides:
            env.update({str(k): str(v) for k, v in overrides.items()})

        child_tmp = self._ensure_child_tmpdir()
        env["TMPDIR"] = str(child_tmp)
        env["TEMP"] = str(child_tmp)
        env["TMP"] = str(child_tmp)
        env["PYTHONPYCACHEPREFIX"] = str(child_tmp / "pycache")
        env["PROMPTLESS_REPO_ROOT"] = str(self.repo_root)

        # Guard de FS para filhos Python (sempre, se writes declarado).
        if "writes" in self.capabilities:
            if self._fs_guard is None:
                self._fs_guard = _make_guard_dir(
                    _FS_DENY_SITEMODULE, prefix="promptless-fsdeny-"
                )
            self._prepend_pythonpath(env, self._fs_guard.name)

        if self.limits.get("network") == "deny":
            if self._net_guard is None:
                self._net_guard = _make_guard_dir(
                    _NETWORK_DENY_SITEMODULE, prefix="promptless-netdeny-"
                )
            self._prepend_pythonpath(env, self._net_guard.name)
            env["PROMPTLESS_NETWORK"] = "deny"
            env.pop("PYTHONNOUSERSITE", None)
        return env

    @staticmethod
    def _prepend_pythonpath(env: dict[str, str], directory: str) -> None:
        sep = os.pathsep
        env["PYTHONPATH"] = directory + (
            (sep + env["PYTHONPATH"]) if env.get("PYTHONPATH") else ""
        )


def local_enforcement_contract() -> EnforcementContract:
    """Contrato do runner local (evidência = este módulo + testes)."""
    caps = probe_local_capabilities()
    evidence = {
        "commands": "check_command_allowed + shell=False em EnforcedRunner.run/__call__",
        "writes": (
            "apply_write + sitecustomize FS-deny nos filhos"
            + (" + sandbox-exec/bwrap" if os_fs_sandbox_available() else "")
            + " (capacidade só se sonda passar)"
        ),
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
            "despacho exige capabilities ⊇ limits.required_capabilities; "
            "EnforcedRunner é callable e não deve ser trocado por run_argv."
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
