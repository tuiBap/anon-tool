"""Decode email headers and message text; attachments are not imported."""

from __future__ import annotations

from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
from pathlib import Path

from anon_tool.types import InputLine


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3"}:
            self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "div", "li", "tr", "h1", "h2", "h3"}:
            self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.chunks.append(data)


def read_eml_lines(path: Path) -> list[InputLine]:
    message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    text = "\n".join(f"{name}: {value}" for name, value in message.items())
    body = message.get_body(preferencelist=("plain", "html"))
    if body is not None:
        payload = body.get_payload(decode=True) or b""
        try:
            content = payload.decode(body.get_content_charset() or "utf-8", errors="replace")
        except LookupError:
            content = payload.decode("utf-8", errors="replace")
        if body.get_content_type() == "text/html":
            parser = _HTMLText()
            parser.feed(content)
            parser.close()
            content = "".join(parser.chunks)
        text += "\n\n" + content
    return [InputLine(page=1, line_no=i, text=line) for i, line in enumerate(text.splitlines(), 1)]
