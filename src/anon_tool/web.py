from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import gradio as gr

from anon_tool.cli import _read_input, _resolve_input_type, _to_markdown, _to_plain_text
from anon_tool.output.pdf_writer import write_sanitized_pdf
from anon_tool.redaction.engine import redact_lines
from anon_tool.rules.policy_profile_opentext import load_profile
from anon_tool.types import InputLine


APP_TITLE = "Anon Tool"
SAVED_OUTPUT_DIR = Path("runs/output/web-ui")
WEB_SETTINGS_PATH = Path("runs/web-ui-settings.json")
DEFAULT_WEB_SETTINGS = {
    "default_output_format": "Markdown",
    "retention_days": 30,
}
OUTPUT_FORMAT_CHOICES = ["Markdown", "Plain text", "PDF"]
DEFAULT_OUTPUT_FORMAT_CHOICES = ["Markdown", "Plain text"]
RETENTION_DAY_CHOICES = [10, 30, 90]
RETENTION_UI_CHOICES = [(f"{days} days", days) for days in RETENTION_DAY_CHOICES]


def launch_app(
    server_name: str = "127.0.0.1",
    server_port: int = 7860,
    auth_user: str | None = None,
    auth_password: str | None = None,
) -> None:
    auth = _resolve_auth(server_name, auth_user, auth_password)
    app = build_app()
    app.launch(
        server_name=server_name,
        server_port=server_port,
        auth=auth,
        theme=_theme(),
        css=_css(),
        footer_links=[],
    )


def _resolve_auth(
    server_name: str,
    auth_user: str | None,
    auth_password: str | None,
) -> tuple[str, str] | None:
    if bool(auth_user) != bool(auth_password):
        raise ValueError("Provide both --auth-user and --auth-password, or neither.")
    if auth_user and auth_password:
        return (auth_user, auth_password)
    if not _is_loopback_bind(server_name):
        raise ValueError("Refusing to expose the web UI without authentication. Use --auth-user and --auth-password.")
    return None


def _is_loopback_bind(server_name: str) -> bool:
    normalized = server_name.strip().lower()
    return normalized in {"127.0.0.1", "localhost", "::1"}


