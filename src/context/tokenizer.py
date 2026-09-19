"""Tokenizer pluggable por provider — oficial quando disponível, heurística senão.

Contagem pré-chamada NÃO é o billable do vendor. O fallback chars÷4 nunca é
apresentado como contagem exata. O hook `observe_billable` persiste a diferença
estimado vs cobrado para o modo live (09).
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Literal, Protocol

HEURISTIC_CHARS_PER_TOKEN = 4
Method = Literal["official", "heuristic"]

_MODEL_ENCODING_PREFIXES: tuple[tuple[str, str], ...] = (
    ("gpt-4o", "o200k_base"),
    ("gpt-4.1", "o200k_base"),
    ("gpt-4", "cl100k_base"),
    ("gpt-3.5", "cl100k_base"),
    ("o1", "o200k_base"),
    ("o3", "o200k_base"),
    ("o4", "o200k_base"),
)


@dataclass(frozen=True)
class TokenizerSettings:
    provider: str
    model: str


@dataclass(frozen=True)
class TokenEstimate:
    tokens: int
    method: Method
    provider: str
    model: str
    encoding: str | None = None
    fallback_reason: str | None = None

    @property
    def label(self) -> str:
        if self.method == "official":
            enc = self.encoding or self.provider
            return (
                f"tokenizer oficial ({enc}) — pré-chamada; "
                "billable do vendor pode divergir"
            )
        reason = f"; motivo: {self.fallback_reason}" if self.fallback_reason else ""
        return f"heurística chars÷4 (fallback; não é contagem exata{reason})"

    def to_dict(self) -> dict[str, Any]:
        return {
            "tokens": self.tokens,
            "method": self.method,
            "provider": self.provider,
            "model": self.model,
            "encoding": self.encoding,
            "fallback_reason": self.fallback_reason,
            "label": self.label,
        }

    def to_telemetry(self, billable: int | None = None) -> dict[str, Any]:
        payload = self.to_dict()
        payload["estimated"] = self.tokens
        if billable is None:
            payload["billable"] = None
            payload["delta"] = None
            payload["delta_pct"] = None
        else:
            payload.update(observe_billable(self, billable))
        return payload


class TokenizerStrategy(Protocol):
    provider: str

    def estimate(self, text: str, model: str | None = None) -> TokenEstimate: ...


_settings: TokenizerSettings | None = None
_strategies: dict[str, TokenizerStrategy] = {}


def chars_for_token_budget(tokens: int) -> int:
    """Clip em chars a partir do teto em tokens (inverso da heurística)."""
    return max(0, int(tokens) * HEURISTIC_CHARS_PER_TOKEN)


def heuristic_count(text: str) -> int:
    if not text:
        return 0
    return max(0, len(text) // HEURISTIC_CHARS_PER_TOKEN)


def provider_for_model(model: str | None) -> str:
    m = (model or "").strip().lower()
    if not m:
        return "unknown"
    if m.startswith(("gpt-", "o1", "o3", "o4")):
        return "openai"
    if "claude" in m:
        return "anthropic"
    if "gemini" in m:
        return "google"
    return "unknown"


def _heuristic(
    text: str,
    *,
    provider: str,
    model: str,
    reason: str,
) -> TokenEstimate:
    return TokenEstimate(
        tokens=heuristic_count(text),
        method="heuristic",
        provider=provider,
        model=model,
        encoding=None,
        fallback_reason=reason,
    )


def _load_tiktoken() -> Any | None:
    try:
        import tiktoken  # type: ignore
    except ImportError:
        return None
    return tiktoken


def _encoding_name_for(model: str) -> str | None:
    m = (model or "").lower()
    for prefix, name in _MODEL_ENCODING_PREFIXES:
        if m.startswith(prefix):
            return name
    return None


def _encoding_for(tiktoken: Any, model: str) -> Any | None:
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        pass
    except Exception:
        pass
    name = _encoding_name_for(model)
    if not name:
        return None
    try:
        return tiktoken.get_encoding(name)
    except Exception:
        return None


class OpenAIStrategy:
    provider = "openai"

    def estimate(self, text: str, model: str | None = None) -> TokenEstimate:
        text = text or ""
        model = model or "gpt-4o"
        tiktoken = _load_tiktoken()
        if tiktoken is None:
            return _heuristic(text, provider=self.provider, model=model, reason="tiktoken_unavailable")
        enc = _encoding_for(tiktoken, model)
        if enc is None:
            return _heuristic(text, provider=self.provider, model=model, reason="encoding_unavailable")
        try:
            n = len(enc.encode(text))
        except Exception:
            return _heuristic(text, provider=self.provider, model=model, reason="encode_failed")
        return TokenEstimate(
            tokens=n,
            method="official",
            provider=self.provider,
            model=model,
            encoding=getattr(enc, "name", None),
            fallback_reason=None,
        )


class FallbackStrategy:
    """Provider sem tokenizer local oficial — fail-open heurístico."""

    def __init__(self, provider: str, reason: str = "no_local_official_tokenizer") -> None:
        self.provider = provider
        self.reason = reason

    def estimate(self, text: str, model: str | None = None) -> TokenEstimate:
        return _heuristic(
            text or "",
            provider=self.provider,
            model=model or "",
            reason=self.reason,
        )


def _builtins() -> dict[str, TokenizerStrategy]:
    return {
        "openai": OpenAIStrategy(),
        "anthropic": FallbackStrategy("anthropic"),
        "google": FallbackStrategy("google"),
    }


def register_strategy(provider: str, strategy: TokenizerStrategy) -> None:
    _strategies[(provider or "").strip().lower()] = strategy


def clear_strategies() -> None:
    _strategies.clear()


def get_strategy(provider: str | None) -> TokenizerStrategy:
    key = (provider or "").strip().lower()
    if key in _strategies:
        return _strategies[key]
    builtins = _builtins()
    if key in builtins:
        return builtins[key]
    return FallbackStrategy(key or "unknown", reason="unknown_provider")


def settings_from_cfg(cfg: dict[str, Any] | None) -> TokenizerSettings:
    models = (cfg or {}).get("models") or {}
    model = str(models.get("name") or models.get("reason_model") or "gpt-4o")
    provider = str(models.get("provider") or provider_for_model(model) or "openai")
    return TokenizerSettings(provider=provider, model=model)


def configure(
    *,
    provider: str | None = None,
    model: str | None = None,
    cfg: dict[str, Any] | None = None,
) -> TokenizerSettings:
    global _settings
    if cfg is not None and provider is None and model is None:
        _settings = settings_from_cfg(cfg)
        return _settings
    resolved_model = model or (settings_from_cfg(cfg).model if cfg else "gpt-4o")
    resolved_provider = provider or provider_for_model(resolved_model)
    _settings = TokenizerSettings(provider=resolved_provider, model=resolved_model)
    return _settings


def configure_from_cfg(cfg: dict[str, Any] | None) -> TokenizerSettings:
    return configure(cfg=cfg)


def current_settings() -> TokenizerSettings:
    if _settings is not None:
        return _settings
    return TokenizerSettings(provider="openai", model="gpt-4o")


@contextmanager
def using_tokenizer(
    provider: str,
    model: str,
) -> Iterator[TokenizerSettings]:
    global _settings
    prev = _settings
    try:
        yield configure(provider=provider, model=model)
    finally:
        _settings = prev


def estimate(
    text: str,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> TokenEstimate:
    current = current_settings()
    resolved_model = model or current.model
    resolved_provider = provider or (
        current.provider if model is None else provider_for_model(resolved_model)
    )
    return get_strategy(resolved_provider).estimate(text or "", model=resolved_model)


def count_tokens(
    text: str,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> int:
    return estimate(text, provider=provider, model=model).tokens


def est_raw(text: str) -> int:
    """Contagem para texto ingerido: vazio → 0; não-vazio → no mínimo 1."""
    if not text:
        return 0
    return max(1, count_tokens(text))


def observe_billable(estimate_: TokenEstimate, billable_tokens: int) -> dict[str, Any]:
    """Hook para 09-live-llm: persiste estimado vs tokens cobrados pelo vendor.

    Não implementa a chamada live — só o contrato de comparação.
    """
    billable = int(billable_tokens)
    delta = billable - estimate_.tokens
    denom = max(abs(estimate_.tokens), 1)
    return {
        "estimated": estimate_.tokens,
        "method": estimate_.method,
        "billable": billable,
        "delta": delta,
        "delta_pct": round(100.0 * delta / denom, 2),
        "provider": estimate_.provider,
        "model": estimate_.model,
        "encoding": estimate_.encoding,
        "fallback_reason": estimate_.fallback_reason,
        "label": estimate_.label,
    }
