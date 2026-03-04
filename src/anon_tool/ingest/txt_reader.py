from __future__ import annotations

from pathlib import Path

from anon_tool.types import InputLine


def read_txt_lines(path: Path) -> list[InputLine]:
    content = path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines()
    return [InputLine(page=1, line_no=i + 1, text=line) for i, line in enumerate(lines)]

