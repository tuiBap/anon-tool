from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
from typing import Iterable

from anon_tool.types import InputLine


DEFAULT_TITLE = "Sanitized Case Record"

_SECTION_TITLES = {
    "action item": "Action Items",
    "action items": "Action Items",
    "additional notes": "Notes",
    "case details": "Case Details",
    "case information": "Case Information",
    "description": "Description",
    "issue": "Issue",
    "notes": "Notes",
    "resolution": "Resolution",
    "root cause": "Root Cause",
    "symptom": "Symptoms",
    "symptoms": "Symptoms",
    "troubleshooting": "Troubleshooting",
    "troubleshooting steps": "Troubleshooting",
}
_BULLET_SECTIONS = {"Action Items", "Notes", "Symptoms", "Troubleshooting"}
_EMAIL_HEADER = re.compile(
    r"^(?P<label>date|sent|message date|from|to|cc|bcc|subject)\s*:\s*(?P<value>.*)$",
    re.IGNORECASE,
)
_FIELD_VALUE = re.compile(r"^(?P<label>[A-Za-z][A-Za-z0-9 /_().#&'-]{1,60})\s*[:|]\s*(?P<value>.+)$")
_PAGE_COUNTER = re.compile(r"^(?:page\s+)?\d+\s*(?:of|/)\s*\d+$", re.IGNORECASE)
_NOISE_LINE = re.compile(
    r"^(?:"
    r"print(?:able view| this page)?|"
    r"close window|"
    r"expand all|collapse all|"
    r"show more|show less|"
    r"back to (?:top|case)|"
    r"skip to navigation|"
    r"loading\.\.\.|"
    r"salesforce"
    r")$",
    re.IGNORECASE,
)
_PRINT_LINK = re.compile(r"^(?:https?://\S+)?\s*(?:print|printable view)\s*$", re.IGNORECASE)
_TECHNICAL_LINE = re.compile(
    r"(?:"
    r"^\s*(?:at\s+\S+\(|caused by:|traceback \(most recent call last\)|exception in thread)|"
    r"^\s*(?:\$|>|PS [A-Z]:\\|C:\\>)\s*\S+|"
    r"^\s*\d{4}-\d{2}-\d{2}[T ][0-9:.+-]+|"
    r"\b(?:(?-i:ERROR|WARN|FATAL)|Exception|Stack trace|exit code|command output)\b|"
    r"^\s*(?:GET|POST|PUT|PATCH|DELETE)\s+/\S+"
    r")",
    re.IGNORECASE,
)
_CASE_NUMBER = re.compile(r"\b(?:case|ticket)\s*(?:number|no\.?|#)?\s*[:#-]?\s*[A-Z0-9-]{4,}\b", re.IGNORECASE)


@dataclass(frozen=True)
class _Record:
    page: int
    text: str


def render_markdown(lines: Iterable[InputLine], title: str = DEFAULT_TITLE) -> str:
    """Render already-redacted input lines as validated Markdown."""
    records = _clean_records(lines)
    blocks: list[str] = [f"# {_heading_text(title)}"]

    if not records:
        blocks.append("## Case Content")
        blocks.append("_No extractable content._")
        markdown = "\n\n".join(blocks) + "\n"
        validate_markdown(markdown)
        return markdown

    blocks.append("## Case Content")
    current_page: int | None = None
    index = 0
    active_bullet_section = False
    email_count = 0

    while index < len(records):
        record = records[index]
        if record.page != current_page:
            current_page = record.page
            blocks.append(f"### Source Page {current_page}")
            active_bullet_section = False

        section = _section_title(record.text)
        if section:
            blocks.append(f"## {section}")
            active_bullet_section = section in _BULLET_SECTIONS
            index += 1
            continue

        if _starts_email(records, index):
            email_count += 1
            email_blocks, index = _render_email(records, index, email_count)
            blocks.extend(email_blocks)
            active_bullet_section = False
            continue

        technical, next_index = _collect_technical(records, index)
        if technical:
            blocks.append(_fenced_block(technical))
            index = next_index
            continue

        fields, next_index = _collect_fields(records, index)
        if fields:
            blocks.append(_render_fields(fields))
            index = next_index
            continue

        text = _normalize_text(record.text)
        if active_bullet_section:
            blocks.append(f"- {_strip_existing_bullet(text)}")
        else:
            blocks.append(_escape_block_start(text))
        index += 1

    markdown = "\n\n".join(block for block in blocks if block.strip()) + "\n"
    validate_markdown(markdown)
    return markdown


