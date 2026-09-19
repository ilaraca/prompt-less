"""Testes adversariais do storage da run: traversal, colisão, interrupção, concorrência."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from src.emit import emit
from src.runtime.run import run
from src.runtime import (
    InvalidContextId,
    InvalidRunId,
    InvalidStatusTransition,
    RunContext,
    RunIdCollision,
    RunStateConflict,
    RunStore,
    UnsafeRunPath,
    context_subdir,
    new_run_id,
    validate_run_id,
)
from src.runtime.state_store import write_state

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

RUN_IDS_MALICIOSOS = [
    "..",
    ".",
    "../escape",
    "../../etc/passwd",
    "a/b",
    "/absoluto",
    "runs/../../fora",
    "C:\\windows",
    "run\\id",
    "run id",
    "run\x00id",
    "",
    "-traco-inicial",
    ".oculto",
    "run.id",
    "latest",
    "x" * 65,
]


def _kill(*_args, **_kwargs):
    """Simula o processo morrendo exatamente no ponto de commit da escrita."""
    raise KeyboardInterrupt("kill simulado no meio da escrita")


def _novo_store(root: Path, run_id: str) -> RunStore:
    return RunStore(RunContext.create(root=root, objective="historia", run_id=run_id))


# ------------------------------------------------------------------ traversal


@pytest.mark.parametrize("run_id", RUN_IDS_MALICIOSOS)
def test_run_id_fora_do_formato_canonico_e_rejeitado(run_id: str, tmp_path: Path):
    with pytest.raises(InvalidRunId):
        RunContext.create(root=tmp_path, objective="historia", run_id=run_id)
    assert not (tmp_path / "runs").exists(), "nada pode ser criado antes da validação"


def test_run_id_gerado_e_canonico():
    assert validate_run_id(new_run_id())


def test_run_com_run_id_de_traversal_nao_escreve_fora(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    alvo = tmp_path / "fora"
    with pytest.raises(InvalidRunId):
        run(
            "historia",
            dry_run=True,
            inputs_dir=FIXTURES / "happy_path",
            output_root=root,
            run_id="../fora",
        )
    assert not alvo.exists()
    assert list(root.iterdir()) == []


def test_symlink_plantado_em_runs_nao_permite_escapar(tmp_path: Path):
    root = tmp_path / "root"
    (root / "runs").mkdir(parents=True)
    fora = tmp_path / "fora"
    fora.mkdir()
    os.symlink(str(fora), str(root / "runs" / "vazada"))
    with pytest.raises(UnsafeRunPath):
        RunContext.create(root=root, objective="historia", run_id="vazada")


def test_context_id_de_traversal_e_rejeitado(tmp_path: Path):
    with pytest.raises(InvalidContextId):
        context_subdir(tmp_path, "../fora")
    with pytest.raises(InvalidContextId):
        emit("historia", "conteudo", context="../fora", root=tmp_path)
    assert not (tmp_path.parent / "fora").exists()


# ------------------------------------------------------- contrato de contexts


def test_contexts_tem_contrato_unico(tmp_path: Path):
    ctx = RunContext.create(root=tmp_path, objective="historia", run_id="ctx-1")
    assert ctx.contexts_dir == ctx.artifacts_dir / "contextos"
    assert (
        ctx.context_artifacts_dir("ms-cliente")
        == ctx.artifacts_dir / "contextos" / "ms-cliente"
    )
    assert (
        ctx.context_validations_dir("_unassigned")
        == ctx.validations_dir / "contextos" / "_unassigned"
    )


def test_run_multi_contexto_grava_no_contrato_unico(tmp_path: Path):
    result = run(
        "historia",
        dry_run=True,
        inputs_dir=FIXTURES / "two_services",
        output_root=tmp_path,
        run_id="ctx-multi-1",
    )
    run_dir = Path(result["run_dir"])
    assert not (run_dir / "contexts").exists(), "diretório morto do contrato antigo"
    contextos = result.get("contexts") or []
    assert contextos
    for sid in contextos:
        assert (run_dir / "artifacts" / "contextos" / sid).is_dir()
        assert (
            run_dir / "validations" / "contextos" / sid / "spec-validation.json"
        ).is_file()
        assert (tmp_path / "outputs" / "contextos" / sid).is_dir()


# ------------------------------------------------------------------- colisão


def test_colisao_de_run_id_preserva_a_run_existente(tmp_path: Path):
    store = _novo_store(tmp_path, "run-colisao-1")
    store.bootstrap()
    artefato = store.ctx.artifacts_dir / "historia.md"
    artefato.write_text("primeira run", encoding="utf-8")
    store.finish("completed")
    manifest_antes = store.ctx.manifest_path.read_text(encoding="utf-8")

    with pytest.raises(RunIdCollision):
        _novo_store(tmp_path, "run-colisao-1").bootstrap()

    assert artefato.read_text(encoding="utf-8") == "primeira run"
    assert store.ctx.manifest_path.read_text(encoding="utf-8") == manifest_antes


def test_run_com_run_id_repetido_falha_sem_sobrescrever(tmp_path: Path):
    primeira = run(
        "historia",
        dry_run=True,
        inputs_dir=FIXTURES / "happy_path",
        output_root=tmp_path,
        run_id="run-dup-1",
    )
    run_dir = Path(primeira["run_dir"])
    antes = sorted(p.name for p in run_dir.rglob("*") if p.is_file())

    with pytest.raises(RunIdCollision):
        run(
            "historia",
            dry_run=True,
            inputs_dir=FIXTURES / "happy_path",
            output_root=tmp_path,
            run_id="run-dup-1",
        )

    assert sorted(p.name for p in run_dir.rglob("*") if p.is_file()) == antes
    assert json.loads(run_dir.joinpath("manifest.json").read_text(encoding="utf-8"))[
        "status"
    ] == primeira["status"]


def test_retomada_explicita_reaproveita_o_diretorio(tmp_path: Path):
    store = _novo_store(tmp_path, "run-retomada-1")
    store.bootstrap()
    inicio = store.read_manifest()["started_at"]
    versao = store.manifest_version

    store.bootstrap(resume=True)

    manifest = store.read_manifest()
    assert manifest["resumed"] is True
    assert manifest["started_at"] == inicio
    assert manifest["version"] > versao


# ----------------------------------------------------- transições versionadas


def test_transicoes_de_status_usam_controle_de_versao(tmp_path: Path):
    store = _novo_store(tmp_path, "run-status-1")
    store.bootstrap()
    assert store.status == "running"
    versao = store.manifest_version
    assert versao >= 1

    with pytest.raises(RunStateConflict):
        store.write_manifest({"current_stage": "emit"}, expected_version=versao - 1)
    store.write_manifest({"current_stage": "emit"}, expected_version=versao)
    assert store.manifest_version == versao + 1

    store.finish("completed")
    assert store.is_finished
    with pytest.raises(InvalidStatusTransition):
        store.set_status("running")
    with pytest.raises(InvalidStatusTransition):
        store.finish("failed")

    historico = store.read_manifest()["status_history"]
    assert [h["to"] for h in historico] == ["running", "completed"]
    versoes = [h["version"] for h in historico]
    assert versoes == sorted(versoes)
    assert json.loads(
        (tmp_path / "runs" / "latest.json").read_text(encoding="utf-8")
    )["status"] == "completed"


def test_status_final_desconhecido_e_recusado(tmp_path: Path):
    store = _novo_store(tmp_path, "run-status-2")
    store.bootstrap()
    with pytest.raises(InvalidStatusTransition):
        store.finish("quase-pronto")


# --------------------------------------------------------------- interrupção


def test_interrupcao_no_commit_nao_deixa_manifest_parcial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = _novo_store(tmp_path, "run-kill-1")
    store.bootstrap()
    antes = store.read_manifest()

    with monkeypatch.context() as m:
        m.setattr("os.replace", _kill)
        with pytest.raises(KeyboardInterrupt):
            store.write_manifest({"current_stage": "emit", "lixo": "x" * 100_000})

    depois = json.loads(store.ctx.manifest_path.read_text(encoding="utf-8"))
    assert depois == antes
    assert "lixo" not in depois
    assert not list(store.ctx.run_dir.glob(".tmp-*")), "temporário órfão no run_dir"


def test_interrupcao_nao_corrompe_state_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path / "state.json"
    write_state({"tipo": "historia", "status": "ok"}, path)
    original = path.read_text(encoding="utf-8")

    with monkeypatch.context() as m:
        m.setattr("os.replace", _kill)
        with pytest.raises(KeyboardInterrupt):
            write_state(
                {"tipo": "historia", "status": "novo", "documents": [{"name": "x"}]},
                path,
            )

    assert path.read_text(encoding="utf-8") == original
    assert json.loads(original)["status"] == "ok"
    assert not list(tmp_path.glob(".tmp-*"))


def test_interrupcao_no_provenance_preserva_relatorio_anterior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = _novo_store(tmp_path, "run-kill-2")
    store.bootstrap()
    prov = store.write_provenance(claims=[{"id": "c1"}], discarded=[])
    original = prov.read_text(encoding="utf-8")

    with monkeypatch.context() as m:
        m.setattr("os.replace", _kill)
        with pytest.raises(KeyboardInterrupt):
            store.write_provenance(claims=[{"id": "c2"}], discarded=[{"id": "d"}])

    assert prov.read_text(encoding="utf-8") == original
    assert json.loads(original)["claims"] == [{"id": "c1"}]


def test_leitor_concorrente_nunca_ve_manifest_parcial(tmp_path: Path):
    store = _novo_store(tmp_path, "run-leitor-1")
    store.bootstrap()
    parciais: list[str] = []
    parar = threading.Event()

    def _ler() -> None:
        while not parar.is_set():
            try:
                texto = store.ctx.manifest_path.read_text(encoding="utf-8")
            except OSError:
                continue
            try:
                json.loads(texto)
            except ValueError:
                parciais.append(texto[:80])

    leitor = threading.Thread(target=_ler, daemon=True)
    leitor.start()
    try:
        for i in range(120):
            store.write_manifest({"current_stage": f"etapa-{i}", "ruido": "y" * i * 50})
    finally:
        parar.set()
        leitor.join(timeout=5)

    assert parciais == []


# --------------------------------------------------------------- concorrência


def test_duas_runs_concorrentes_preservam_artefatos_e_provenance(tmp_path: Path):
    resultados: dict[str, dict] = {}
    erros: list[BaseException] = []

    def _executar(run_id: str) -> None:
        try:
            resultados[run_id] = run(
                "historia",
                dry_run=True,
                inputs_dir=FIXTURES / "happy_path",
                output_root=tmp_path,
                run_id=run_id,
            )
        except BaseException as exc:  # noqa: BLE001 — o teste reporta qualquer falha
            erros.append(exc)

    threads = [
        threading.Thread(target=_executar, args=(rid,))
        for rid in ("run-par-a", "run-par-b")
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not erros, erros
    assert set(resultados) == {"run-par-a", "run-par-b"}

    for run_id, resultado in resultados.items():
        run_dir = Path(resultado["run_dir"])
        assert resultado["status"] == "completed"
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["run_id"] == run_id
        assert manifest["status"] == "completed"
        provenance = json.loads(
            (run_dir / "validations" / "provenance.json").read_text(encoding="utf-8")
        )
        assert provenance["run_id"] == run_id
        assert list(run_dir.rglob("historia.md")), f"{run_id} sem artefato"

    a, b = (Path(resultados[r]["run_dir"]) for r in ("run-par-a", "run-par-b"))
    assert a != b
    assert (a / "state.json").read_bytes() and (b / "state.json").read_bytes()
    latest = json.loads((tmp_path / "runs" / "latest.json").read_text(encoding="utf-8"))
    assert latest["run_id"] in resultados


# -------------------------------------------------------------------- espelho


def test_espelho_publica_por_manifesto_e_remove_obsoletos(tmp_path: Path):
    store = _novo_store(tmp_path, "run-esp-1")
    store.bootstrap()
    (store.ctx.artifacts_dir / "historia.md").write_text("v1", encoding="utf-8")
    ms_a = store.ctx.context_artifacts_dir("ms-a")
    ms_a.mkdir(parents=True)
    (ms_a / "PRD.md").write_text("prd antigo", encoding="utf-8")

    outputs = tmp_path / "outputs"
    outputs.mkdir()
    do_usuario = outputs / "arquivo-do-usuario.txt"
    do_usuario.write_text("não veio do espelho", encoding="utf-8")

    manifesto = store.mirror_artifacts_to_outputs(tmp_path)
    assert {f["path"] for f in manifesto["files"]} == {
        "historia.md",
        "contextos/ms-a/PRD.md",
    }
    assert all(len(f["sha256"]) == 64 for f in manifesto["files"])
    assert (outputs / ".mirror-manifest.json").is_file()
    assert (outputs / "contextos" / "ms-a" / "PRD.md").read_text() == "prd antigo"

    # segunda publicação: o PRD por contexto some, um PRD raiz aparece
    (ms_a / "PRD.md").unlink()
    (store.ctx.artifacts_dir / "PRD.md").write_text("prd novo", encoding="utf-8")
    store.mirror_artifacts_to_outputs(tmp_path)

    assert not (outputs / "contextos" / "ms-a" / "PRD.md").exists()
    assert not (outputs / "contextos").exists(), "diretório vazio deve ser podado"
    assert (outputs / "PRD.md").read_text(encoding="utf-8") == "prd novo"
    assert do_usuario.read_text(encoding="utf-8") == "não veio do espelho"


def test_espelho_ignora_symlink_e_nao_escreve_fora(tmp_path: Path):
    store = _novo_store(tmp_path, "run-esp-2")
    store.bootstrap()
    fora = tmp_path / "fora"
    fora.mkdir()
    segredo = fora / "segredo.txt"
    segredo.write_text("segredo", encoding="utf-8")
    os.symlink(str(segredo), str(store.ctx.artifacts_dir / "segredo.txt"))
    os.symlink(str(fora), str(store.ctx.artifacts_dir / "link-dir"))
    (store.ctx.artifacts_dir / "ok.md").write_text("ok", encoding="utf-8")

    manifesto = store.mirror_artifacts_to_outputs(tmp_path)

    assert {f["path"] for f in manifesto["files"]} == {"ok.md"}
    espelhados = {p.name for p in (tmp_path / "outputs").rglob("*") if p.is_file()}
    assert "segredo.txt" not in espelhados
    assert sorted(p.name for p in fora.iterdir()) == ["segredo.txt"]


def test_remocao_de_obsoletos_ignora_manifesto_adulterado(tmp_path: Path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    fora = tmp_path / "fora.txt"
    fora.write_text("intacto", encoding="utf-8")
    (outputs / ".mirror-manifest.json").write_text(
        json.dumps({"run_id": "antiga", "files": [{"path": "../fora.txt"}]}),
        encoding="utf-8",
    )

    store = _novo_store(tmp_path, "run-esp-3")
    store.bootstrap()
    (store.ctx.artifacts_dir / "a.md").write_text("a", encoding="utf-8")
    store.mirror_artifacts_to_outputs(tmp_path)

    assert fora.read_text(encoding="utf-8") == "intacto"
    assert (outputs / "a.md").read_text(encoding="utf-8") == "a"
