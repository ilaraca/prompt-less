"""Tokenizer oficial pluggable, fallback heurístico e budget nos limites."""
from __future__ import annotations

from typing import Any

import pytest

from src.context_builder import build_context
from src.reason import build_llm_package
from src.tokenizer import (
    TokenEstimate,
    clear_strategies,
    count_tokens,
    estimate,
    heuristic_count,
    observe_billable,
    provider_for_model,
    register_strategy,
    using_tokenizer,
)


def _rag(text: str = "consolidado curto") -> dict[str, Any]:
    return {
        "consolidated": text,
        "est_tokens_raw": 8,
        "est_tokens_compressed": 4,
        "documents": {"docs": [], "reduction_pct": 0},
    }


class _FakeOfficial:
    provider = "fake"

    def estimate(self, text: str, model: str | None = None) -> TokenEstimate:
        return TokenEstimate(
            tokens=42,
            method="official",
            provider="fake",
            model=model or "fake-1",
            encoding="fake-enc",
        )


def test_pluggable_strategy_per_provider():
    register_strategy("fake", _FakeOfficial())
    try:
        est = estimate("qualquer", provider="fake", model="fake-1")
        assert est.tokens == 42
        assert est.method == "official"
        assert est.provider == "fake"
        assert est.encoding == "fake-enc"
    finally:
        clear_strategies()


def test_provider_for_model_mapping():
    assert provider_for_model("gpt-4o") == "openai"
    assert provider_for_model("claude-sonnet") == "anthropic"
    assert provider_for_model("gemini-flash") == "google"


def test_openai_official_when_tiktoken_present():
    pytest.importorskip("tiktoken")
    est = estimate("hello world", provider="openai", model="gpt-4o")
    assert est.method == "official"
    assert est.tokens > 0
    assert est.encoding
    assert est.fallback_reason is None
    assert "não é contagem exata" not in est.label


def test_fail_open_heuristic_when_tiktoken_missing(monkeypatch):
    import src.tokenizer as tok

    monkeypatch.setattr(tok, "_load_tiktoken", lambda: None)
    est = tok.estimate("hello world", provider="openai", model="gpt-4o")
    assert est.method == "heuristic"
    assert est.fallback_reason == "tiktoken_unavailable"
    assert est.tokens == heuristic_count("hello world")
    assert "não é contagem exata" in est.label
    blob = str(est.to_dict())
    assert "method" in blob
    assert "'method': 'official'" not in blob and '"method": "official"' not in blob


def test_anthropic_is_heuristic_fallback_not_exact():
    est = estimate("olá mundo " * 20, provider="anthropic", model="claude-sonnet")
    assert est.method == "heuristic"
    assert est.fallback_reason == "no_local_official_tokenizer"
    assert "não é contagem exata" in est.label
    assert est.tokens == heuristic_count("olá mundo " * 20)


def test_observe_billable_records_estimated_vs_billable_delta():
    pytest.importorskip("tiktoken")
    est = estimate("prompt de teste", provider="openai", model="gpt-4o")
    observed = observe_billable(est, billable_tokens=est.tokens + 11)
    assert observed["estimated"] == est.tokens
    assert observed["billable"] == est.tokens + 11
    assert observed["delta"] == 11
    assert observed["method"] == est.method
    usage = est.to_telemetry(billable=est.tokens + 11)
    assert usage["delta"] == 11
    assert usage["billable"] == est.tokens + 11


def test_heuristic_observe_billable_still_not_exact():
    est = estimate("abc", provider="anthropic", model="claude-haiku")
    observed = observe_billable(est, billable_tokens=99)
    assert observed["method"] == "heuristic"
    assert "não é contagem exata" in observed["label"]
    assert observed["delta"] == 99 - est.tokens


def test_budget_keeps_template_under_limit():
    template = "template curto"
    with using_tokenizer("anthropic", "claude-sonnet"):
        ctx = build_context(
            "historia",
            state={"k": 1},
            rag=_rag(),
            template=template,
            budget_tokens=2000,
        )
    assert ctx["dynamic"]["template"] == template
    assert ctx["est_tokens"] <= 2000
    assert ctx["est_tokens"] > 0
    assert ctx["est_tokens_method"] == "heuristic"
    assert ctx["token_usage"]["method"] == "heuristic"
    assert ctx["token_usage"]["billable"] is None