def validate_markdown(markdown: str) -> None:
    """Reject malformed renderer output before it reaches disk."""
    lines = markdown.splitlines()
    headings: list[tuple[int, int]] = []
    fence_marker: str | None = None

    for line_number, line in enumerate(lines, start=1):
        fence = re.match(r"^(`{3,}|~{3,})", line)
        if fence:
            marker = fence.group(1)
            if fence_marker is None:
                fence_marker = marker
            elif line.startswith(fence_marker):
                fence_marker = None
            continue
        if fence_marker is not None:
            continue

        heading = re.match(r"^(#{1,6})\s+\S", line)
        if heading:
            level = len(heading.group(1))
            headings.append((line_number, level))
            if line_number > 1 and lines[line_number - 2].strip():
                raise ValueError(f"Markdown heading on line {line_number} is not preceded by a blank line.")
            if line_number < len(lines) and lines[line_number].strip():
                raise ValueError(f"Markdown heading on line {line_number} is not followed by a blank line.")

        if re.match(r"^[ \t]*(?:[-+]\S|\*(?!\*)\S)", line):
            raise ValueError(f"Markdown list item on line {line_number} is missing a space.")

    if fence_marker is not None:
        raise ValueError("Markdown contains an unclosed fenced code block.")
    if not headings or headings[0] != (1, 1):
        raise ValueError("Markdown must start with an H1 title.")
    if sum(level == 1 for _, level in headings) != 1:
        raise ValueError("Markdown must contain exactly one H1 title.")

    previous_level = 0
    for line_number, level in headings:
        if previous_level and level > previous_level + 1:
            raise ValueError(f"Markdown heading level jumps on line {line_number}.")
        previous_level = level


def _clean_records(lines: Iterable[InputLine]) -> list[_Record]:
    candidates: list[_Record] = []
    for line in lines:
        text = _normalize_text(line.text)
        if not text or _is_noise(text):
            continue
        candidates.append(_Record(page=line.page, text=text))

    # Salesforce printable views often repeat a product/banner label at the
    # beginning or end of every page. Only remove short repeated boundary text;
    # case numbers and redaction placeholders are always retained.
    boundary_counts: Counter[str] = Counter()
    by_page: dict[int, list[_Record]] = {}
    for record in candidates:
        by_page.setdefault(record.page, []).append(record)
    for page_records in by_page.values():
        if page_records:
            for boundary_text in {page_records[0].text, page_records[-1].text}:
                boundary_counts[boundary_text] += 1

    repeated_boundaries = {
        text
        for text, count in boundary_counts.items()
        if count >= 2 and len(text) <= 80 and not _CASE_NUMBER.search(text) and "[REDACTED_" not in text
    }
    if not repeated_boundaries:
        return candidates

    cleaned: list[_Record] = []
    for page_records in by_page.values():
        for position, record in enumerate(page_records):
            is_boundary = position in {0, len(page_records) - 1}
            if is_boundary and record.text in repeated_boundaries:
                continue
            cleaned.append(record)
    return cleaned


def _is_noise(text: str) -> bool:
    compact = text.strip()
    lower = compact.lower()
    if _PAGE_COUNTER.fullmatch(compact) or _NOISE_LINE.fullmatch(compact) or _PRINT_LINK.fullmatch(compact):
        return True
    if lower.startswith(("javascript:", "data:text/html")):
        return True
    if re.fullmatch(r"(?:copyright|©)\s+\d{4}.*", compact, re.IGNORECASE):
        return True
    return False