def build_app() -> gr.Blocks:
    settings = _load_web_settings()
    _cleanup_stale_outputs(int(settings["retention_days"]))
    initial_saved_outputs = _load_saved_outputs()

    with gr.Blocks(
        title=APP_TITLE,
        fill_width=True,
    ) as app:
        history_state = gr.State([])
        saved_state = gr.State(initial_saved_outputs)

        gr.HTML(_shell_header())

        with gr.Row(elem_classes=["app-shell"]):
            with gr.Column(elem_classes=["side-nav"]):
                gr.HTML(_sidebar_header())
                dashboard_nav = gr.Button("Dashboard", elem_classes=["nav-button", "active-nav"])
                history_nav = gr.Button("History", elem_classes=["nav-button"])
                saved_nav = gr.Button("Saved Outputs", elem_classes=["nav-button"])
                settings_nav = gr.Button("Settings", elem_classes=["nav-button"])
                about_nav = gr.Button("About", elem_classes=["nav-button"])
                gr.HTML(_sidebar_footer())

            with gr.Column(elem_classes=["workspace"]):
                with gr.Group(visible=True) as dashboard_view:
                    with gr.Row(elem_classes=["control-panel"]):
                        with gr.Column(scale=3, elem_classes=["source-card"]):
                            with gr.Tabs():
                                with gr.Tab("Upload file"):
                                    file_input = gr.File(
                                        label="",
                                        show_label=False,
                                        file_types=[".pdf", ".txt", ".docx"],
                                        file_count="multiple",
                                        elem_classes=["file-picker"],
                                    )
                                with gr.Tab("Paste text"):
                                    text_input = gr.Textbox(
                                        label="",
                                        placeholder="Paste text to anonymize...",
                                        lines=7,
                                        max_lines=12,
                                        elem_classes=["paste-box"],
                                    )
                        with gr.Column(scale=2, elem_classes=["run-card"]):
                            output_format = gr.Dropdown(
                                label="Output format",
                                choices=OUTPUT_FORMAT_CHOICES,
                                value=str(settings["default_output_format"]),
                                interactive=True,
                            )
                            anonymize_button = gr.Button("Anonymize", variant="primary", elem_classes=["run-button"])
                            status_line = gr.Markdown("Sensitive fields will be detected and redacted.")

                    stats = gr.HTML(_empty_stats(output_format=str(settings["default_output_format"])))

                    with gr.Row(elem_classes=["compare-grid"]):
                        with gr.Column(elem_classes=["text-panel"]):
                            with gr.Row(elem_classes=["panel-header"]):
                                gr.Markdown("### Original text")
                            original_output = gr.Textbox(
                                label="",
                                show_label=False,
                                lines=14,
                                max_lines=20,
                                buttons=["copy"],
                                elem_classes=["mono-output"],
                            )
                        with gr.Column(elem_classes=["text-panel"]):
                            with gr.Row(elem_classes=["panel-header"]):
                                gr.Markdown("### Anonymized output")
                                download_file = gr.DownloadButton(
                                    "Download output",
                                    size="sm",
                                    interactive=False,
                                    elem_classes=["small-button", "download-button"],
                                )
                            redacted_output = gr.Textbox(
                                label="",
                                show_label=False,
                                lines=14,
                                max_lines=20,
                                buttons=["copy"],
                                elem_classes=["mono-output"],
                            )

                    with gr.Accordion("Details", open=True, elem_classes=["details-panel"]):
                        gr.Markdown("Warnings and run metadata appear here after anonymization.")
                        warnings_table = gr.Dataframe(
                            label="Warnings",
                            headers=["Location", "Rule", "Message"],
                            datatype=["str", "str", "str"],
                            interactive=False,
                            elem_classes=["warnings-table"],
                        )
                        with gr.Row():
                            details_json = gr.Code(label="", language="json", lines=10, elem_classes=["details-code"])
                            details_table = gr.Dataframe(
                                label="Run summary",
                                headers=["Field", "Value"],
                                datatype=["str", "str"],
                                interactive=False,
                                elem_classes=["details-table"],
                            )

                with gr.Group(visible=False, elem_classes=["page-panel"]) as history_view:
                    gr.Markdown("## History")
                    gr.Markdown("Each anonymization run in this session is listed here.")
                    history_table = gr.Dataframe(
                        value=[],
                        headers=["Time", "Source", "Redactions", "Warnings", "Processing time", "Saved output"],
                        datatype=["str", "str", "number", "number", "str", "str"],
                        interactive=False,
                    )

                with gr.Group(visible=False, elem_classes=["saved-page"]) as saved_view:
                    gr.Markdown("## Saved Outputs")
                    gr.Markdown("Latest saved redacted outputs, sorted newest first.")
                    saved_picker = gr.CheckboxGroup(
                        label="Select saved files",
                        choices=_saved_selection_choices(initial_saved_outputs),
                        interactive=True,
                        elem_classes=["saved-picker"],
                    )
                    with gr.Row(elem_classes=["saved-actions"]):
                        select_all_saved_button = gr.Button(
                            "Select all",
                            elem_classes=["nav-button"],
                        )
                        delete_saved_button = gr.Button(
                            "Delete selected",
                            variant="stop",
                            elem_classes=["delete-button"],
                        )
                        prepare_separate_button = gr.Button(
                            "Prepare separate files",
                            elem_classes=["nav-button"],
                        )
                        prepare_combined_button = gr.Button(
                            "Prepare combined file",
                            elem_classes=["nav-button"],
                        )
                        combined_download_file = gr.DownloadButton(
                            "Download combined",
                            size="sm",
                            elem_classes=["small-button"],
                        )
                    saved_downloads = gr.Files(
                        label="Prepared separate downloads",
                        interactive=False,
                        elem_classes=["saved-downloads"],
                    )
                    saved_status = gr.Markdown("Select one or more saved files.")
                    saved_table = gr.Dataframe(
                        value=_saved_rows(initial_saved_outputs, limit=25),
                        headers=["Time", "Source", "Redactions", "Warnings", "Path"],
                        datatype=["str", "str", "number", "number", "str"],
                        interactive=False,
                    )

                with gr.Group(visible=False, elem_classes=["page-panel"]) as settings_view:
                    gr.Markdown("## Settings")
                    gr.Markdown("Configure dashboard defaults and automatic cleanup for saved web UI outputs.")
                    with gr.Row(elem_classes=["settings-grid"]):
                        default_output_setting = gr.Dropdown(
                            label="Default output",
                            choices=DEFAULT_OUTPUT_FORMAT_CHOICES,
                            value=str(settings["default_output_format"]),
                            interactive=True,
                        )
                        retention_setting = gr.Dropdown(
                            label="Delete saved outputs older than",
                            choices=RETENTION_UI_CHOICES,
                            value=int(settings["retention_days"]),
                            interactive=True,
                            info="Applies to anonymized files in runs/output/web-ui.",
                        )
                    save_settings_button = gr.Button(
                        "Save settings",
                        variant="primary",
                        elem_classes=["settings-save-button"],
                    )
                    settings_status = gr.Markdown(
                        f"Current retention: {settings['retention_days']} days. Settings are saved locally."
                    )

                with gr.Group(visible=False, elem_classes=["page-panel"]) as about_view:
                    gr.Markdown(
                        """
                        ## About

                        Anon Tool is a local anonymization utility for redacting sensitive information from PDF, TXT, DOCX, and pasted text inputs.

                        Written by David Bush.
                        """
                    )

        views = [dashboard_view, history_view, saved_view, settings_view, about_view]
        dashboard_nav.click(lambda: _view_updates("dashboard"), outputs=views)
        history_nav.click(lambda: _view_updates("history"), outputs=views)
        saved_nav.click(lambda: _view_updates("saved"), outputs=views)
        settings_nav.click(lambda: _view_updates("settings"), outputs=views)
        about_nav.click(lambda: _view_updates("about"), outputs=views)
        saved_nav.click(
            fn=refresh_saved_outputs,
            inputs=[saved_state],
            outputs=[saved_state, saved_picker, saved_table, saved_downloads, combined_download_file, saved_status],
        )
        select_all_saved_button.click(
            fn=select_all_saved_outputs,
            inputs=[saved_state],
            outputs=[saved_picker, saved_status],
        )
        delete_saved_button.click(
            fn=delete_saved_outputs,
            inputs=[saved_picker, saved_state],
            outputs=[saved_state, saved_picker, saved_table, saved_downloads, combined_download_file, saved_status],
        )
        prepare_separate_button.click(
            fn=prepare_separate_downloads,
            inputs=[saved_picker],
            outputs=[saved_downloads, saved_status],
        )
        prepare_combined_button.click(
            fn=prepare_combined_download,
            inputs=[saved_picker],
            outputs=[combined_download_file, saved_status],
        )
        save_settings_button.click(
            fn=save_web_settings,
            inputs=[default_output_setting, retention_setting, saved_state],
            outputs=[
                output_format,
                saved_state,
                saved_picker,
                saved_table,
                saved_downloads,
                combined_download_file,
                saved_status,
                settings_status,
            ],
        )

        anonymize_button.click(
            fn=run_anonymization,
            inputs=[file_input, text_input, output_format, history_state, saved_state],
            outputs=[
                original_output,
                redacted_output,
                stats,
                details_json,
                details_table,
                warnings_table,
                download_file,
                status_line,
                history_state,
                saved_state,
                history_table,
                saved_table,
                saved_picker,
                saved_downloads,
                combined_download_file,
                saved_status,
            ],
        )

    return app


