from __future__ import annotations

from pathlib import Path

from anon_tool.types import InputLine


def read_pdf_lines(path: Path) -> list[InputLine]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency 'pypdf'. Install project dependencies before running PDF input."
        ) from exc

    reader = PdfReader(str(path))
    results: list[InputLine] = []
    for page_idx, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        for line_idx, line in enumerate(text.splitlines(), start=1):
            results.append(InputLine(page=page_idx, line_no=line_idx, text=line))
    return results