def _section_title(text: str) -> str | None:
    normalized = re.sub(r"[:\s]+$", "", text).strip().lower()
    return _SECTION_TITLES.get(normalized)


def _starts_email(records: list[_Record], index: int) -> bool:
    match = _EMAIL_HEADER.match(records[index].text)
    if not match or match.group("label").lower() not in {"from", "date", "sent", "message date"}:
        return False
    nearby = records[index : min(index + 6, len(records))]
    labels = {
        header.group("label").lower()
        for record in nearby
        if record.page == records[index].page and (header := _EMAIL_HEADER.match(record.text))
    }
    return "from" in labels and ("subject" in labels or "to" in labels)


def _render_email(records: list[_Record], index: int, email_count: int) -> tuple[list[str], int]:
    headers: dict[str, str] = {}
    page = records[index].page
    while index < len(records) and records[index].page == page:
        match = _EMAIL_HEADER.match(records[index].text)
        if not match:
            break
        label = match.group("label").lower()
        canonical = "Date" if label in {"date", "sent", "message date"} else label.title()
        headers[canonical] = match.group("value").strip()
        index += 1

    body: list[str] = []
    while index < len(records) and records[index].page == page:
        if _section_title(records[index].text) or _starts_email(records, index):
            break
        body.append(records[index].text)
        index += 1

    blocks = ["## Email Thread", f"### Message {email_count}"]
    metadata = [
        f"- **{label}:** {headers[label]}"
        for label in ("Date", "From", "To", "Cc", "Bcc", "Subject")
        if headers.get(label)
    ]
    if metadata:
        blocks.append("\n".join(metadata))
    if body:
        blocks.append("**Body**")
        blocks.append("\n".join(_escape_block_start(line) for line in body))
    return blocks, index


def _collect_fields(records: list[_Record], index: int) -> tuple[list[tuple[str, str]], int]:
    page = records[index].page
    fields: list[tuple[str, str]] = []
    cursor = index
    while cursor < len(records) and records[cursor].page == page:
        match = _FIELD_VALUE.match(records[cursor].text)
        if not match or _EMAIL_HEADER.match(records[cursor].text):
            break
        label = match.group("label").strip()
        value = match.group("value").strip()
        if _section_title(label):
            break
        fields.append((label, value))
        cursor += 1
    return (fields, cursor) if fields else ([], index)


def _render_fields(fields: list[tuple[str, str]]) -> str:
    if len(fields) == 1:
        label, value = fields[0]
        return f"- **{_escape_inline(label)}:** {_escape_inline(value)}"
    rows = ["| Field | Value |", "| --- | --- |"]
    rows.extend(f"| {_escape_table(label)} | {_escape_table(value)} |" for label, value in fields)
    return "\n".join(rows)


def _collect_technical(records: list[_Record], index: int) -> tuple[list[str], int]:
    if not _TECHNICAL_LINE.search(records[index].text):
        return [], index
    page = records[index].page
    collected: list[str] = []
    cursor = index
    while cursor < len(records) and records[cursor].page == page:
        text = records[cursor].text
        if collected and (_section_title(text) or _starts_email(records, cursor)):
            break
        if not collected or _TECHNICAL_LINE.search(text) or text.startswith((" ", "\t")):
            collected.append(text)
            cursor += 1
            continue
        if _FIELD_VALUE.match(text):
            break
        break
    return collected, cursor


def _fenced_block(lines: list[str]) -> str:
    content = "\n".join(lines)
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", content)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}text\n{content}\n{fence}"


def _normalize_text(text: str) -> str:
    return text.replace("\u00a0", " ").strip()


def _heading_text(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    return normalized.lstrip("#").strip() or DEFAULT_TITLE


def _strip_existing_bullet(text: str) -> str:
    return re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", text).strip()


def _escape_inline(text: str) -> str:
    return text.replace("\n", " ").strip()


def _escape_block_start(text: str) -> str:
    return re.sub(r"^([*+-])(?=\S)", r"\\\1", text)


def _escape_table(text: str) -> str:
    return _escape_inline(text).replace("|", r"\|")
