from __future__ import annotations

from pathlib import Path

from anon_tool.types import InputLine


def write_sanitized_pdf(path: Path, lines: list[InputLine]) -> None:
    try:
        from reportlab.lib.pagesizes import LETTER
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency 'reportlab'. Install project dependencies before writing PDF output."
        ) from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=LETTER)
    width, height = LETTER
    x_margin = 40
    y = height - 40
    line_height = 12

    last_page = None
    for entry in lines:
        if last_page is None:
            last_page = entry.page
            c.setFont("Courier", 10)
            c.drawString(x_margin, y, f"Sanitized Output - Source Page {entry.page}")
            y -= line_height * 2
        elif entry.page != last_page:
            c.showPage()
            c.setFont("Courier", 10)
            y = height - 40
            c.drawString(x_margin, y, f"Sanitized Output - Source Page {entry.page}")
            y -= line_height * 2
            last_page = entry.page

        if y <= 40:
            c.showPage()
            c.setFont("Courier", 10)
            y = height - 40

        text = entry.text
        for chunk in _wrap_line(text, max_chars=95):
            c.drawString(x_margin, y, chunk)
            y -= line_height
            if y <= 40:
                c.showPage()
                c.setFont("Courier", 10)
                y = height - 40

    c.save()


def _wrap_line(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        split = remaining.rfind(" ", 0, max_chars)
        if split <= 0:
            split = max_chars
        chunks.append(remaining[:split].rstrip())
        remaining = remaining[split:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks

