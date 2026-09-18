"""Scan de inputs não confiáveis: secrets, PII heurística, prompt injection.

Achados nunca são engolidos: o relatório lista cada um. Secrets, PII de alta
confiança e instruções suspeitas bloqueiam a montagem do pacote LLM
(fail-closed). PII heurística de baixa confiança fica só no relatório.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

# --------------------------------------------------------------------------- secrets

_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    (
        "private_key",
        re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----"),
    ),
    ("github_token", re.compile(r"\b(?:ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    (
        "connection_string",
        re.compile(
            r"\b(?:postgres|mysql|mongodb|redis|amqp)://[^\s/'\"@]+:[^\s/'\"@]+@",
            re.IGNORECASE,
        ),
    ),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
    (
        "assigned_secret",
        re.compile(
            r"(?:api[_-]?key|secret[_-]?key|access[_-]?token|password)\s*[:=]\s*"
            r"['\"]?[A-Za-z0-9/+_\-]{16,}",
            re.IGNORECASE,
        ),
    ),
]

# --------------------------------------------------------------------------- PII

_CPF_RE = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
_CARD_RE = re.compile(r"\b(?:\d{4}[-\s]){3}\d{4}\b")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_BR_RE = re.compile(r"\b(?:\+55\s*)?(?:\(?\d{2}\)?\s*)?9?\d{4}[-\s]?\d{4}\b")
_EXAMPLE_EMAIL_DOMAINS = ("example.com", "example.org", "example.net", "test.local")

# --------------------------------------------------------------------------- injection

_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "ignore_previous",
        re.compile(
            r"ignore(?:\s+all)?\s+(?:the\s+)?(?:previous|prior|above)\s+instructions",
            re.IGNORECASE,
        ),
    ),
    (
        "ignore_previous_pt",
        re.compile(
            r"ignore(?:\s+todas)?\s+as\s+instru[cç][oõ]es\s+anteriores",
            re.IGNORECASE,
        ),
    ),
    (
        "disregard_system",
        re.compile(r"disregard\s+(?:the\s+)?(?:system\s+)?prompt", re.IGNORECASE),
    ),
    ("jailbreak", re.compile(r"\b(?:jailbreak|dan\s+mode|you are now)\b", re.IGNORECASE)),
    (
        "leak_env",
        re.compile(
            r"(?:publique|revele|dump(?:ar)?)\s+(?:todas\s+)?(?:as\s+)?"
            r"(?:vari[aá]veis\s+de\s+ambiente|env(?:ironment)?\s+vars?|system\s+prompt)",
            re.IGNORECASE,
        ),
    ),
    (
        "override_policy",
        re.compile(
            r"(?:override|bypass)\s+(?:the\s+)?(?:safety|policy|guardrail)",
            re.IGNORECASE,
        ),
    ),
]


@dataclass
class ScanFinding:
    category: str  # secret | pii | injection
    code: str
    severity: str  # error | warning
    message: str
    source: str
    excerpt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScanReport:
    findings: list[ScanFinding] = field(default_factory=list)

    @property
    def blocking(self) -> list[ScanFinding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def blocks(self) -> bool:
        return bool(self.blocking)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "blocked" if self.blocks else "passed",
            "findings_count": len(self.findings),
            "blocking_count": len(self.blocking),
            "findings": [f.to_dict() for f in self.findings],
        }


class InputScanBlocked(Exception):
    """Pacote LLM recusado: input com secret/PII/injection de severidade error."""

    def __init__(self, report: ScanReport):
        self.report = report
        super().__init__(
            f"input scan blocked: {len(report.blocking)} achado(s) fail-closed"
        )


def _excerpt(text: str, match: re.Match[str], radius: int = 24) -> str:
    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    snippet = text[start:end].replace("\n", " ")
    return snippet[:80]


def _luhn_ok(digits: str) -> bool:
    total = 0
    alt = False
    for ch in reversed(digits):
        n = ord(ch) - 48
        if alt:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        alt = not alt
    return total % 10 == 0


def scan_text(text: str, *, source: str) -> list[ScanFinding]:
    findings: list[ScanFinding] = []
    if not text:
        return findings

    for code, pat in _SECRET_PATTERNS:
        for m in pat.finditer(text):
            findings.append(
                ScanFinding(
                    category="secret",
                    code=f"SECRET_{code.upper()}",
                    severity="error",
                    message=f"segredo detectado ({code}) em {source}",
                    source=source,
                    excerpt=_excerpt(text, m),
                )
            )

    for m in _CPF_RE.finditer(text):
        findings.append(
            ScanFinding(
                category="pii",
                code="PII_CPF",
                severity="error",
                message=f"CPF com máscara detectado em {source}",
                source=source,
                excerpt=_excerpt(text, m),
            )
        )

    for m in _CARD_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if len(digits) == 16 and _luhn_ok(digits):
            findings.append(
                ScanFinding(
                    category="pii",
                    code="PII_CREDIT_CARD",
                    severity="error",
                    message=f"número de cartão (Luhn) detectado em {source}",
                    source=source,
                    excerpt=_excerpt(text, m),
                )
            )

    for m in _EMAIL_RE.finditer(text):
        email = m.group(0).lower()
        domain = email.rsplit("@", 1)[-1]
        if domain in _EXAMPLE_EMAIL_DOMAINS:
            continue
        findings.append(
            ScanFinding(
                category="pii",
                code="PII_EMAIL",
                severity="warning",
                message=f"e-mail heurístico em {source}",
                source=source,
                excerpt=_excerpt(text, m),
            )
        )

    for m in _PHONE_BR_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if len(digits) < 10:
            continue
        findings.append(
            ScanFinding(
                category="pii",
                code="PII_PHONE",
                severity="warning",
                message=f"telefone heurístico em {source}",
                source=source,
                excerpt=_excerpt(text, m),
            )
        )

    for code, pat in _INJECTION_PATTERNS:
        for m in pat.finditer(text):
            findings.append(
                ScanFinding(
                    category="injection",
                    code=f"INJECTION_{code.upper()}",
                    severity="error",
                    message=f"instrução suspeita ({code}) em {source}",
                    source=source,
                    excerpt=_excerpt(text, m),
                )
            )

    return findings


def scan_blobs(blobs: Iterable[tuple[str, str]]) -> ScanReport:
    findings: list[ScanFinding] = []
    for source, text in blobs:
        findings.extend(scan_text(text or "", source=str(source)))
    return ScanReport(findings=findings)


def collect_untrusted_blobs(
    payload: dict[str, Any] | None,
    slot: dict[str, Any] | None = None,
) -> list[tuple[str, str]]:
    """Junta documentos, YAML/JSON de negócio, RAG e payload dinâmico do pacote."""
    payload = payload or {}
    slot = slot or {}
    blobs: list[tuple[str, str]] = []

    raw = payload.get("raw") or {}
    slim = payload.get("slim") or slot.get("slim_ctx") or {}

    def _dump(value: Any) -> str:
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False)
        except TypeError:
            return str(value)

    for doc in raw.get("documents") or slim.get("documents") or []:
        if not isinstance(doc, dict):
            continue
        blobs.append((f"document:{doc.get('name') or 'unnamed'}", str(doc.get("text") or "")))

    for key in ("figma", "regras", "engenharia"):
        value = raw.get(key)
        if value is None:
            value = slim.get(key)
        if value:
            blobs.append((key, _dump(value)))

    rag = slot.get("rag") or {}
    if rag.get("consolidated"):
        blobs.append(("rag.consolidated", str(rag.get("consolidated") or "")))
    for claim in rag.get("claims") or []:
        if isinstance(claim, dict) and claim.get("text"):
            blobs.append((f"claim:{claim.get('id')}", str(claim.get("text"))))

    for tipo, pkg in (slot.get("context_by_tipo") or {}).items():
        if not isinstance(pkg, dict):
            continue
        blobs.append((f"llm_dynamic:{tipo}", _dump(pkg.get("dynamic") or {})))
        if pkg.get("system"):
            # system é confiável; não entra no scan de untrusted
            continue

    return blobs
