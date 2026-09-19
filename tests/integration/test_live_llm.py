"""Modo --live: clientes OpenAI Responses / Claude Messages com HTTP mock."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.reason import (
    LiveApiError,
    build_llm_package,
    build_live_telemetry,
    call_claude_messages,
    call_openai_responses,
    live_generate,
)
from src.runtime.run import run
from src.context.tokenizer import TokenEstimate

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _pkg() -> dict[str, Any]:
    return build_llm_package(
        {
            "system": "Você gera um artefato técnico curto.",
            "dynamic": {"comando": "openapi", "state": {"k": 1}},
            "est_tokens": 40,
            "est_tokens_method": "heuristic",
            "token_usage": {
                "estimated": 40,
                "tokens": 40,
                "method": "heuristic",
                "provider": "openai",
                "model": "gpt-4o",
                "billable": None,
                "delta": None,
                "label": "heurística chars÷4 (fallback; não é contagem exata)",
            },
        },
        scan_inputs=False,
    )


def _openai_transport(text: str = "# openapi live\ninfo: ok", *, cached: int = 10):
    def transport(
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout: float,
    ) -> tuple[int, bytes]:
        assert method == "POST"
        assert "responses" in url
        assert headers.get("Authorization", "").startswith("Bearer ")
        payload = {
            "id": "resp_test_1",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": text}],
                }
            ],
            "usage": {
                "input_tokens": 100,
                "output_tokens": 20,
                "input_tokens_details": {"cached_tokens": cached},
            },
        }
        return 200, json.dumps(payload).encode("utf-8")

    return transport


def _claude_transport(text: str = "# historia live\nOK", *, cache_read: int = 40):
    def transport(
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout: float,
    ) -> tuple[int, bytes]:
        assert method == "POST"
        assert "messages" in url
        assert headers.get("x-api-key")
        assert headers.get("anthropic-version")
        payload = {
            "id": "msg_test_1",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": text}],
            "usage": {
                "input_tokens": 80,
                "output_tokens": 25,
                "cache_read_input_tokens": cache_read,
            },
        }
        return 200, json.dumps(payload).encode("utf-8")

    return transport


def test_openai_responses_returns_text_and_billable_cache():
    live = call_openai_responses(
        _pkg(),
        model="gpt-4o",
        api_key="sk-test",
        transport=_openai_transport(),
    )
    assert "openapi live" in live.text
    assert live.usage.billable_tokens == 120
    assert live.usage.cache_read_tokens == 10
    assert live.usage.cache_hit_ratio == 0.1
    telemetry = build_live_telemetry(
        TokenEstimate(40, "heuristic", "openai", "gpt-4o"),
        live,
    )
    assert telemetry["billable"] == 120
    assert telemetry["delta"] == 80
    assert telemetry["cache_hit"] == 0.1
    assert telemetry["cost_usd"]["usd_total"] > 0


def test_claude_messages_returns_text_and_cache_hit():
    live = call_claude_messages(
        _pkg(),
        model="claude-sonnet",
        api_key="ant-test",
        transport=_claude_transport(),
    )
    assert "historia live" in live.text
    assert live.provider == "anthropic"
    assert live.usage.cache_read_tokens == 40
    assert live.usage.cache_hit_ratio == 0.5


def test_live_generate_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LiveApiError, match="OPENAI_API_KEY"):
        live_generate(_pkg(), provider="openai", model="gpt-4o")


def test_live_generate_http_error_does_not_look_like_success():
    def boom(
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout: float,
    ) -> tuple[int, bytes]:
        return 500, json.dumps({"error": {"message": "upstream down"}}).encode()

    with pytest.raises(LiveApiError, match="upstream down") as excinfo:
        live_generate(
            _pkg(),
            provider="openai",
            model="gpt-4o",
            api_key="sk-test",
            transport=boom,
        )
    assert excinfo.value.status == 500


def test_run_live_with_mock_persists_billable(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-live")
    root = tmp_path / "root"
    root.mkdir()
    # Conteúdo alinhado ao IR dry-run para passar o gate derived_artifact.
    dry = run(
        "openapi",
        dry_run=True,
        inputs_dir=FIXTURES / "happy_path",
        output_root=root / "dry",
        no_split=True,
    )
    assert dry["status"] == "completed"
    artifact_text = Path(dry["output"]).read_text(encoding="utf-8")
    calls: list[str] = []

    def transport(
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout: float,
    ) -> tuple[int, bytes]:
        calls.append(url)
        return _openai_transport(artifact_text)(method, url, headers, body, timeout)

    monkeypatch.setattr("src.reason.default_transport", transport)
    result = run(
        "openapi",
        dry_run=False,
        inputs_dir=FIXTURES / "happy_path",
        output_root=root / "live",
        no_split=True,
    )
    assert result["status"] == "completed"
    assert calls, "esperava chamada HTTP mockada"
    usage = result.get("token_usage") or {}
    assert usage.get("billable") == 120
    assert usage.get("cache_hit") == 0.1
    assert "cost_usd" in usage
    run_dir = Path(result["run_dir"])
    pkgs = list(run_dir.rglob("llm_package_openapi.json"))
    assert pkgs
    meta = json.loads(pkgs[0].read_text(encoding="utf-8"))["meta"]
    assert meta["token_usage"]["billable"] == 120
    assert meta["live"]["provider"] == "openai"
    out = Path(result["output"])
    assert out.is_file()
    assert out.read_text(encoding="utf-8").strip() == artifact_text.strip()
    assert usage.get("billable") is not None


def test_run_live_api_failure_does_not_corrupt_run(tmp_path: Path, monkeypatch):
    from src.runtime import StageError

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-live")
    root = tmp_path / "root"
    root.mkdir()

    def boom(
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout: float,
    ) -> tuple[int, bytes]:
        return 503, json.dumps({"error": {"message": "unavailable"}}).encode()

    monkeypatch.setattr("src.reason.default_transport", boom)
    with pytest.raises(StageError, match="unavailable|--live falhou"):
        run(
            "openapi",
            dry_run=False,
            inputs_dir=FIXTURES / "happy_path",
            output_root=root,
            no_split=True,
            run_id="livefail01",
        )
    run_dir = root / "runs" / "livefail01"
    assert run_dir.is_dir()
    # Falha no reason: pacote live deste tipo não deve ter sido commitado
    live_pkgs = list(run_dir.rglob("llm_package_openapi.json"))
    assert live_pkgs == []
    # Manifesto permanece legível (storage íntegro)
    manifest = run_dir / "manifest.json"
    assert manifest.is_file()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data.get("status") == "failed"
    artifacts = (
        list((run_dir / "artifacts").rglob("openapi*"))
        if (run_dir / "artifacts").is_dir()
        else []
    )
    assert artifacts == []


def test_dry_run_remains_default_without_api(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    called = {"n": 0}

    def transport(*_a: Any, **_k: Any) -> tuple[int, bytes]:
        called["n"] += 1
        return 200, b"{}"

    monkeypatch.setattr("src.reason.default_transport", transport)
    result = run(
        "openapi",
        dry_run=True,
        inputs_dir=FIXTURES / "happy_path",
        output_root=tmp_path / "root",
        no_split=True,
    )
    assert result["status"] == "completed"
    assert called["n"] == 0
    usage = result.get("token_usage") or {}
    assert usage.get("billable") is None
