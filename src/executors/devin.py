"""Adapter Devin — CLI real, JSONL estruturado e ExecutionResult do runner.

Limites efetivos: worktree/`shell=False` ≠ sandbox. O despacho exige um
``EnforcementContract`` cujas ``guarantees`` cubram ``limits.required_capabilities``
do profile da camada (ou o runner local ``EnforcedRunner``). Sem isso,
``DispatchBlocked``. Ver README § enforcement.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.executors.base import ExecutionResult
from src.executors.evidence import (
    GitEvidenceError,
    HARNESS_EXECUTED_BY,
    command_argv,
    full_commit_sha,
    hash_bytes,
    inspect_commits,
    is_behavioral_test_command,
    is_non_behavioral_kind,
    make_evidence_binding,
    normalize_test_kind,
    run_git,
    worktree_dirty,
)
from src.executors.policy import load_profiles, resolve_layer_profile
from src.executors.runner import (
    DEVIN_EXTERNAL_CONTRACT,
    DispatchBlocked,
    EnforcementContract,
    EnforcedRunner,
    assert_dispatch_allowed,
    local_enforcement_contract,
)
from src.executors.safe_exec import run_argv
from src.runtime.atomic_io import atomic_write_json, sha256_of

Runner = Callable[..., Any]


def invoke_runner(
    runner: Runner | EnforcedRunner,
    argv: list[str],
    *,
    profile: dict[str, Any] | None = None,
    cwd: Path | str | None = None,
    timeout: float | None = None,
    repo_root: Path | str | None = None,
    capture_output: bool = True,
    text: bool = True,
    **kwargs: Any,
) -> Any:
    """Invoca runner de forma uniforme (callable ou ``EnforcedRunner``)."""
    return runner(
        argv,
        profile=profile,
        cwd=cwd,
        timeout=timeout,
        repo_root=repo_root,
        capture_output=capture_output,
        text=text,
        **kwargs,
    )


class DirtyWorktreeError(RuntimeError):
    """Worktree sujo quando o contrato exige HEAD limpo."""


class DevinCliError(RuntimeError):
    """Falha ao invocar o Devin CLI."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def append_adapter_log(path: Path, record: dict[str, Any]) -> None:
    """Append de uma linha JSONL (runner real grava a evidência de comando)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)


def _read_prompt(*, prompt: str | None, prompt_file: Path | None) -> str:
    if prompt_file is not None:
        return Path(prompt_file).read_text(encoding="utf-8")
    if prompt is not None and str(prompt).strip():
        return str(prompt)
    raise ValueError("passe prompt= ou prompt_file= para o DevinAdapter")


def _load_sidecar_hints(repo: Path) -> dict[str, Any]:
    """Sidecar opcional escrito pelo agente — só dicas; commits/arquivos vêm do Git."""
    candidates = [
        repo / "docs" / "prompt-less" / "execution-result.json",
        repo / "docs" / "prompt-less" / "devin-result.json",
    ]
    for path in candidates:
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return {}
            return data if isinstance(data, dict) else {}
    return {}


def _commands_from_log(log_path: Path) -> list[str | dict[str, Any]]:
    if not log_path.is_file():
        return []
    commands: list[str | dict[str, Any]] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        if isinstance(rec.get("argv"), list) and rec["argv"]:
            argv = [str(a) for a in rec["argv"]]
            commands.append({"executable": argv[0], "args": argv[1:]})
        elif rec.get("command"):
            commands.append(rec["command"])
    return commands


def _tests_from_sidecar(hints: dict[str, Any], *, log_dir: Path) -> list[dict[str, Any]]:
    raw = hints.get("tests")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        test = dict(item)
        log_rel = test.get("log")
        if isinstance(log_rel, str) and log_rel and not Path(log_rel).is_absolute():
            candidate = log_dir / log_rel
            if candidate.is_file():
                test["log"] = str(candidate)
        out.append(test)
    return out


class DevinAdapter:
    id = "devin"

    def __init__(
        self,
        *,
        result_path: Path | None = None,
        cli_bin: str = "devin",
        runner: Runner | None = None,
        enforcement_contract: EnforcementContract | dict[str, Any] | None = None,
    ) -> None:
        self.result_path = result_path
        self.cli_bin = cli_bin
        self.runner = runner or run_argv
        self.enforcement_contract = self._coerce_contract(enforcement_contract)

    @staticmethod
    def _coerce_contract(
        value: EnforcementContract | dict[str, Any] | None,
    ) -> EnforcementContract | None:
        if value is None:
            return None
        if isinstance(value, EnforcementContract):
            return value
        return EnforcementContract.from_dict(value)

    def resolve_enforcement_contract(self) -> EnforcementContract:
        """Contrato efetivo: explícito, runner local, ou default externo (sem garantias)."""
        if self.enforcement_contract is not None:
            return self.enforcement_contract
        if isinstance(self.runner, EnforcedRunner):
            return local_enforcement_contract()
        return DEVIN_EXTERNAL_CONTRACT

    def prepare(
        self,
        *,
        run_id: str,
        artifacts_dir: str,
        repository: str,
    ) -> dict[str, Any]:
        art = Path(artifacts_dir)
        return {
            "run_id": run_id,
            "agent": self.id,
            "repository": repository,
            "artifacts_dir": str(art),
            "handoff": {
                "canonical_spec": str(art / "canonical-spec.yaml"),
                "prd": str(next(art.glob("**/PRD.md"), art / "PRD.md")),
                "historia": str(next(art.glob("**/historia.md"), art / "historia.md")),
            },
            "instructions": (
                f"Implemente run_id={run_id} respeitando canonical-spec.yaml. "
                "Mapeie RF/AC/NFR em requirement_traceability. "
                "Não altere arquivos fora do profile da camada. "
                "Opcional: grave docs/prompt-less/execution-result.json com "
                "requirement_traceability e testes evidenciados."
            ),
        }

    def collect_result(self, payload: dict[str, Any] | None = None) -> ExecutionResult:
        if payload:
            return ExecutionResult.from_dict(payload)
        if self.result_path and self.result_path.is_file():
            data = json.loads(self.result_path.read_text(encoding="utf-8"))
            return ExecutionResult.from_dict(data)
        raise FileNotFoundError(
            "Resultado do Devin ausente: passe payload ou result_path JSON"
        )

    def execute(
        self,
        *,
        run_id: str,
        repository: str,
        repo_path: Path | str,
        out_dir: Path | str,
        layer: str | None = None,
        profile: dict[str, Any] | None = None,
        prompt: str | None = None,
        prompt_file: Path | str | None = None,
        timeout: float | None = 3600.0,
        auto_commit: bool = True,
        invoke_cli: bool = True,
        require_cli: bool = True,
        require_enforcement: bool = True,
        enforcement_contract: EnforcementContract | dict[str, Any] | None = None,
        spec_hash: str | None = None,
    ) -> ExecutionResult:
        """Invoca o CLI, grava adapter-log.jsonl + execution.json e devolve o resultado.

        O ``ExecutionResult`` é montado pelo adapter a partir do Git e do JSONL —
        não aceita commits/arquivos só declarados pelo agente.

        Com ``require_enforcement=True`` (default), o despacho só ocorre se o
        contrato cobrir ``limits.required_capabilities`` do profile da camada.
        """
        repo = Path(repo_path)
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        log_path = out / "adapter-log.jsonl"
        result_path = out / "execution.json"
        self.result_path = result_path

        if not repo.is_dir():
            raise FileNotFoundError(f"repositório inexistente: {repo}")

        if profile is None and layer:
            profile = resolve_layer_profile(layer)
        elif profile is None and require_enforcement and invoke_cli:
            raise DispatchBlocked(
                "despacho exige layer/profile para enforcement "
                "(worktree ≠ sandbox; profile=None é recusado)",
                missing=frozenset({"commands", "writes"}),
            )

        contract = self._coerce_contract(enforcement_contract) or self.resolve_enforcement_contract()
        if require_enforcement and invoke_cli:
            if profile is None:
                raise DispatchBlocked(
                    "profile ausente — não há como validar limits.required_capabilities",
                    missing=frozenset({"commands"}),
                )
            assert_dispatch_allowed(profile, contract.capabilities())

        dirty, dirty_detail = worktree_dirty(repo)
        if dirty:
            raise DirtyWorktreeError(
                f"worktree sujo antes da execução (commite ou limpe): {dirty_detail}"
            )

        base_commit = full_commit_sha(repo, "HEAD")
        if not base_commit:
            raise GitEvidenceError(
                "MISSING_BASE_COMMIT",
                f"HEAD inválido em {repo} — base_commit é obrigatório antes da execução",
            )

        prompt_path = Path(prompt_file) if prompt_file else None
        session: dict[str, Any] = {
            "run_id": run_id,
            "agent": self.id,
            "repository": repository,
            "repo_path": str(repo),
            "base_commit": base_commit,
            "layer": layer,
            "enforcement": contract.to_dict(),
            "events": [],
        }

        if invoke_cli:
            text = _read_prompt(prompt=prompt, prompt_file=prompt_path)
            if prompt_path is None:
                prompt_path = out / "DEVIN_PROMPT.md"
                prompt_path.write_text(text, encoding="utf-8")
            self._invoke_cli(
                repo=repo,
                prompt_file=prompt_path,
                out_dir=out,
                session=session,
                timeout=timeout,
                require_cli=require_cli,
                profile=profile,
            )

        dirty_after, _ = worktree_dirty(repo)
        if dirty_after:
            if not auto_commit:
                raise DirtyWorktreeError(
                    "Devin deixou o worktree sujo e auto_commit=False — "
                    "commite antes do close_loop"
                )
            self._commit_result(repo, run_id=run_id, session=session)

        dirty_final, dirty_final_detail = worktree_dirty(repo)
        if dirty_final:
            raise DirtyWorktreeError(
                f"worktree ainda sujo vs result_commit: {dirty_final_detail}"
            )

        result_commit = full_commit_sha(repo, "HEAD")
        if not result_commit:
            raise GitEvidenceError(
                "MISSING_RESULT_COMMIT",
                "result_commit ausente após a execução",
            )

        git = inspect_commits(repo, base_commit, result_commit)
        if not git.ok:
            detail = "; ".join(f"{c}: {m}" for c, m in git.issues) or "git inválido"
            raise GitEvidenceError("GIT_INSPECTION_FAILED", detail)

        hints = _load_sidecar_hints(repo)
        trace = hints.get("requirement_traceability")
        if not isinstance(trace, dict):
            trace = {}
        unresolved = hints.get("unresolved_items")
        if not isinstance(unresolved, list):
            unresolved = []

        tests_suggested = _tests_from_sidecar(hints, log_dir=out)
        binding = make_evidence_binding(
            run_id=run_id,
            repository=repository,
            base_commit=git.base_sha or base_commit,
            result_commit=git.result_sha or result_commit,
            spec_hash=spec_hash,
        )
        profiles = load_profiles()
        profile = profiles.get(layer) if layer else None
        tests = self._materialize_test_evidence(
            tests_suggested,
            log_path=log_path,
            out_dir=out,
            repo=repo,
            binding=binding,
            profile=profile,
        )
        commands = _commands_from_log(log_path)
        command_strs: list[str] = []
        for cmd in commands:
            if isinstance(cmd, dict):
                exe = str(cmd.get("executable") or "")
                args = [str(a) for a in (cmd.get("args") or [])]
                command_strs.append(" ".join([exe, *args]).strip())
            else:
                command_strs.append(str(cmd))

        session["result_commit"] = result_commit
        session["changed_files"] = list(git.changed_files)
        atomic_write_json(out / "devin-session.json", session)
        atomic_write_json(out / "enforcement-contract.json", contract.to_dict())

        execution = ExecutionResult(
            run_id=run_id,
            agent=self.id,
            repository=repository,
            base_commit=git.base_sha or base_commit,
            result_commit=git.result_sha or result_commit,
            changed_files=list(git.changed_files),
            commands_executed=command_strs,
            tests=tests,
            unresolved_items=[str(x) for x in unresolved],
            requirement_traceability={
                str(k): [str(p) for p in (v or [])]
                for k, v in trace.items()
                if isinstance(v, list)
            },
            layer=layer or (str(hints["layer"]) if hints.get("layer") else None),
            approved=None,
            adapter_log=str(log_path),
        )
        atomic_write_json(result_path, execution.to_dict())
        return execution

    def _invoke_cli(
        self,
        *,
        repo: Path,
        prompt_file: Path,
        out_dir: Path,
        session: dict[str, Any],
        timeout: float | None,
        require_cli: bool,
        profile: dict[str, Any] | None = None,
    ) -> None:
        """Invoca o CLI. Metadados vão para ``devin-session.json``, não ao JSONL
        de evidência (o verify aplica policy de camada só aos comandos do log).

        A invocação do binário ``devin`` é meta-harness: ``runner(argv,
        profile=None)`` não aplica a allowlist de camada ao binário, mas se o
        runner for ``EnforcedRunner`` os limites de FS/rede/credenciais/tempo/
        recursos **permanecem**. Nunca trocar por ``run_argv``.
        """
        cli = self.cli_bin
        uses_real_exec = self.runner is run_argv or isinstance(self.runner, EnforcedRunner)
        if require_cli and uses_real_exec and shutil.which(cli) is None:
            raise DevinCliError(
                f"`{cli}` não está no PATH. Instale o Devin CLI ou use --dry-prep."
            )
        argv = [cli, "--print", "--prompt-file", str(prompt_file)]
        ts = _now_iso()
        run_kwargs: dict[str, Any] = {
            "cwd": str(repo),
            "timeout": timeout,
            "capture_output": True,
            "text": True,
        }
        # Sempre usar self.runner (callable). EnforcedRunner com profile=None
        # pula a allowlist do binário meta-CLI, mas mantém FS/rede/credenciais/
        # tempo/recursos — nunca substituir por run_argv (remove limites).
        enforced = isinstance(self.runner, EnforcedRunner)
        try:
            proc = self.runner(argv, profile=None, **run_kwargs)
            exit_code = int(getattr(proc, "returncode", 1))
            stdout = getattr(proc, "stdout", "") or ""
            stderr = getattr(proc, "stderr", "") or ""
        except Exception as exc:  # noqa: BLE001 — registra e propaga
            session["events"].append(
                {
                    "timestamp": ts,
                    "kind": "invoke",
                    "argv": argv,
                    "exit_code": 1,
                    "error": str(exc),
                    "profile_applied_to_cli": False,
                    "enforced_runner": enforced,
                    "layer_profile": bool(profile),
                }
            )
            raise DevinCliError(f"falha ao executar Devin CLI: {exc}") from exc

        cli_log = out_dir / "devin-cli.log"
        cli_log.write_text(
            f"stdout:\n{stdout}\n\nstderr:\n{stderr}\n",
            encoding="utf-8",
        )
        session["events"].append(
            {
                "timestamp": ts,
                "kind": "invoke",
                "argv": argv,
                "exit_code": exit_code,
                "log": cli_log.name,
                "profile_applied_to_cli": False,
                "enforced_runner": enforced,
                "layer_profile": bool(profile),
            }
        )
        if exit_code != 0:
            raise DevinCliError(
                f"Devin CLI saiu com código {exit_code}. Veja {cli_log}"
            )

    def _commit_result(
        self, repo: Path, *, run_id: str, session: dict[str, Any]
    ) -> None:
        ts = _now_iso()
        run_git(repo, "add", "-A")
        msg = f"prompt-less:devin run_id={run_id}"
        proc = run_git(repo, "commit", "-m", msg, check=False)
        session["events"].append(
            {
                "timestamp": ts,
                "kind": "commit",
                "argv": ["git", "commit", "-m", msg],
                "exit_code": int(proc.returncode),
            }
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise DirtyWorktreeError(f"falha ao commitar resultado do Devin: {detail}")

    def _materialize_test_evidence(
        self,
        suggestions: list[dict[str, Any]],
        *,
        log_path: Path,
        out_dir: Path,
        repo: Path,
        binding: dict[str, Any],
        profile: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Executa sugestões do sidecar via runner do harness.

        ``passed=True`` do agente **nunca** vira ``exit_code=0`` sem execução.
        Sidecar só sugere comando/kind/covers; argv/stdout/stderr/exit vêm do
        runner controlado pelo harness e ficam vinculados ao binding.
        """
        materialized: list[dict[str, Any]] = []
        if log_path.exists():
            log_path.unlink()
        if not suggestions:
            log_path.write_text("", encoding="utf-8")
            return materialized

        for index, suggestion in enumerate(suggestions):
            name = str(suggestion.get("name") or f"test-{index}")
            kind = normalize_test_kind(suggestion.get("kind"))
            covers = suggestion.get("covers") or suggestion.get("acceptance_criteria") or []
            if isinstance(covers, (str, int)):
                covers = [covers]
            covers_list = [str(c) for c in covers]

            if is_non_behavioral_kind(kind):
                # Stub/skip: registra separadamente; não executa nem finge passe.
                materialized.append(
                    {
                        "name": name,
                        "kind": kind,
                        "passed": False,
                        "suggestion_only": True,
                        "executed_by": None,
                        "covers": covers_list,
                        "binding": dict(binding),
                    }
                )
                continue

            command = suggestion.get("command") or suggestion.get("cmd")
            if command is None and isinstance(suggestion.get("argv"), list):
                raw_argv = [str(a) for a in suggestion["argv"]]
                command = (
                    {"executable": raw_argv[0], "args": raw_argv[1:]}
                    if raw_argv
                    else None
                )
            argv_t = command_argv(command) if command is not None else None
            if argv_t is None:
                # Sem comando: não inventa exit_code a partir de passed=.
                materialized.append(
                    {
                        "name": name,
                        "kind": kind,
                        "passed": False,
                        "suggestion_only": True,
                        "executed_by": None,
                        "covers": covers_list,
                        "binding": dict(binding),
                        "error": "sidecar sem comando executável",
                    }
                )
                continue

            argv = [str(a) for a in argv_t]
            if not is_behavioral_test_command(argv):
                # Autorizado + exit 0 ≠ prova: git diff / inspeção não bastam.
                materialized.append(
                    {
                        "name": name,
                        "kind": kind,
                        "passed": False,
                        "suggestion_only": True,
                        "executed_by": None,
                        "covers": covers_list,
                        "binding": dict(binding),
                        "command": {"executable": argv[0], "args": argv[1:]},
                        "argv": argv,
                        "error": (
                            "comando não é runner de teste comportamental "
                            "(kind/covers do agente não bastam)"
                        ),
                    }
                )
                continue

            ts = _now_iso()
            stdout = ""
            stderr = ""
            try:
                proc = invoke_runner(
                    self.runner,
                    argv,
                    profile=profile,
                    cwd=str(repo),
                    capture_output=True,
                    text=True,
                    repo_root=str(repo),
                )
                exit_code = int(getattr(proc, "returncode", 1))
                stdout = getattr(proc, "stdout", "") or ""
                stderr = getattr(proc, "stderr", "") or ""
            except Exception as exc:  # noqa: BLE001 — captura real da falha
                exit_code = 1
                stderr = str(exc)

            safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)[:80]
            log_name = f"harness-test-{safe or index}.log"
            log_body = f"argv: {argv!r}\nexit_code: {exit_code}\n\nstdout:\n{stdout}\n\nstderr:\n{stderr}\n"
            dest = out_dir / log_name
            dest.write_text(log_body, encoding="utf-8")
            log_digest = sha256_of(dest)

            rec: dict[str, Any] = {
                "timestamp": ts,
                "argv": argv,
                "command": " ".join(argv),
                "exit_code": exit_code,
                "log": log_name,
                "log_sha256": log_digest,
                "stdout_sha256": hash_bytes(stdout.encode("utf-8")),
                "stderr_sha256": hash_bytes(stderr.encode("utf-8")),
                "executed_by": HARNESS_EXECUTED_BY,
                "kind": kind,
                "binding": dict(binding),
                "name": name,
            }
            append_adapter_log(log_path, rec)

            materialized.append(
                {
                    "name": name,
                    "kind": kind,
                    "passed": exit_code == 0,
                    "command": {"executable": argv[0], "args": argv[1:]},
                    "argv": argv,
                    "exit_code": exit_code,
                    "timestamp": ts,
                    "log": log_name,
                    "log_sha256": log_digest,
                    "executed_by": HARNESS_EXECUTED_BY,
                    "covers": covers_list,
                    "binding": dict(binding),
                }
            )

        if not log_path.exists():
            log_path.write_text("", encoding="utf-8")
        return materialized


