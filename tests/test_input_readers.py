from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from anon_tool.cli import _read_input, _resolve_input_type, _write_output
from anon_tool.types import InputLine


def test_resolves_supported_input_types() -> None:
    assert _resolve_input_type(Path("case.pdf"), "auto") == "pdf"
    assert _resolve_input_type(Path("case.txt"), "auto") == "txt"
    assert _resolve_input_type(Path("case.docx"), "auto") == "docx"


def test_rejects_unsupported_input_type() -> None:
    with pytest.raises(ValueError, match="Unable to infer input type"):
        _resolve_input_type(Path("case.doc"), "auto")


def test_writes_supported_output_formats(tmp_path: Path) -> None:
    lines = [InputLine(page=1, line_no=1, text="redacted")]
    markdown_path = tmp_path / "case.md"
    text_path = tmp_path / "case.txt"
    pdf_path = tmp_path / "case.pdf"

    _write_output(markdown_path, lines, "markdown")
    _write_output(text_path, lines, "text")
    _write_output(pdf_path, lines, "pdf")

    assert markdown_path.read_text(encoding="utf-8") == (
        "# Sanitized Case Record\n\n## Case Content\n\n### Source Page 1\n\nredacted\n"
    )
    assert text_path.read_text(encoding="utf-8") == "=== Source Page 1 ===\nredacted\n"
    assert pdf_path.read_bytes().startswith(b"%PDF")


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


@pytest.mark.parametrize("suffix", ["md", "eml", "MD", "EML"])
def test_resolves_new_input_types(suffix: str) -> None:
    assert _resolve_input_type(Path(f"case.{suffix}"), "auto") == suffix.lower()


def test_reads_markdown_without_losing_syntax(tmp_path: Path) -> None:
    path = tmp_path / "case.md"
    path.write_text("# Case\n\n- **Contact**: person@example.com\n", encoding="utf-8")
    lines = _read_input(path, "md")
    assert [line.text for line in lines] == ["# Case", "", "- **Contact**: person@example.com"]
    assert [line.line_no for line in lines] == [1, 2, 3]


def test_reads_decoded_email_and_skips_attachments(tmp_path: Path) -> None:
    from email.message import EmailMessage

    message = EmailMessage()
    message["From"] = "Jos? <person@example.com>"
    message["Subject"] = "R?sum?"
    message.set_content("Contact caf?@example.com", cte="base64")
    message.add_alternative("<p>Duplicate alternative</p>", subtype="html")
    message.add_attachment(b"attachment secret", maintype="application", subtype="octet-stream", filename="secret.bin")
    path = tmp_path / "case.eml"
    path.write_bytes(message.as_bytes())
    lines = _read_input(path, "eml")
    text = "\n".join(line.text for line in lines)
    assert "Jos?" in text
    assert "Subject: R?sum?" in text
    assert "Contact caf?@example.com" in text
    assert "Duplicate alternative" not in text
    assert "attachment secret" not in text
    assert [line.line_no for line in lines] == list(range(1, len(lines) + 1))


def test_reads_html_only_email(tmp_path: Path) -> None:
    from email.message import EmailMessage

    message = EmailMessage()
    message.set_content("<style>hidden</style><p>A &amp; B</p><p>person@example.com</p>", subtype="html", charset="iso-8859-1", cte="quoted-printable")
    path = tmp_path / "html.eml"
    path.write_bytes(message.as_bytes())
    text = "\n".join(line.text for line in _read_input(path, "eml"))
    assert "A & B" in text
    assert "person@example.com" in text
    assert "<p>" not in text
    assert "hidden" not in text
