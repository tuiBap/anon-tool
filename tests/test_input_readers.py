from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from anon_tool.cli import _read_input, _resolve_input_type


def test_resolves_supported_input_types() -> None:
    assert _resolve_input_type(Path("case.pdf"), "auto") == "pdf"
    assert _resolve_input_type(Path("case.txt"), "auto") == "txt"
    assert _resolve_input_type(Path("case.docx"), "auto") == "docx"


def test_rejects_unsupported_input_type() -> None:
    with pytest.raises(ValueError, match="Unable to infer input type"):
        _resolve_input_type(Path("case.doc"), "auto")


@pytest.mark.skipif(importlib.util.find_spec("docx") is None, reason="python-docx not installed")
def test_reads_docx_lines(tmp_path: Path) -> None:
    from docx import Document

    input_path = tmp_path / "case.docx"
    document = Document()
    document.add_paragraph("Created By David Bush")
    document.add_paragraph("Phone: 847-267-9330")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Case"
    table.cell(0, 1).text = "12345678"
    document.save(input_path)

    lines = _read_input(input_path, "docx")

    assert [line.text for line in lines] == [
        "Created By David Bush",
        "Phone: 847-267-9330",
        "Case | 12345678",
    ]
