from __future__ import annotations

import argparse
import sys
from pathlib import Path

from anon_tool.ingest.pdf_reader import read_pdf_lines
from anon_tool.ingest.txt_reader import read_txt_lines
from anon_tool.logging.audit import default_log_path, write_audit_log
from anon_tool.output.pdf_writer import write_sanitized_pdf
from anon_tool.output.report_writer import write_report
from anon_tool.redaction.engine import redact_lines
from anon_tool.rules.policy_profile_opentext import load_profile
from anon_tool.types import InputLine


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command != "redact":
        parser.print_help()
        return 1

    input_path = Path(args.input)
    output_path = Path(args.output)
    report_path = Path(args.report)
    config_path = Path(args.config) if args.config else None
    log_path = Path(args.log_file) if args.log_file else default_log_path()
    include_raw = _parse_bool(args.log_raw_values, default=True)
    input_type = _resolve_input_type(input_path, args.input_type)

    profile = load_profile(config_path)

    lines = _read_input(input_path, input_type)
    result = redact_lines(lines, profile)

    write_sanitized_pdf(output_path, result.redacted_lines)
    if args.also_write_txt:
        txt_path = Path(args.also_write_txt)
        txt_path.parent.mkdir(parents=True, exist_ok=True)
        txt_path.write_text(_to_plain_text(result.redacted_lines), encoding="utf-8")

    write_report(
        path=report_path,
        input_file=input_path,
        output_file=output_path,
        policy_profile=profile.policy_profile,
        result=result,
    )
    write_audit_log(log_path, result, include_raw_values=include_raw)

    print(f"Sanitized PDF written: {output_path}")
    print(f"Report written: {report_path}")
    print(f"Audit log written: {log_path}")
    print(f"Warnings: {len(result.warnings)}")

    if len(result.warnings) > args.warn_threshold:
        print(
            f"Warning threshold exceeded ({len(result.warnings)} > {args.warn_threshold}).",
            file=sys.stderr,
        )
        return 2
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="anon-tool", description="Policy-compliant PDF/TXT anonymizer.")
    sub = parser.add_subparsers(dest="command")

    redact = sub.add_parser("redact", help="Anonymize input and produce sanitized PDF/report output.")
    redact.add_argument("--input", required=True, help="Input file path (.pdf or .txt).")
    redact.add_argument("--output", required=True, help="Output sanitized PDF path.")
    redact.add_argument("--report", required=True, help="Output JSON report path.")
    redact.add_argument("--log-file", default=None, help="Detailed audit log path.")
    redact.add_argument("--log-raw-values", default="true", help="true|false, default true.")
    redact.add_argument("--warn-threshold", type=int, default=99999, help="Non-zero exit if warnings exceed value.")
    redact.add_argument("--input-type", choices=["auto", "pdf", "txt"], default="auto")
    redact.add_argument("--also-write-txt", default=None, help="Optional sanitized text output path.")
    redact.add_argument("--config", default=None, help="Optional YAML policy override file.")
    return parser


def _resolve_input_type(path: Path, requested: str) -> str:
    if requested != "auto":
        return requested
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".txt":
        return "txt"
    raise ValueError(f"Unable to infer input type from extension: {path.suffix}")


def _read_input(path: Path, input_type: str) -> list[InputLine]:
    if input_type == "pdf":
        return read_pdf_lines(path)
    if input_type == "txt":
        return read_txt_lines(path)
    raise ValueError(f"Unsupported input type: {input_type}")


def _parse_bool(value: str, default: bool) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _to_plain_text(lines: list[InputLine]) -> str:
    out: list[str] = []
    current_page = None
    for line in lines:
        if current_page != line.page:
            current_page = line.page
            out.append(f"=== Source Page {line.page} ===")
        out.append(line.text)
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())

