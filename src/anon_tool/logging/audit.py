from __future__ import annotations

from datetime import datetime
from pathlib import Path

from anon_tool.redaction.engine import RedactionResult


def default_log_path() -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("logs") / f"{ts}_redaction.log"


def write_audit_log(path: Path, result: RedactionResult, include_raw_values: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("WARNING: LOG MAY CONTAIN SENSITIVE SOURCE CONTENT.")
    lines.append("This file is intended for controlled local debugging only.")
    lines.append("")
    lines.append("=== Span Detections ===")
    for span in result.spans:
        raw = span.original_text if include_raw_values else "<hidden>"
        lines.append(
            f"p{span.page}:l{span.line} {span.rule_id} {span.category} "
            f"[{span.start},{span.end}) confidence={span.confidence} raw={raw!r}"
        )

    lines.append("")
    lines.append("=== Redaction Decisions ===")
    for decision in result.decisions:
        lines.append(f"{decision.span_id} -> {decision.replacement_token} reason={decision.reason}")

    lines.append("")
    lines.append("=== Warnings ===")
    if result.warnings:
        for warning in result.warnings:
            lines.append(f"{warning.location} {warning.rule_id} {warning.message}")
    else:
        lines.append("none")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

