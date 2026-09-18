"""Seleção de evidência de eval por run_id + manifesto (31)."""
from __future__ import annotations

import threading
from pathlib import Path

import yaml

from src.learning.evals import score_case, select_run_evidence
from src.runtime.atomic_io import sha256_of
from src.runtime.integrity import seal_hmac
from src.runtime.run_context import RunContext
from src.runtime.run_store import RunStore
from src.run import run

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _seed_run(
    root: Path,
    run_id: str,
    *,
    status: str = "completed",
    spec: dict | None = None,
    historia: str | None = None,
    prd: str | None = None,
    tamper_rel: str | None = None,
    omit_manifest: bool = False,
    omit_integrity: bool = False,
    declare_run_id: str | None = None,
) -> Path:
    """Monta runs/<id>/ com manifesto + integrity.files (sem espelho)."""
    ctx = RunContext.create(root=root, objective="historia", run_id=run_id)
    store = RunStore(ctx)
    store.bootstrap()
    art = ctx.artifacts_dir
    art.mkdir(parents=True, exist_ok=True)
    files: list[dict] = []

    if spec is not None:
        path = art / "canonical-spec.yaml"
        path.write_text(yaml.safe_dump(spec), encoding="utf-8")
        files.append(
            {
                "path": "artifacts/canonical-spec.yaml",
                "bytes": path.stat().st_size,
                "sha256": sha256_of(path),
            }
        )
    if historia is not None:
        path = art / "historia.md"
        path.write_text(historia, encoding="utf-8")
        files.append(
            {
                "path": "artifacts/historia.md",
                "bytes": path.stat().st_size,
                "sha256": sha256_of(path),
            }
        )
    if prd is not None:
        path = art / "prd.md"
        path.write_text(prd, encoding="utf-8")
        files.append(
            {
                "path": "artifacts/prd.md",
                "bytes": path.stat().st_size,
                "sha256": sha256_of(path),
            }
        )

    store.finish(status, {"contexts": ["ms-cliente"]})
    if omit_manifest:
        ctx.manifest_path.unlink(missing_ok=True)
        return ctx.run_dir

    if omit_integrity:
        return ctx.run_dir

    integrity = {
        "algo": "hmac-sha256",
        "kid": "v1",
        "events_tip": store.events.tip,
        "files": files,
        "sealed_at": "2026-09-18T00:00:00Z",
    }
    integrity["hmac"] = seal_hmac(integrity)
    store.write_manifest(
        {
            "run_id": declare_run_id if declare_run_id is not None else run_id,
            "integrity": integrity,
        }
    )

    if tamper_rel:
        target = ctx.run_dir / tamper_rel
        target.write_text(target.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")
    return ctx.run_dir


def _spec_ok() -> dict:
    return {
        "claims": [{"id": "CLM-0001", "text": "cadastro POST /clientes cpf"}],
        "requirements": [
            {
                "id": "RF-0001",
                "text": "POST /clientes",
                "source_claims": ["CLM-0001"],
            }
        ],
        "acceptance_criteria": [],
        "operations": [],
        "errors": [{"trigger": "ok", "status": 200}, {"trigger": "cpf", "status": 400}],
        "open_questions": [],
    }


def _spec_wrong() -> dict:
    data = _spec_ok()
    data["errors"] = [{"trigger": "ok", "status": 500}]
    data["claims"] = [{"id": "CLM-0001", "text": "sem sinal esperado"}]
    return data


def test_old_correct_run_does_not_make_current_pass(tmp_path: Path):
    root = tmp_path / "eval-root"
    _seed_run(
        root,
        "run-old-ok",
        spec=_spec_ok(),
        historia="POST /clientes cpf",
        prd="POST /clientes cpf",
    )
    _seed_run(
        root,
        "run-new-bad",
        spec=_spec_wrong(),
        historia="lixo",
        prd="lixo",
    )
    # espelho de compatibilidade com a spec antiga correta — deve ser ignorado
    mirror = root / "outputs"
    mirror.mkdir(parents=True)
    (mirror / "canonical-spec.yaml").write_text(
        yaml.safe_dump(_spec_ok()), encoding="utf-8"
    )
    (mirror / "historia.md").write_text("POST /clientes cpf", encoding="utf-8")

    expected = {
        "critical": True,
        "http_statuses": [200, 400],
        "http_status_mode": "exact",
        "services": [],
        "signals": ["cpf"],
    }
    result = {
        "status": "completed",
        "run_id": "run-new-bad",
        "run_dir": str(root / "runs" / "run-new-bad"),
        "contexts": [],
        "by_context": [],
        "claims": [],
    }
    score = score_case(expected, result, output_root=root)
    assert score.selection_ok is True
    assert score.details["specs_loaded"] == 1
    assert score.expected_status_match is False
    assert score.passed is False
    # confirma que o espelho não entrou
    sel = select_run_evidence(root=root, run_id="run-new-bad")
    assert all(not p.startswith("outputs/") for p in sel.files_used)


def test_concurrent_runs_do_not_mix_evidence(tmp_path: Path):
    root = tmp_path / "concurrent"
    _seed_run(
        root,
        "run-alpha",
        spec={
            **_spec_ok(),
            "claims": [{"id": "CLM-0001", "text": "sinal-alpha"}],
            "errors": [{"status": 201}],
        },
        historia="sinal-alpha",
        prd="sinal-alpha",
    )
    _seed_run(
        root,
        "run-beta",
        spec={
            **_spec_ok(),
            "claims": [{"id": "CLM-0001", "text": "sinal-beta"}],
            "errors": [{"status": 202}],
        },
        historia="sinal-beta",
        prd="sinal-beta",
    )
    scores: dict[str, object] = {}
    erros: list[BaseException] = []

    def _score(rid: str, signal: str, status: int) -> None:
        try:
            expected = {
                "http_statuses": [status],
                "http_status_mode": "exact",
                "services": [],
                "signals": [signal],
            }
            result = {
                "status": "completed",
                "run_id": rid,
                "run_dir": str(root / "runs" / rid),
                "contexts": [],
                "by_context": [],
                "claims": [{"text": signal}],
            }
            scores[rid] = score_case(expected, result, output_root=root)
        except BaseException as exc:  # noqa: BLE001
            erros.append(exc)

    threads = [
        threading.Thread(target=_score, args=("run-alpha", "sinal-alpha", 201)),
        threading.Thread(target=_score, args=("run-beta", "sinal-beta", 202)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not erros, erros
    sa = scores["run-alpha"]
    sb = scores["run-beta"]
    assert sa.passed and sb.passed
    assert sa.details["actual_spec_statuses"] == [201]
    assert sb.details["actual_spec_statuses"] == [202]


def test_missing_manifest_fails(tmp_path: Path):
    root = tmp_path / "no-manifest"
    _seed_run(root, "run-x", spec=_spec_ok(), omit_manifest=True)
    sel = select_run_evidence(root=root, run_id="run-x")
    assert sel.ok is False
    assert any("manifesto ausente" in e for e in sel.errors)


def test_divergent_run_id_fails(tmp_path: Path):
    root = tmp_path / "divergent"
    _seed_run(root, "run-real", spec=_spec_ok(), declare_run_id="run-other")
    sel = select_run_evidence(root=root, run_id="run-real")
    assert sel.ok is False
    assert any("divergente" in e for e in sel.errors)


def test_tampered_artifact_fails(tmp_path: Path):
    root = tmp_path / "tamper"
    _seed_run(
        root,
        "run-tamper",
        spec=_spec_ok(),
        tamper_rel="artifacts/canonical-spec.yaml",
    )
    sel = select_run_evidence(root=root, run_id="run-tamper")
    assert sel.ok is False
    assert any("adulterado" in e for e in sel.errors)


def test_missing_integrity_files_fails(tmp_path: Path):
    root = tmp_path / "no-seal"
    _seed_run(root, "run-noseal", spec=_spec_ok(), omit_integrity=True)
    sel = select_run_evidence(root=root, run_id="run-noseal")
    assert sel.ok is False
    assert any("integrity.files" in e for e in sel.errors)


def test_score_without_run_id_rejects_disk_root(tmp_path: Path):
    (tmp_path / "canonical-spec.yaml").write_text(
        yaml.safe_dump(_spec_ok()), encoding="utf-8"
    )
    expected = {"http_statuses": [200, 400], "services": [], "signals": []}
    result = {"status": "completed", "contexts": [], "by_context": [], "claims": []}
    score = score_case(expected, result, output_root=tmp_path)
    assert score.selection_ok is False
    assert score.passed is False
    assert any("run_id obrigatório" in e for e in score.details["selection_errors"])


def test_blocked_run_scored_but_not_released(tmp_path: Path):
    root = tmp_path / "blocked"
    _seed_run(
        root,
        "run-blocked",
        status="blocked",
        spec=_spec_ok(),
        historia="POST /clientes cpf liberado-indevido",
        prd="POST /clientes cpf liberado-indevido",
    )
    expected = {
        "expect_blocked": True,
        "http_statuses": [200, 400],
        "http_status_mode": "exact",
        "services": [],
        "signals": ["cpf"],
    }
    result = {
        "status": "blocked",
        "run_id": "run-blocked",
        "run_dir": str(root / "runs" / "run-blocked"),
        "contexts": ["ms-cliente"],
        "by_context": [],
        "claims": [{"text": "cpf POST /clientes"}],
    }
    score = score_case(expected, result, output_root=root)
    assert score.selection_ok is True
    assert score.status_ok is True
    assert score.artifacts_released is False
    assert score.layer_scores["artifacts"]["released_for_implementation"] is False
    assert score.passed is True
    # textos de história/PRD não entram no blob liberado
    assert score.layer_scores["artifacts"]["prd_historia_signals"] is True


def test_live_pipeline_selection_ignores_sibling_run(tmp_path: Path):
    """Contraexemplo real: run antiga correta no mesmo root não salva a nova."""
    old = run(
        "historia",
        dry_run=True,
        inputs_dir=FIXTURES / "happy_path",
        output_root=tmp_path,
        run_id="eval-old-happy",
    )
    assert old["status"] == "completed"
    new = run(
        "historia",
        dry_run=True,
        inputs_dir=FIXTURES / "ambiguous_status",
        output_root=tmp_path,
        run_id="eval-new-amb",
    )
    expected = {
        "expect_blocked": True,
        "services": [],
        "signals": [],
        "http_statuses": [],
    }
    score = score_case(
        expected,
        new,
        output_root=tmp_path,
        run_id="eval-new-amb",
    )
    assert score.details["run_id"] == "eval-new-amb"
    sel = select_run_evidence(root=tmp_path, run_id="eval-new-amb")
    assert sel.ok
    assert all("eval-old-happy" not in p for p in sel.files_used)
    assert all(not p.startswith("outputs/") for p in sel.files_used)
    assert new.get("run_id") == "eval-new-amb"