def main(argv: list[str] | None = None) -> None:
    """CLI: python -m src.executors.devin …"""
    import argparse
    import sys

    from src.executors.close_loop import close_loop
    from src.runtime.consume import RunNotReady, assert_run_ready_for_executor, resolve_run_dir
    from src.runtime.run_context import new_run_id, validate_run_id

    p = argparse.ArgumentParser(description="Prompt-less — DevinAdapter + close_loop")
    p.add_argument("--repo", type=Path, required=True, help="checkout isolado do app")
    p.add_argument("--repository", default=None, help="nome lógico do repo (default: basename)")
    p.add_argument("--run-id", default=None)
    p.add_argument("--root", type=Path, default=None, help="raiz com runs/<id> (gate de consumo)")
    p.add_argument("--artifacts", type=Path, default=None, help="dir com canonical-spec etc.")
    p.add_argument("--out", type=Path, default=None, help="dir para execution.json + adapter-log")
    p.add_argument("--spec", type=Path, default=None, help="canonical-spec.yaml p/ close_loop")
    p.add_argument("--layer", default=None)
    p.add_argument("--prompt-file", type=Path, default=None)
    p.add_argument("--prompt", default=None)
    p.add_argument("--cli", default="devin")
    p.add_argument("--timeout", type=float, default=3600.0)
    p.add_argument("--no-cli", action="store_true", help="só coleta/commit (sem invocar devin)")
    p.add_argument(
        "--enforcement-contract",
        type=Path,
        default=None,
        help="JSON com guarantees/evidence do sandbox externo (obrigatório p/ Devin real)",
    )
    p.add_argument(
        "--allow-unenforced",
        action="store_true",
        help="perigoso: despacha sem enforcement (só dry-run/lab)",
    )
    p.add_argument("--close-loop", action="store_true", help="roda verify após a execução")
    p.add_argument(
        "--validations",
        type=Path,
        default=None,
        help="dir para verify-report.json (default: <out>/../validations ou runs/<id>/validations)",
    )
    args = p.parse_args(argv)

    run_id = validate_run_id(args.run_id) if args.run_id else new_run_id()
    repo = args.repo.resolve()
    repository = args.repository or repo.name
    out = (args.out or (Path("runs") / run_id / "executor")).resolve()
    contract = None
    if args.enforcement_contract:
        contract = EnforcementContract.from_dict(
            json.loads(Path(args.enforcement_contract).read_text(encoding="utf-8"))
        )
    adapter = DevinAdapter(cli_bin=args.cli, enforcement_contract=contract)

    # Gate: run blocked/failed ou identidade divergente não despacha ao executor.
    root = (args.root or Path(".")).resolve()
    run_dir = resolve_run_dir(root, run_id)
    if (run_dir / "manifest.json").is_file():
        try:
            assert_run_ready_for_executor(
                run_dir,
                run_id=run_id,
                artifacts_dir=args.artifacts,
            )
        except RunNotReady as exc:
            print(
                json.dumps(
                    {
                        "status": exc.status or "blocked",
                        "run_id": exc.run_id or run_id,
                        "reason": exc.reason,
                        "error": str(exc),
                        "error_type": "RunNotReady",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            sys.exit(2)

    if args.artifacts:
        adapter.prepare(
            run_id=run_id,
            artifacts_dir=str(args.artifacts),
            repository=repository,
        )

    prompt_file = args.prompt_file
    if prompt_file is None and args.prompt is None:
        default_prompt = repo / "docs" / "prompt-less" / "DEVIN_PROMPT.md"
        if default_prompt.is_file():
            prompt_file = default_prompt

    try:
        execution = adapter.execute(
            run_id=run_id,
            repository=repository,
            repo_path=repo,
            out_dir=out,
            layer=args.layer,
            prompt=args.prompt,
            prompt_file=prompt_file,
            timeout=args.timeout,
            invoke_cli=not args.no_cli,
            require_cli=not args.no_cli,
            require_enforcement=not args.allow_unenforced and not args.no_cli,
        )
    except DispatchBlocked as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "run_id": run_id,
                    "reason": "enforcement_insufficient",
                    "missing": sorted(exc.missing),
                    "error": str(exc),
                    "error_type": "DispatchBlocked",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        sys.exit(2)
    print(json.dumps(execution.to_dict(), ensure_ascii=False, indent=2))

    if args.close_loop:
        spec = args.spec
        if spec is None and args.artifacts:
            candidate = Path(args.artifacts) / "canonical-spec.yaml"
            if candidate.is_file():
                spec = candidate
        if spec is None:
            print("erro: --close-loop exige --spec ou --artifacts com canonical-spec.yaml", file=sys.stderr)
            sys.exit(2)
        validations = args.validations
        if validations is None:
            # prefer runs/<id>/validations when out is under runs/<id>/
            if out.parent.name == run_id or (out.parent / "artifacts").is_dir():
                validations = out.parent / "validations"
            else:
                validations = out / "validations"
        report = close_loop(
            spec_path=Path(spec),
            result_path=out / "execution.json",
            layer=args.layer,
            out_dir=validations,
            repo_path=repo,
            adapter_log=out / "adapter-log.jsonl",
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if report["verify"]["status"] not in {"passed", "needs_approval"}:
            sys.exit(2)
        print(
            "Aprovação humana: python -m src.approval request-approval "
            f"--root . --run-id {run_id}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
