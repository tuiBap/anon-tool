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

from anon_tool.cli import _read_input, _resolve_input_type, _to_plain_text
from anon_tool.redaction.engine import redact_lines
from anon_tool.rules.policy_profile_opentext import load_profile
from anon_tool.types import InputLine


APP_TITLE = "Anon Tool"
SAVED_OUTPUT_DIR = Path("runs/output/web-ui")


def launch_app(server_name: str = "127.0.0.1", server_port: int = 7860) -> None:
    app = build_app()
    app.launch(
        server_name=server_name,
        server_port=server_port,
        theme=_theme(),
        css=_css(),
        footer_links=[],
    )


def build_app() -> gr.Blocks:
    with gr.Blocks(
        title=APP_TITLE,
        fill_width=True,
    ) as app:
        history_state = gr.State([])
        saved_state = gr.State(_load_saved_outputs())

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
                            output_mode = gr.Dropdown(
                                label="Output mode",
                                choices=["Redacted"],
                                value="Redacted",
                                interactive=False,
                            )
                            anonymize_button = gr.Button("Anonymize", variant="primary", elem_classes=["run-button"])
                            status_line = gr.Markdown("Sensitive fields will be detected and redacted.")

                    stats = gr.HTML(_empty_stats())

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
                                    "Download",
                                    size="sm",
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

                with gr.Group(visible=False, elem_classes=["page-panel"]) as saved_view:
                    gr.Markdown("## Saved Outputs")
                    gr.Markdown("Redacted text outputs are saved locally after each successful run.")
                    saved_table = gr.Dataframe(
                        value=_saved_rows(_load_saved_outputs()),
                        headers=["Time", "Source", "Redactions", "Warnings", "Path"],
                        datatype=["str", "str", "number", "number", "str"],
                        interactive=False,
                    )

                with gr.Group(visible=False, elem_classes=["page-panel"]) as settings_view:
                    gr.Markdown(
                        """
                        ## Settings

                        Current configuration:

                        - Output mode: Redacted
                        - Processing: local only
                        - Supported inputs: PDF, TXT, DOCX, or pasted text
                        - Saved outputs: redacted text files under `runs/output/web-ui`

                        There are no user-editable settings yet.
                        """
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

        anonymize_button.click(
            fn=run_anonymization,
            inputs=[file_input, text_input, output_mode, history_state, saved_state],
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
    output_mode: str,
    history: list[dict[str, Any]] | None,
    saved_outputs: list[dict[str, Any]] | None,
) -> tuple[
    str,
    str,
    str,
    str,
    list[list[str]],
    list[list[str]],
    str | None,
    str,
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[list[Any]],
    list[list[Any]],
]:
    start = time.perf_counter()
    history = history or []
    saved_outputs = saved_outputs or []
    try:
        lines, source_name = _load_source(uploaded_file, pasted_text)
        profile = load_profile(None)
        result = redact_lines(lines, profile)
        elapsed = time.perf_counter() - start

        original_text = _to_plain_text(lines)
        redacted_text = _to_plain_text(result.redacted_lines)
        details = _build_details(result, output_mode, elapsed, source_name)
        details_text = json.dumps(details, indent=2)
        download_path = _write_download(redacted_text, source_name, details)
        record = _run_record(details, download_path)
        history = [record, *history]
        saved_outputs = [record, *[item for item in saved_outputs if item.get("path") != download_path]]
        status = _status_message(result)

        return (
            original_text,
            redacted_text,
            _stats_html(result, output_mode, elapsed),
            details_text,
            _details_rows(details),
            _warning_rows(details),
            download_path,
            status,
            history,
            saved_outputs,
            _history_rows(history),
            _saved_rows(saved_outputs),
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
            _empty_stats(error=True),
            json.dumps(details, indent=2),
            _details_rows(details),
            _warning_rows(details),
            None,
            f"Unable to anonymize input: {exc}",
            history,
            saved_outputs,
            _history_rows(history),
            _saved_rows(saved_outputs),
        )


def _load_source(uploaded_file: Any, pasted_text: str | None) -> tuple[list[InputLine], str]:
    if uploaded_file is not None:
        path = Path(uploaded_file.name if hasattr(uploaded_file, "name") else str(uploaded_file))
        input_type = _resolve_input_type(path, "auto")
        return _read_input(path, input_type), path.name

    text = (pasted_text or "").strip("\ufeff")
    if not text.strip():
        raise ValueError("Upload a PDF, TXT, or DOCX file, or paste text first.")

    raw_lines = text.splitlines() or [text]
    return [InputLine(page=1, line_no=index, text=line) for index, line in enumerate(raw_lines, start=1)], "pasted-text.txt"


def _build_details(result: Any, output_mode: str, elapsed: float, source_name: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "summary": {
            "output_mode": output_mode.lower(),
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


def _write_download(text: str, source_name: str, details: dict[str, Any]) -> str:
    SAVED_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = _safe_stem(source_name)
    timestamp = str(details.get("summary", {}).get("timestamp", datetime.now(timezone.utc).isoformat()))
    compact_ts = re.sub(r"[^0-9T]", "", timestamp.split("+", 1)[0].replace(":", ""))
    output = SAVED_OUTPUT_DIR / f"{compact_ts}-{stem}.anonymized.txt"
    output.write_text(text, encoding="utf-8")
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
    for path in sorted(SAVED_OUTPUT_DIR.glob("*.anonymized.txt"), key=lambda item: item.stat().st_mtime, reverse=True):
        records.append(
            {
                "time": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
                "source": path.name.rsplit(".anonymized.txt", 1)[0],
                "redactions": "",
                "warnings": "",
                "processing_time": "",
                "path": str(path),
            }
        )
    return records


def _details_rows(details: dict[str, Any]) -> list[list[str]]:
    summary = details.get("summary", {})
    rows = [
        ["Schema version", str(details.get("schema_version", ""))],
        ["Output mode", str(summary.get("output_mode", ""))],
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


def _saved_rows(saved_outputs: list[dict[str, Any]]) -> list[list[Any]]:
    return [
        [
            item.get("time", ""),
            item.get("source", ""),
            item.get("redactions", ""),
            item.get("warnings", ""),
            item.get("path", ""),
        ]
        for item in saved_outputs
    ]


def _status_message(result: Any) -> str:
    if result.warnings:
        return f"Completed with {len(result.warnings)} warning(s). Review Details before sharing."
    return "Sensitive fields were detected and redacted."


def _empty_stats(error: bool = False) -> str:
    if error:
        return _stat_cards(
            [
                ("0 redactions", "Detected & redacted", "scan"),
                ("Error", "Review details", "warn"),
                ("Redacted", "Output mode", "doc"),
                ("0.00s", "Processing time", "time"),
            ]
        )
    return _stat_cards(
        [
            ("0 redactions", "Detected & redacted", "scan"),
            ("0 mismatches", "Decoded mismatches", "shield"),
            ("Redacted", "Output mode", "doc"),
            ("0.00s", "Processing time", "time"),
        ]
    )


def _stats_html(result: Any, output_mode: str, elapsed: float) -> str:
    warning_label = "warning" if len(result.warnings) == 1 else "warnings"
    return _stat_cards(
        [
            (f"{len(result.spans)} redactions", "Detected & redacted", "scan"),
            (f"{len(result.warnings)} {warning_label}", "Review in Details", "warn"),
            (output_mode, "Output mode", "doc"),
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

    .control-panel, .stats-grid, .compare-grid, .details-panel, .page-panel {
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
    args = parser.parse_args()
    launch_app(server_name=args.server_name, server_port=args.server_port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