def test_budget_truncates_when_over_limit():
    huge = "palavra " * 4000
    with using_tokenizer("anthropic", "claude-sonnet"):
        ctx = build_context(
            "historia",
            state={"k": 1},
            rag=_rag("x" * 2000),
            template=huge,
            budget_tokens=80,
        )
    assert "truncado" in ctx["dynamic"]["template"]
    assert len(ctx["dynamic"]["template"]) < len(huge)
    assert ctx["est_tokens_method"] in {"official", "heuristic"}


def test_budget_allows_exact_limit(monkeypatch):
    import src.context_builder as cb

    template = "TEMPLATE_OK"

    def fake_estimate(text: str, **kwargs: Any) -> TokenEstimate:
        return TokenEstimate(
            tokens=100,
            method="official",
            provider="openai",
            model="gpt-4o",
            encoding="o200k_base",
        )

    monkeypatch.setattr(cb, "estimate", fake_estimate)
    ctx = cb.build_context(
        "historia",
        state={},
        rag=_rag(),
        template=template,
        budget_tokens=100,
    )
    assert ctx["est_tokens"] == 100
    assert ctx["est_tokens_method"] == "official"
    assert ctx["dynamic"]["template"] == template
    assert "truncado" not in ctx["dynamic"]["template"]


def test_budget_clips_when_one_over_limit(monkeypatch):
    import src.context_builder as cb

    template = "T" * 500
    calls = {"n": 0}

    def fake_estimate(text: str, **kwargs: Any) -> TokenEstimate:
        calls["n"] += 1
        tokens = 101 if calls["n"] == 1 else 90
        return TokenEstimate(
            tokens=tokens,
            method="heuristic",
            provider="anthropic",
            model="claude-sonnet",
            fallback_reason="no_local_official_tokenizer",
        )

    monkeypatch.setattr(cb, "estimate", fake_estimate)
    ctx = cb.build_context(
        "historia",
        state={},
        rag=_rag(),
        template=template,
        budget_tokens=100,
    )
    assert "truncado" in ctx["dynamic"]["template"]
    assert ctx["est_tokens"] == 90
    assert ctx["est_tokens"] <= 100
    assert ctx["est_tokens_method"] == "heuristic"


def test_llm_package_persists_method_and_usage_hook():
    with using_tokenizer("anthropic", "claude-sonnet"):
        ctx = build_context("prd", state={"a": 1}, rag=_rag(), template="t", budget_tokens=2000)
    pkg = build_llm_package(ctx)
    meta = pkg["meta"]
    assert meta["est_tokens"] == ctx["est_tokens"]
    assert meta["est_tokens_method"] == "heuristic"
    assert meta["token_usage"]["method"] == "heuristic"
    assert meta["token_usage"]["billable"] is None
    assert meta["token_usage"]["delta"] is None
    assert "não é contagem exata" in meta["token_usage"]["label"]


def test_run_result_records_method(run_case):
    result, _ = run_case("happy_path")
    assert result.get("est_tokens", 0) > 0 or (
        result.get("by_context") and any(c.get("est_tokens") for c in result["by_context"])
    )
    methods = []
    if result.get("est_tokens_method"):
        methods.append(result["est_tokens_method"])
    for ctx in result.get("by_context") or []:
        if ctx.get("est_tokens_method"):
            methods.append(ctx["est_tokens_method"])
    assert methods, "pipeline deve registrar est_tokens_method"
    assert set(methods) <= {"official", "heuristic"}
    usage = result.get("token_usage") or (result.get("by_context") or [{}])[0].get("token_usage")
    assert usage
    assert usage["method"] in {"official", "heuristic"}
    assert "billable" in usage
    if usage["method"] == "heuristic":
        assert "não é contagem exata" in usage["label"]


def test_count_tokens_matches_estimate():
    text = "abc123"
    with using_tokenizer("anthropic", "claude-haiku"):
        assert count_tokens(text) == estimate(text).tokens == heuristic_count(text)
