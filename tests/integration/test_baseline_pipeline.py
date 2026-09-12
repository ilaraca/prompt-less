"""Integração baseline: serviços, HTTP, ownership, artefatos, budget."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.conftest import CASES

HTTP_RE = re.compile(r"\b(200|201|400|401|403|404|422)\b")


def _artifact_blobs(result: dict, out_root: Path) -> str:
    texts: list[str] = []
    if result.get("split") and result.get("by_context"):
        for ctx in result["by_context"]:
            for path in (ctx.get("outputs") or {}).values():
                p = Path(path)
                if p.exists():
                    texts.append(p.read_text(encoding="utf-8"))
            # spec / validation mesmo quando blocked
            for key in ("canonical_spec", "validation_report", "report"):
                p = Path(ctx.get(key) or "")
                if p.is_file():
                    texts.append(p.read_text(encoding="utf-8"))
            val = ctx.get("validation") or {}
            texts.append(str(val))
            texts.extend(ctx.get("questions") or [])
    else:
        for path in (result.get("outputs") or {}).values():
            p = Path(path)
            if p.exists():
                texts.append(p.read_text(encoding="utf-8"))
        texts.append(str(result.get("validation") or {}))
        texts.extend(result.get("questions") or [])
    for p in out_root.rglob("*"):
        if p.suffix in {".md", ".yaml", ".mmd", ".json"} and p.is_file():
            texts.append(p.read_text(encoding="utf-8"))
    return "\n".join(texts)


def _statuses_in(text: str) -> set[str]:
    return set(HTTP_RE.findall(text))


def _est_tokens(result: dict) -> list[int]:
    if result.get("split") and result.get("by_context"):
        return [int(c.get("est_tokens") or 0) for c in result["by_context"] if c.get("est_tokens")]
    n = int(result.get("est_tokens") or 0)
    return [n] if n else []


@pytest.mark.parametrize("case_id", CASES)
def test_baseline_pipeline_properties(case_id: str, run_case, load_expected):
    expected = load_expected(case_id)
    result, out_root = run_case(case_id, tipo=expected.get("tipo", "historia"))

    if expected.get("expect_blocked"):
        assert result.get("status") == "blocked"
        blob = _artifact_blobs(result, out_root)
        for code in expected.get("http_statuses") or []:
            assert str(code) in blob
        return

    want_services = set(expected.get("services") or [])
    if expected.get("split"):
        assert result.get("split") is True
        got = set(result.get("contexts") or [])
        assert want_services.issubset(got), f"serviços faltando: {want_services - got}"
    else:
        assert result.get("split") is False

    ownership = expected.get("ownership") or {}
    if result.get("by_context"):
        by_id = {
            (c.get("servico") or {}).get("id"): c
            for c in result["by_context"]
            if (c.get("servico") or {}).get("id")
        }
        for sid, repos in ownership.items():
            assert sid in by_id, f"contexto ausente: {sid}"
            got_repos = set((by_id[sid].get("servico") or {}).get("repos") or [])
            assert set(repos).issubset(got_repos), f"ownership {sid}: {set(repos) - got_repos}"

    want_artifacts = set(expected.get("artifacts") or [])
    if result.get("by_context"):
        for ctx in result["by_context"]:
            if (ctx.get("servico") or {}).get("id") == "_unassigned":
                continue
            if ctx.get("status") == "blocked":
                continue
            produced = set((ctx.get("outputs") or {}).keys())
            assert want_artifacts.issubset(produced), (
                f"artefatos {ctx.get('context')}: {want_artifacts - produced}"
            )
            for key, path in (ctx.get("outputs") or {}).items():
                if key == "canonical_spec":
                    continue
                assert Path(path).is_file()
    else:
        produced = set((result.get("outputs") or {}).keys())
        assert want_artifacts.issubset(produced)

    blob = _artifact_blobs(result, out_root)
    got_http = _statuses_in(blob)
    for code in expected.get("http_statuses") or []:
        assert str(code) in got_http, f"{case_id}: status {code} não encontrado nos artefatos"

    for signal in expected.get("signals") or []:
        assert signal.lower() in blob.lower() or signal in blob, (
            f"{case_id}: sinal ausente: {signal}"
        )

    max_tokens = int(expected.get("max_est_tokens") or 2000)
    for n in _est_tokens(result):
        assert n <= max_tokens, f"{case_id}: est_tokens {n} > budget {max_tokens}"
        assert n > 0

    state_file = out_root / "state" / "workflow.json"
    assert state_file.is_file()
    assert "ruido telemetria" not in state_file.read_text(encoding="utf-8").lower()


def test_two_services_partition(run_case, load_expected):
    expected = load_expected("two_services")
    result, _ = run_case("two_services")
    preview = result.get("partition_preview") or {}
    assert "ms-cliente" in preview
    assert "ms-pagamento" in preview
    assert preview["ms-cliente"]["lines"] > 0
    assert preview["ms-pagamento"]["lines"] > 0
    assert set(expected["ownership"]["ms-cliente"]).issubset(
        set(preview["ms-cliente"].get("repos") or [])
    )


def test_ambiguous_status_blocks_render(run_case, load_expected):
    """Ambiguidade crítica 400/422 bloqueia renderização (quality gate)."""
    expected = load_expected("ambiguous_status")
    assert expected.get("expect_blocked") is True
    result, out_root = run_case("ambiguous_status")
    assert result.get("status") == "blocked"
    blob = _artifact_blobs(result, out_root)
    assert "400" in blob and "422" in blob
    # não deve ter emitido história renderizada para o serviço ambíguo
    historias = list(out_root.rglob("historia.md"))
    assert not historias
