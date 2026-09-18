"""Referência a trecho de fonte documental."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class SourceRef:
    document: str
    section: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    content_hash: str | None = None
    selected_lines: tuple[int, ...] | None = None
    locator: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for key, value in asdict(self).items():
            if value is None or value == () or value == []:
                continue
            if key == "selected_lines":
                data[key] = list(value)
            else:
                data[key] = value
        return data