def _theme() -> gr.themes.Base:
    return gr.themes.Base(
        primary_hue="green",
        neutral_hue="slate",
        font=[gr.themes.GoogleFont("Inter"), "Arial", "sans-serif"],
        font_mono=[gr.themes.GoogleFont("JetBrains Mono"), "Consolas", "monospace"],
    )


def run_anonymization(
    uploaded_file: Any,
    pasted_text: str | None,
    output_format: str,
    history: list[dict[str, Any]] | None,
    saved_outputs: list[dict[str, Any]] | None,
) -> tuple[
    str,
    str,
    str,
    str,
    list[list[str]],
    list[list[str]],
    Any,
    str,
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[list[Any]],
    list[list[Any]],
    Any,
    Any,
    Any,
    str,
]:
    start = time.perf_counter()
    history = history or []
    saved_outputs = saved_outputs or []
    try:
        sources = _load_sources(uploaded_file, pasted_text)
        profile = load_profile(None)
        run_items = []
        total_redactions = 0
        total_warnings = 0

        for lines, source_name in sources:
            item_start = time.perf_counter()
            result = redact_lines(lines, profile)
            item_elapsed = time.perf_counter() - item_start

            original_text = _to_plain_text(lines)
            redacted_text = _to_plain_text(result.redacted_lines)
            details = _build_details(result, output_format, item_elapsed, source_name)
            download_path = _write_download(result.redacted_lines, source_name, details, output_format)
            record = _run_record(details, download_path)

            total_redactions += len(result.spans)
            total_warnings += len(result.warnings)
            run_items.append(
                {
                    "source_name": source_name,
                    "original_text": original_text,
                    "redacted_text": redacted_text,
                    "details": details,
                    "download_path": download_path,
                    "record": record,
                }
            )

        elapsed = time.perf_counter() - start

        first_item = run_items[0]
        details = _batch_details(run_items, output_format, elapsed)
        details_text = json.dumps(details, indent=2)
        records = [item["record"] for item in run_items]
        download_path = str(first_item["download_path"])
        history = [*records, *history]
        new_paths = {record.get("path") for record in records}
        saved_outputs = [*records, *[item for item in saved_outputs if item.get("path") not in new_paths]]
        status = _batch_status(total_warnings, len(run_items))
        saved_choices = _saved_selection_choices(saved_outputs)

        return (
            str(first_item["original_text"]),
            str(first_item["redacted_text"]),
            _stats_html(total_redactions, total_warnings, output_format, elapsed),
            details_text,
            _details_rows(details),
            _warning_rows(details),
            gr.update(value=download_path, interactive=True),
            status,
            history,
            saved_outputs,
            _history_rows(history),
            _saved_rows(saved_outputs, limit=25),
            gr.update(choices=saved_choices, value=[record["path"] for record in records[:25]]),
            [record["path"] for record in records],
            None,
            f"Prepared {len(records)} new saved output file(s).",
        )
    except Exception as exc:
        details = {
            "schema_version": 1,
            "status": "error",
            "message": str(exc),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return (
            "",
            "",
            _empty_stats(output_format=output_format, error=True),
            json.dumps(details, indent=2),
            _details_rows(details),
            _warning_rows(details),
            gr.update(value=None, interactive=False),
            f"Unable to anonymize input: {exc}",
            history,
            saved_outputs,
            _history_rows(history),
            _saved_rows(saved_outputs, limit=25),
            gr.update(),
            None,
            None,
            "Select one or more saved files.",
        )


def _load_sources(uploaded_file: Any, pasted_text: str | None) -> list[tuple[list[InputLine], str]]:
    if uploaded_file is not None:
        uploaded_files = uploaded_file if isinstance(uploaded_file, list) else [uploaded_file]
        sources = []
        for item in uploaded_files:
            path = Path(item.name if hasattr(item, "name") else str(item))
            input_type = _resolve_input_type(path, "auto")
            sources.append((_read_input(path, input_type), path.name))
        if sources:
            return sources

    text = (pasted_text or "").strip("\ufeff")
    if not text.strip():
        raise ValueError("Upload one or more PDF, TXT, or DOCX files, or paste text first.")

    raw_lines = text.splitlines() or [text]
    return [([InputLine(page=1, line_no=index, text=line) for index, line in enumerate(raw_lines, start=1)], "pasted-text.txt")]


def _build_details(result: Any, output_format: str, elapsed: float, source_name: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "summary": {
            "output_mode": "redacted",
            "output_format": output_format.lower(),
            "redaction_count": len(result.spans),
            "by_label": result.counts_by_category,
            "decoded_mismatch": False,
            "processing_time_seconds": round(elapsed, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "file": source_name,
        },
        "warnings": [asdict(warning) for warning in result.warnings],
        "residual_risk_checks": result.residual_risk_checks,
    }


def _batch_details(run_items: list[dict[str, Any]], output_format: str, elapsed: float) -> dict[str, Any]:
    if len(run_items) == 1:
        details = dict(run_items[0]["details"])
        details["summary"] = dict(details.get("summary", {}))
        details["summary"]["processing_time_seconds"] = round(elapsed, 2)
        return details

    warnings = []
    redaction_count = 0
    by_label: dict[str, int] = {}
    files = []
    for item in run_items:
        details = item["details"]
        summary = details.get("summary", {})
        redaction_count += int(summary.get("redaction_count", 0))
        for label, count in summary.get("by_label", {}).items():
            by_label[label] = by_label.get(label, 0) + int(count)
        warnings.extend(details.get("warnings", []))
        files.append(
            {
                "file": summary.get("file", ""),
                "redaction_count": summary.get("redaction_count", 0),
                "warnings": len(details.get("warnings", [])),
                "processing_time_seconds": summary.get("processing_time_seconds", 0),
                "download_path": item.get("download_path", ""),
            }
        )

    return {
        "schema_version": 1,
        "summary": {
            "output_mode": "redacted",
            "output_format": output_format.lower(),
            "redaction_count": redaction_count,
            "by_label": by_label,
            "decoded_mismatch": False,
            "processing_time_seconds": round(elapsed, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "file": f"{len(run_items)} uploaded files",
            "file_count": len(run_items),
        },
        "files": files,
        "warnings": warnings,
        "residual_risk_checks": {},
    }


def _write_download(
    lines: list[InputLine],
    source_name: str,
    details: dict[str, Any],
    output_format: str = "Markdown",
) -> str:
    SAVED_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = _safe_stem(source_name)
    timestamp = str(details.get("summary", {}).get("timestamp", datetime.now(timezone.utc).isoformat()))
    compact_ts = re.sub(r"[^0-9T]", "", timestamp.split("+", 1)[0].replace(":", ""))
    normalized_format = output_format.strip().lower()
    extension = {"markdown": "md", "plain text": "txt", "text": "txt", "pdf": "pdf"}.get(normalized_format)
    if extension is None:
        raise ValueError(f"Unsupported output format: {output_format}")

    output = SAVED_OUTPUT_DIR / f"{compact_ts}-{stem}.anonymized.{extension}"
    if normalized_format == "pdf":
        write_sanitized_pdf(output, lines)
    elif normalized_format == "markdown":
        output.write_text(_to_markdown(lines), encoding="utf-8")
    else:
        output.write_text(_to_plain_text(lines), encoding="utf-8")
    return str(output)


def _safe_stem(source_name: str) -> str:
    stem = Path(source_name).stem or "anon-tool-output"
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", stem).strip("-")
    return cleaned or "anon-tool-output"


def _run_record(details: dict[str, Any], output_path: str) -> dict[str, Any]:
    summary = details.get("summary", {})
    return {
        "time": summary.get("timestamp", ""),
        "source": summary.get("file", ""),
        "redactions": summary.get("redaction_count", 0),
        "warnings": len(details.get("warnings", [])),
        "processing_time": f"{summary.get('processing_time_seconds', 0)}s",
        "path": output_path,
    }


def _load_saved_outputs() -> list[dict[str, Any]]:
    if not SAVED_OUTPUT_DIR.exists():
        return []
    records: list[dict[str, Any]] = []
    saved_paths = [
        path
        for pattern in ("*.anonymized.md", "*.anonymized.txt", "*.anonymized.pdf")
        for path in SAVED_OUTPUT_DIR.glob(pattern)
    ]
    for path in sorted(saved_paths, key=lambda item: item.stat().st_mtime, reverse=True):
        records.append(
            {
                "time": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
                "source": _source_from_saved_filename(path.name),
                "redactions": "",
                "warnings": "",
                "processing_time": "",
                "path": str(path),
            }
        )
    return records


def _load_web_settings() -> dict[str, Any]:
    settings = dict(DEFAULT_WEB_SETTINGS)
    if not WEB_SETTINGS_PATH.exists():
        return settings
    try:
        saved = json.loads(WEB_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return settings
    if not isinstance(saved, dict):
        return settings

    output_format = str(saved.get("default_output_format", "")).strip()
    if output_format in DEFAULT_OUTPUT_FORMAT_CHOICES:
        settings["default_output_format"] = output_format
    try:
        retention_days = int(saved.get("retention_days", DEFAULT_WEB_SETTINGS["retention_days"]))
    except (TypeError, ValueError):
        retention_days = int(DEFAULT_WEB_SETTINGS["retention_days"])
    if retention_days in RETENTION_DAY_CHOICES:
        settings["retention_days"] = retention_days
    return settings


def _write_web_settings(default_output_format: str, retention_days: int) -> dict[str, Any]:
    normalized_format = str(default_output_format).strip()
    normalized_retention = int(retention_days)
    if normalized_format not in DEFAULT_OUTPUT_FORMAT_CHOICES:
        raise ValueError(f"Unsupported default output format: {default_output_format}")
    if normalized_retention not in RETENTION_DAY_CHOICES:
        raise ValueError(f"Unsupported output retention period: {retention_days}")

    settings = {
        "default_output_format": normalized_format,
        "retention_days": normalized_retention,
    }
    WEB_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = WEB_SETTINGS_PATH.with_suffix(WEB_SETTINGS_PATH.suffix + ".tmp")
    temporary_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(WEB_SETTINGS_PATH)
    return settings


def _cleanup_stale_outputs(retention_days: int, now: datetime | None = None) -> tuple[int, int]:
    if retention_days not in RETENTION_DAY_CHOICES:
        raise ValueError(f"Unsupported output retention period: {retention_days}")
    if not SAVED_OUTPUT_DIR.exists():
        return 0, 0

    reference_time = now or datetime.now(timezone.utc)
    cutoff = reference_time.timestamp() - (retention_days * 24 * 60 * 60)
    deleted = 0
    failed = 0
    for pattern in ("*.anonymized.md", "*.anonymized.txt", "*.anonymized.pdf"):
        for path in SAVED_OUTPUT_DIR.glob(pattern):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    deleted += 1
            except OSError:
                failed += 1
    return deleted, failed


def save_web_settings(
    default_output_format: str,
    retention_days: int,
    saved_outputs: list[dict[str, Any]] | None,
) -> tuple[Any, list[dict[str, Any]], Any, list[list[Any]], Any, Any, str, str]:
    settings = _write_web_settings(default_output_format, retention_days)
    deleted, failed = _cleanup_stale_outputs(int(settings["retention_days"]))
    refreshed = _merge_saved_outputs(saved_outputs or [])
    cleanup_status = f"Removed {deleted} stale output file(s)."
    if failed:
        cleanup_status += f" Could not remove {failed} locked or inaccessible file(s)."
    return (
        gr.update(value=settings["default_output_format"]),
        refreshed,
        gr.update(choices=_saved_selection_choices(refreshed), value=[]),
        _saved_rows(refreshed, limit=25),
        None,
        None,
        "Select one or more saved files.",
        (
            f"Settings saved. Default output: {settings['default_output_format']}. "
            f"Retention: {settings['retention_days']} days. {cleanup_status}"
        ),
    )


def _source_from_saved_filename(name: str) -> str:
    stem = re.sub(r"\.anonymized\.(?:md|txt|pdf)$", "", name, flags=re.IGNORECASE)
    return re.sub(r"^[0-9T]+-", "", stem) or stem


def _details_rows(details: dict[str, Any]) -> list[list[str]]:
    summary = details.get("summary", {})
    rows = [
        ["Schema version", str(details.get("schema_version", ""))],
        ["Output format", str(summary.get("output_format", ""))],
        ["Redaction count", str(summary.get("redaction_count", ""))],
        ["Decoded mismatch", str(summary.get("decoded_mismatch", ""))],
        ["Processing time", f"{summary.get('processing_time_seconds', '')}s"],
        ["Timestamp", str(summary.get("timestamp", details.get("timestamp", "")))],
        ["File", str(summary.get("file", ""))],
        ["Warnings", str(len(details.get("warnings", [])))],
    ]
    if "message" in details:
        rows.append(["Message", str(details["message"])])
    return rows


def _warning_rows(details: dict[str, Any]) -> list[list[str]]:
    warnings = details.get("warnings", [])
    return [
        [
            str(warning.get("location", "")),
            str(warning.get("rule_id", "")),
            str(warning.get("message", "")),
        ]
        for warning in warnings
    ]


def _history_rows(history: list[dict[str, Any]]) -> list[list[Any]]:
    return [
        [
            item.get("time", ""),
            item.get("source", ""),
            item.get("redactions", ""),
            item.get("warnings", ""),
            item.get("processing_time", ""),
            item.get("path", ""),
        ]
        for item in history
    ]


def _saved_rows(saved_outputs: list[dict[str, Any]], limit: int | None = None) -> list[list[Any]]:
    rows = []
    for item in _latest_existing_outputs(saved_outputs, limit=limit):
        rows.append(
            [
                item.get("time", ""),
                item.get("source", ""),
                item.get("redactions", ""),
                item.get("warnings", ""),
                item.get("path", ""),
            ]
        )
    return rows


def _latest_existing_outputs(saved_outputs: list[dict[str, Any]], limit: int | None = 25) -> list[dict[str, Any]]:
    existing = [item for item in saved_outputs if _valid_saved_path(str(item.get("path", "")))]
    existing.sort(key=lambda item: str(item.get("time", "")), reverse=True)
    if limit is None:
        return existing
    return existing[:limit]


def _saved_selection_choices(saved_outputs: list[dict[str, Any]], limit: int = 25) -> list[tuple[str, str]]:
    choices = []
    for item in _latest_existing_outputs(saved_outputs, limit=limit):
        path = str(item.get("path", ""))
        label = f"{item.get('time', '')} | {item.get('source', '')} | {path}"
        choices.append((label, path))
    return choices


def _valid_saved_path(path: str) -> bool:
    if not path:
        return False
    try:
        candidate = Path(path)
        return candidate.exists() and candidate.is_file()
    except OSError:
        return False


def refresh_saved_outputs(
    saved_outputs: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], Any, list[list[Any]], Any, Any, str]:
    settings = _load_web_settings()
    _cleanup_stale_outputs(int(settings["retention_days"]))
    refreshed = _merge_saved_outputs(saved_outputs or [])
    return (
        refreshed,
        gr.update(choices=_saved_selection_choices(refreshed), value=[]),
        _saved_rows(refreshed, limit=25),
        None,
        None,
        "Select one or more saved files.",
    )


def select_all_saved_outputs(
    saved_outputs: list[dict[str, Any]] | None,
) -> tuple[Any, str]:
    choices = _saved_selection_choices(saved_outputs or [])
    selected_paths = [path for _, path in choices]
    if not selected_paths:
        return gr.update(choices=choices, value=[]), "No saved output files are available."
    return (
        gr.update(choices=choices, value=selected_paths),
        f"Selected all {len(selected_paths)} saved output file(s).",
    )


def delete_saved_outputs(
    selected_paths: list[str] | None,
    saved_outputs: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], Any, list[list[Any]], Any, Any, str]:
    requested_paths = list(dict.fromkeys(selected_paths or []))
    if not requested_paths:
        refreshed = _merge_saved_outputs(saved_outputs or [])
        return (
            refreshed,
            gr.update(choices=_saved_selection_choices(refreshed), value=[]),
            _saved_rows(refreshed, limit=25),
            None,
            None,
            "Select one or more saved files to delete.",
        )

    deleted = 0
    failed = 0
    skipped = 0
    for raw_path in requested_paths:
        path = _deletable_saved_path(raw_path)
        if path is None:
            skipped += 1
            continue
        try:
            path.unlink()
            deleted += 1
        except OSError:
            failed += 1

    refreshed = _merge_saved_outputs(saved_outputs or [])
    status = f"Deleted {deleted} saved output file(s)."
    if failed:
        status += f" Could not delete {failed} locked or inaccessible file(s)."
    if skipped:
        status += f" Ignored {skipped} invalid or unavailable selection(s)."
    return (
        refreshed,
        gr.update(choices=_saved_selection_choices(refreshed), value=[]),
        _saved_rows(refreshed, limit=25),
        None,
        None,
        status,
    )


def _deletable_saved_path(path: str) -> Path | None:
    if not path:
        return None
    try:
        output_root = SAVED_OUTPUT_DIR.resolve()
        candidate = Path(path).resolve()
        candidate.relative_to(output_root)
        if not candidate.is_file():
            return None
        if not re.search(r"\.anonymized\.(?:md|txt|pdf)$", candidate.name, flags=re.IGNORECASE):
            return None
        return candidate
    except (OSError, ValueError):
        return None


def _merge_saved_outputs(saved_outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_path = {str(item.get("path", "")): item for item in _load_saved_outputs()}
    by_path.update({str(item.get("path", "")): item for item in saved_outputs if item.get("path")})
    return _latest_existing_outputs(list(by_path.values()), limit=None)


def prepare_separate_downloads(selected_paths: list[str] | None) -> tuple[list[str] | None, str]:
    paths = _selected_saved_paths(selected_paths)
    if not paths:
        return None, "Select one or more saved files."
    file_label = "file" if len(paths) == 1 else "files"
    return paths, f"Prepared {len(paths)} separate {file_label}."


def prepare_combined_download(selected_paths: list[str] | None) -> tuple[str | None, str]:
    paths = _selected_saved_paths(selected_paths)
    if not paths:
        return None, "Select one or more saved files."
    combined_path = _write_combined_download(paths)
    return combined_path, f"Prepared one combined file from {len(paths)} saved output file(s)."


def _selected_saved_paths(selected_paths: list[str] | None) -> list[str]:
    if not selected_paths:
        return []
    return [path for path in selected_paths if _valid_saved_path(path)]


def _write_combined_download(paths: list[str]) -> str:
    SAVED_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    compact_ts = re.sub(r"[^0-9T]", "", timestamp.split("+", 1)[0].replace(":", ""))
    output = SAVED_OUTPUT_DIR / f"{compact_ts}-combined.anonymized.md"
    sections = []
    for path in paths:
        source = Path(path)
        sections.append(f"# {source.name}\n\n{_read_saved_output(source).strip()}")
    output.write_text("\n\n".join(sections) + "\n", encoding="utf-8")
    return str(output)


def _read_saved_output(path: Path) -> str:
    if path.suffix.lower() != ".pdf":
        return path.read_text(encoding="utf-8")

    from pypdf import PdfReader

    return "\n\n".join((page.extract_text() or "").strip() for page in PdfReader(path).pages)


def _batch_status(warnings_count: int, file_count: int) -> str:
    file_label = "file" if file_count == 1 else "files"
    if warnings_count:
        return f"Completed {file_count} {file_label} with {warnings_count} warning(s). Review Details before sharing."
    return "Sensitive fields were detected and redacted."


def _empty_stats(output_format: str = "Markdown", error: bool = False) -> str:
    if error:
        return _stat_cards(
            [
                ("0 redactions", "Detected & redacted", "scan"),
                ("Error", "Review details", "warn"),
                (output_format, "Output format", "doc"),
                ("0.00s", "Processing time", "time"),
            ]
        )
    return _stat_cards(
        [
            ("0 redactions", "Detected & redacted", "scan"),
            ("0 mismatches", "Decoded mismatches", "shield"),
            (output_format, "Output format", "doc"),
            ("0.00s", "Processing time", "time"),
        ]
    )


def _stats_html(redaction_count: int, warnings_count: int, output_format: str, elapsed: float) -> str:
    warning_label = "warning" if warnings_count == 1 else "warnings"
    return _stat_cards(
        [
            (f"{redaction_count} redactions", "Detected & redacted", "scan"),
            (f"{warnings_count} {warning_label}", "Review in Details", "warn"),
            (output_format, "Output format", "doc"),
            (f"{elapsed:.2f}s", "Processing time", "time"),
        ]
    )


def _stat_cards(items: list[tuple[str, str, str]]) -> str:
    icons = {
        "scan": "[]",
        "shield": "<>",
        "doc": "##",
        "time": "o",
        "warn": "!",
    }
    cards = []
    for value, label, icon in items:
        cards.append(
            f"""
            <div class="stat-card">
              <div class="stat-icon">{icons.get(icon, "*")}</div>
              <div>
                <div class="stat-value">{value}</div>
                <div class="stat-label">{label}</div>
              </div>
            </div>
            """
        )
    return f'<div class="stats-grid">{"".join(cards)}</div>'


def _view_updates(active: str) -> list[Any]:
    return [
        gr.update(visible=active == "dashboard"),
        gr.update(visible=active == "history"),
        gr.update(visible=active == "saved"),
        gr.update(visible=active == "settings"),
        gr.update(visible=active == "about"),
    ]


def _shell_header() -> str:
    return """
    <div class="browser-chrome">
      <div class="chrome-dots"><span></span><span></span><span></span></div>
      <div class="chrome-tab">Anon Tool</div>
      <div class="chrome-url">127.0.0.1:7860</div>
    </div>
    """


def _sidebar_header() -> str:
    return """
    <div class="brand"><div class="brand-mark">◇</div><div>Anon Tool</div></div>
    """


def _sidebar_footer() -> str:
    return """
    <div class="nav-footer"><strong>Anon Tool v1.0.0</strong><br><span>Local processing - Secure</span></div>
    """


def _css() -> str:
    return """
    :root {
      --bg: #07110d;
      --bg-2: #0b1712;
      --panel: rgba(18, 31, 25, 0.92);
      --panel-2: rgba(15, 27, 22, 0.98);
      --border: #284036;
      --border-soft: #1d3128;
      --green: #1f7a4d;
      --green-2: #25a865;
      --green-soft: rgba(31, 122, 77, 0.22);
      --text: #edf5ef;
      --muted: #a7b8ae;
      --dim: #71827a;
      --code: #09110e;
    }

    body, .gradio-container {
      background:
        radial-gradient(circle at 80% 12%, rgba(31, 122, 77, 0.12), transparent 28%),
        linear-gradient(180deg, #0b1511 0%, var(--bg) 45%, #050907 100%) !important;
      color: var(--text) !important;
      min-height: 100vh;
    }

    .gradio-container {
      max-width: none !important;
      padding: 0 !important;
    }

    .browser-chrome {
      height: 56px;
      background: #1b1d1d;
      border-bottom: 1px solid #303636;
      display: flex;
      align-items: center;
      gap: 18px;
      padding: 0 18px;
      color: #d8dedb;
      font-size: 14px;
    }

    .chrome-dots span {
      display: inline-block;
      width: 12px;
      height: 12px;
      border-radius: 50%;
      margin-right: 7px;
      background: #e65b5b;
    }

    .chrome-dots span:nth-child(2) { background: #e0b94e; }
    .chrome-dots span:nth-child(3) { background: #38b76b; }

    .chrome-tab {
      background: #252a29;
      border-radius: 10px 10px 0 0;
      padding: 10px 28px;
      color: #d8dedb;
    }

    .chrome-url {
      flex: 1;
      background: #111515;
      border: 1px solid #343a39;
      border-radius: 18px;
      padding: 8px 14px;
      color: #b7c0bc;
    }

    .app-shell {
      min-height: calc(100vh - 56px);
      gap: 0 !important;
    }

    .side-nav {
      width: 255px !important;
      flex: 0 0 255px !important;
      min-height: calc(100vh - 56px);
      padding: 28px 14px;
      border-right: 1px solid var(--border-soft);
      background: linear-gradient(180deg, rgba(9, 28, 20, 0.96), rgba(5, 14, 11, 0.98));
      box-sizing: border-box;
      position: relative;
      color: var(--text);
    }

    .brand {
      display: flex;
      gap: 12px;
      align-items: center;
      font-size: 30px;
      font-weight: 700;
      margin: 0 10px 24px;
      color: var(--text);
    }

    .brand-mark {
      color: #71d69a;
      text-shadow: 0 0 14px rgba(37, 168, 101, 0.45);
    }

    .nav-button button {
      justify-content: flex-start !important;
      width: 100% !important;
      min-height: 44px !important;
      color: #c6d0ca !important;
      background: transparent !important;
      border: 0 !important;
      border-radius: 7px !important;
      box-shadow: none !important;
      font-size: 15px !important;
      font-weight: 500 !important;
      padding: 0 14px !important;
    }

    .nav-button button:hover,
    .active-nav button {
      color: #67e092 !important;
      background: linear-gradient(90deg, rgba(31, 122, 77, 0.32), rgba(31, 122, 77, 0.16)) !important;
    }

    .nav-footer {
      margin-top: auto;
      border: 1px solid var(--border);
      background: rgba(20, 36, 29, 0.9);
      border-radius: 8px;
      padding: 13px;
      color: var(--text);
      font-size: 13px;
    }

    .nav-footer span { color: var(--muted); }

    .workspace {
      padding: 28px 30px 32px !important;
      gap: 14px !important;
      min-width: 0;
    }

    .control-panel, .stats-grid, .compare-grid, .details-panel, .page-panel, .saved-page {
      max-width: 1600px;
    }

    .control-panel {
      border: 1px solid var(--border);
      border-radius: 8px;
      background: rgba(13, 26, 21, 0.78);
      padding: 14px !important;
      gap: 26px !important;
    }

    .source-card, .run-card, .text-panel {
      min-width: 0;
    }

    .run-card {
      justify-content: center;
      padding: 8px 8px 0 !important;
    }

    .run-button button, button.primary {
      background: linear-gradient(180deg, var(--green-2), var(--green)) !important;
      border: 1px solid rgba(143, 214, 163, 0.3) !important;
      color: white !important;
      font-weight: 700 !important;
      border-radius: 7px !important;
      min-height: 58px !important;
      box-shadow: 0 10px 24px rgba(31, 122, 77, 0.22);
    }

    .stats-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(145px, 1fr));
      gap: 12px;
      margin: 0;
    }

    .stat-card {
      display: flex;
      align-items: center;
      gap: 14px;
      min-height: 70px;
      padding: 12px 16px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: rgba(18, 31, 25, 0.9);
      box-sizing: border-box;
    }

    .stat-icon {
      display: grid;
      place-items: center;
      width: 48px;
      height: 48px;
      border-radius: 8px;
      background: var(--green-soft);
      color: #5fe28f;
      font-size: 24px;
      font-weight: 700;
    }

    .stat-value {
      font-size: 22px;
      line-height: 1.15;
      color: var(--text);
      font-weight: 700;
    }

    .stat-label {
      color: var(--muted);
      font-size: 13px;
      margin-top: 4px;
    }

    .compare-grid {
      gap: 14px !important;
    }

    .text-panel, .details-panel {
      border: 1px solid var(--border) !important;
      border-radius: 8px !important;
      background: rgba(18, 31, 25, 0.88) !important;
      padding: 12px !important;
    }

    .page-panel {
      border: 1px solid var(--border) !important;
      border-radius: 8px !important;
      background: rgba(18, 31, 25, 0.88) !important;
      padding: 22px !important;
      min-height: 520px;
    }

    .saved-page {
      border: 1px solid var(--border) !important;
      border-radius: 8px !important;
      background: rgba(18, 31, 25, 0.88) !important;
      padding: 22px !important;
    }

    .panel-header {
      align-items: center;
      gap: 8px !important;
    }

    .panel-header h3 {
      margin: 0 !important;
      font-size: 18px !important;
      color: var(--text) !important;
    }

    .small-button {
      max-width: 116px;
      margin-left: auto;
    }

    .small-button button {
      min-height: 34px !important;
      border-radius: 7px !important;
      background: rgba(18, 31, 25, 0.95) !important;
      border: 1px solid var(--border) !important;
      color: var(--text) !important;
      font-weight: 600 !important;
    }

    .saved-actions {
      align-items: end;
      gap: 12px !important;
    }

    .delete-button button {
      min-height: 44px !important;
      border-radius: 7px !important;
      border: 1px solid rgba(248, 113, 113, 0.7) !important;
      background: rgba(127, 29, 29, 0.72) !important;
      color: #fee2e2 !important;
      font-weight: 700 !important;
    }

    .delete-button button:hover {
      background: rgba(153, 27, 27, 0.9) !important;
    }

    .saved-picker {
      max-height: 360px;
      overflow: auto;
    }

    .saved-picker label {
      font-family: "JetBrains Mono", Consolas, monospace !important;
      font-size: 12px !important;
      line-height: 1.35 !important;
    }

    .saved-downloads {
      margin-top: 10px;
    }

    .settings-grid {
      gap: 18px !important;
      align-items: end;
    }

    .settings-save-button {
      max-width: 220px;
      margin-top: 12px;
    }

    textarea, input, .wrap, .block, .form {
      background-color: rgba(11, 20, 16, 0.96) !important;
      color: var(--text) !important;
      border-color: var(--border) !important;
    }

    .mono-output textarea, .details-code textarea, code {
      font-family: "JetBrains Mono", Consolas, monospace !important;
      font-size: 13px !important;
      line-height: 1.45 !important;
      color: #f3f8f4 !important;
      background: var(--code) !important;
    }

    .details-table {
      min-width: 390px;
    }

    .tabs button.selected {
      color: #8ff0ae !important;
      border-color: var(--green) !important;
      background: rgba(31, 122, 77, 0.16) !important;
    }

    label, .gr-markdown, .markdown, .prose {
      color: var(--text) !important;
    }

    .gr-markdown p {
      color: var(--muted) !important;
    }

    @media (max-width: 1100px) {
      .side-nav {
        display: flex !important;
        width: auto !important;
        flex: 0 0 auto !important;
        min-height: auto;
        padding: 16px !important;
        border-right: 0;
        border-bottom: 1px solid var(--border-soft);
      }
      .brand {
        font-size: 24px;
        margin-bottom: 12px;
      }
      .nav-button button {
        min-height: 36px !important;
      }
      .nav-footer {
        display: none;
      }
      .workspace {
        padding: 18px !important;
      }
      .stats-grid {
        grid-template-columns: repeat(2, minmax(145px, 1fr));
      }
      .control-panel, .compare-grid {
        flex-direction: column !important;
      }
    }
    """


def main() -> int:
    parser = argparse.ArgumentParser(prog="anon-tool-web", description="Launch the Anon Tool web UI.")
    parser.add_argument("--server-name", default="127.0.0.1")
    parser.add_argument("--server-port", type=int, default=7860)
    parser.add_argument("--auth-user", default=None, help="Username required when exposing the UI off localhost.")
    parser.add_argument("--auth-password", default=None, help="Password required when exposing the UI off localhost.")
    args = parser.parse_args()
    launch_app(
        server_name=args.server_name,
        server_port=args.server_port,
        auth_user=args.auth_user,
        auth_password=args.auth_password,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
