"""Prefácio operacional: índice de salto, DAG e lookup sem Grep."""
from __future__ import annotations

from pathlib import Path

from src.doc_preface import (
    PREFACE_END,
    PREFACE_START,
    apply_to_file,
    build_document,
    lookup,
    neighborhood,
    strip_preface,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "doc_preface" / "sample.md"


def test_parse_tickets_and_frontier(tmp_path: Path):
    text = FIXTURE.read_text(encoding="utf-8")
    _, index = build_document(text, tmp_path / "sample.md")
    assert set(index.tickets) == {
        "08-ir-openapi-mermaid",
        "18-safe-run-storage",
        "19-contextual-provenance",
        "22-code-evidence-spec",
    }
    assert index.tickets["19-contextual-provenance"].blocked_by == ["18-safe-run-storage"]
    assert index.tickets["22-code-evidence-spec"].blocked_by == ["19-contextual-provenance"]
    assert "18-safe-run-storage" in index.frontier
    assert "08-ir-openapi-mermaid" in index.frontier
    assert "19-contextual-provenance" not in index.frontier
    assert index.adjacency["18-safe-run-storage"] == ["19-contextual-provenance"]
    t22 = index.tickets["22-code-evidence-spec"]
    assert "gaps" in t22.text.lower()
    assert "code_evidence" in t22.text
    assert lookup(index, "gaps")[0]["id"] == "22-code-evidence-spec"


def test_lookup_prefers_ticket_id_and_gaps(tmp_path: Path):
    text = FIXTURE.read_text(encoding="utf-8")
    _, index = build_document(text, tmp_path / "sample.md")
    by_id = lookup(index, "22-code-evidence-spec")
    assert by_id and by_id[0]["id"] == "22-code-evidence-spec"
    gaps = lookup(index, "história gaps repositório")
    ids = [h["id"] for h in gaps]
    assert "22-code-evidence-spec" in ids


def test_apply_is_idempotent_and_line_numbers_work(tmp_path: Path):
    target = tmp_path / "sample.md"
    target.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    index1, side = apply_to_file(target)
    first = target.read_text(encoding="utf-8")
    assert PREFACE_START in first and PREFACE_END in first
    assert side.exists()
    assert index1.preface_lines and index1.preface_lines[0] < 10

    sec = index1.tickets["22-code-evidence-spec"]
    lines = first.splitlines()
    heading = lines[sec.start_line - 1]
    assert "22-code-evidence-spec" in heading

    index2, _ = apply_to_file(target)
    second = target.read_text(encoding="utf-8")
    assert strip_preface(first) == strip_preface(second)
    assert index2.tickets["22-code-evidence-spec"].start_line == sec.start_line
    assert first.count(PREFACE_START) == 1


def test_neighborhood_loads_blockers_and_dependents(tmp_path: Path):
    text = FIXTURE.read_text(encoding="utf-8")
    _, index = build_document(text, tmp_path / "sample.md")
    nb = neighborhood(index, "19-contextual-provenance")
    ids = {h["id"] for h in nb["read"]}
    assert ids == {
        "19-contextual-provenance",
        "18-safe-run-storage",
        "22-code-evidence-spec",
    }


def test_glossary_extracts_ir_and_prd(tmp_path: Path):
    text = FIXTURE.read_text(encoding="utf-8")
    _, index = build_document(text, tmp_path / "sample.md")
    folded = {t.lower() for t in index.glossary}
    assert "ir" in folded
    assert "prd" in folded
