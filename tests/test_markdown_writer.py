from __future__ import annotations

import pytest

from anon_tool.output.markdown_writer import render_markdown, validate_markdown
from anon_tool.types import InputLine


def _lines(*texts: str, page: int = 1) -> list[InputLine]:
    return [InputLine(page=page, line_no=index, text=text) for index, text in enumerate(texts, start=1)]


def test_renders_structured_salesforce_case_markdown() -> None:
    lines = _lines(
        "Print this page",
        "Case Number: 00012345",
        "Status: Open",
        "Product Version: 24.2.1",
        "Symptoms",
        "Service fails during startup",
        "Error message remains [REDACTED_HOSTNAME]",
        "Troubleshooting Steps",
        "Restarted the service",
        "Collected diagnostics",
        "2026-06-09T10:15:31Z ERROR Connection refused: port 8443",
        "at com.example.Service.start(Service.java:42)",
        "1 / 1",
    )

    markdown = render_markdown(lines)

    assert markdown.startswith("# Sanitized Case Record\n\n")
    assert "| Case Number | 00012345 |" in markdown
    assert "| Product Version | 24.2.1 |" in markdown
    assert "## Symptoms\n\n- Service fails during startup" in markdown
    assert "- Error message remains [REDACTED_HOSTNAME]" in markdown
    assert "## Troubleshooting\n\n- Restarted the service" in markdown
    assert "```text\n2026-06-09T10:15:31Z ERROR Connection refused: port 8443" in markdown
    assert "Print this page" not in markdown
    assert "1 / 1" not in markdown
    validate_markdown(markdown)


def test_renders_email_thread_with_metadata_and_body() -> None:
    lines = _lines(
        "From: [REDACTED_PERSON] <[REDACTED_EMAIL]>",
        "To: Support <[REDACTED_EMAIL]>",
        "Sent: June 9, 2026 10:22 AM",
        "Subject: Re: Case 00012345 startup failure",
        "The issue still occurs on version 24.2.1.",
        "Exact error: Connection refused.",
    )

    markdown = render_markdown(lines)

    assert "## Email Thread" in markdown
    assert "### Message 1" in markdown
    assert "- **Date:** June 9, 2026 10:22 AM" in markdown
    assert "- **From:** [REDACTED_PERSON] <[REDACTED_EMAIL]>" in markdown
    assert "- **Subject:** Re: Case 00012345 startup failure" in markdown
    assert "**Body**\n\nThe issue still occurs on version 24.2.1." in markdown


def test_escapes_raw_markdown_markers_in_email_body() -> None:
    markdown = render_markdown(
        _lines(
            "From: [REDACTED_PERSON] <[REDACTED_EMAIL]>",
            "To: Support <[REDACTED_EMAIL]>",
            "Subject: Re: Case 00012345 startup failure",
            "Thanks,",
            "--",
            "[REDACTED_PERSON]",
        )
    )

    assert "\\--" in markdown
    validate_markdown(markdown)


def test_removes_repeated_boundary_headers_but_keeps_case_numbers_and_placeholders() -> None:
    lines = [
        *_lines("Support Portal", "Case Number: 00012345", "[REDACTED_COMPANY]", page=1),
        *_lines("Support Portal", "Case Number: 00012345", "[REDACTED_COMPANY]", page=2),
    ]

    markdown = render_markdown(lines)

    assert "Support Portal" not in markdown
    assert markdown.count("00012345") == 2
    assert markdown.count("[REDACTED_COMPANY]") == 2
    assert "### Source Page 1" in markdown
    assert "### Source Page 2" in markdown


def test_validation_rejects_heading_jump_and_unclosed_fence() -> None:
    with pytest.raises(ValueError, match="heading level jumps"):
        validate_markdown("# Title\n\n### Page\n")
    with pytest.raises(ValueError, match="unclosed fenced"):
        validate_markdown("# Title\n\n## Logs\n\n```text\nERROR\n")


def test_escapes_raw_markdown_markers_in_extracted_prose() -> None:
    markdown = render_markdown(_lines("-not a list", "+not a list", "*not a list"))

    assert "\\-not a list" in markdown
    assert "\\+not a list" in markdown
    assert "\\*not a list" in markdown
    validate_markdown(markdown)


def test_escapes_raw_heading_markers_in_extracted_prose() -> None:
    markdown = render_markdown(
        _lines(
            "# Please confirm the installation directory",
            "## Directory inventory",
        )
    )

    assert "\\# Please confirm the installation directory" in markdown
    assert "\\## Directory inventory" in markdown
    assert markdown.count("# Sanitized Case Record") == 1
    validate_markdown(markdown)
