"""Tools de recovery search_claims / get_claim no pacote live e sobre claims da run."""
from __future__ import annotations

import json
from pathlib import Path

from src.hardening.claim_tools import (
    TOOL_GET_CLAIM,
    TOOL_SEARCH_CLAIMS,
    dispatch_tool,
    get_claim,
    load_run_claims,
    search_claims,
)
from src.reason import build_llm_package
from src.runtime.run import run

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

CLAIMS = [
    {
        "id": "CLM-R001",
        "text": "block status=400 trigger=CPF inválido",
        "service_id": "ms-cliente",
    },
    {
        "id": "CLM-R002",
        "text": "block status=403 trigger=sem permissão admin",
        "service_id": "ms-cliente",
    },
    {
        "id": "CLM-X",
        "text": "saldo negativo HTTP 422",
        "service_id": "ms-pagamento",
    },
]


def test_search_and_get_claim():
    hits = search_claims(CLAIMS, "CPF")
    assert [c["id"] for c in hits] == ["CLM-R001"]
    by_svc = search_claims(CLAIMS, "422", service_id="ms-pagamento")
    assert [c["id"] for c in by_svc] == ["CLM-X"]
    assert get_claim(CLAIMS, "CLM-R002")["text"].startswith("block status=403")
    assert get_claim(CLAIMS, "CLM-INEXISTENTE") is None
    missing = dispatch_tool(TOOL_GET_CLAIM, {"claim_id": "nope"}, CLAIMS)
    assert missing["ok"] is False
    found = dispatch_tool(TOOL_SEARCH_CLAIMS, {"query": "422"}, CLAIMS)
    assert found["ok"] is True and found["count"] == 1


def test_llm_package_exposes_recovery_tools():
    pkg = build_llm_package(
        {
            "system": "sys",
            "dynamic": {"comando": "Gerar historia", "contexto_comprimido": "ok"},
            "est_tokens": 3,
        },
        claims=CLAIMS,
        run_id="run-tools",
        scan_inputs=False,
    )
    names = {t["name"] for t in pkg["tools"]}
    assert names == {TOOL_SEARCH_CLAIMS, TOOL_GET_CLAIM}
    openai_names = {t["function"]["name"] for t in pkg["openai"]["tools"]}
    claude_names = {t["name"] for t in pkg["claude"]["tools"]}
    assert openai_names == names
    assert claude_names == names
    assert pkg["meta"]["claim_index"]["count"] == 3
    assert "CLM-R001" in pkg["meta"]["claim_index"]["ids"]


def test_tools_consult_claims_from_run(tmp_path: Path):
    result = run(
        "historia",
        dry_run=True,
        inputs_dir=FIXTURES / "happy_path",
        output_root=tmp_path,
        run_id="claims-rec-1",
    )
    assert result["status"] == "completed"
    run_dir = Path(result["run_dir"])
    claims = load_run_claims(run_dir)
    assert claims
    pkg_files = list(run_dir.rglob("llm_package_historia.json"))
    assert pkg_files
    package = json.loads(pkg_files[0].read_text(encoding="utf-8"))
    assert {t["name"] for t in package["tools"]} >= {TOOL_SEARCH_CLAIMS, TOOL_GET_CLAIM}
    cid = claims[0]["id"]
    got = get_claim(claims, cid)
    assert got is not None and got["id"] == cid
    hits = search_claims(claims, "400")
    assert hits, "search_claims deve achar o bloqueio HTTP 400 da fixture"
