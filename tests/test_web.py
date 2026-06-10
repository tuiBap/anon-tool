from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

import pytest

from anon_tool.types import InputLine
from anon_tool.web import (
    _load_sources,
    _cleanup_stale_outputs,
    _load_web_settings,
    refresh_saved_outputs,
    run_anonymization,
    save_web_settings,
    _write_web_settings,
    _write_download,
    _saved_rows,
    _saved_selection_choices,
    _selected_saved_paths,
    _write_combined_download,
    _resolve_auth,
)


def test_web_ui_allows_localhost_without_auth() -> None:
    assert _resolve_auth("127.0.0.1", None, None) is None
    assert _resolve_auth("localhost", None, None) is None


def test_web_ui_requires_auth_for_non_loopback_bind() -> None:
    with pytest.raises(ValueError, match="Refusing to expose"):
        _resolve_auth("0.0.0.0", None, None)


def test_web_ui_accepts_auth_for_non_loopback_bind() -> None:
    assert _resolve_auth("0.0.0.0", "user", "password") == ("user", "password")


def test_web_ui_rejects_partial_auth() -> None:
    with pytest.raises(ValueError, match="Provide both"):
        _resolve_auth("127.0.0.1", "user", None)


def test_web_ui_loads_multiple_uploaded_sources(tmp_path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("alpha\nbeta\n", encoding="utf-8")
    second.write_text("gamma\n", encoding="utf-8")

    sources = _load_sources([str(first), str(second)], None)

    assert [source_name for _, source_name in sources] == ["first.txt", "second.txt"]
    assert [[line.text for line in lines] for lines, _ in sources] == [["alpha", "beta"], ["gamma"]]


def test_web_ui_saved_selection_choices_only_include_latest_existing_files(tmp_path) -> None:
    existing = tmp_path / "kept.anonymized.txt"
    missing = tmp_path / "missing.anonymized.txt"
    existing.write_text("redacted", encoding="utf-8")

    choices = _saved_selection_choices(
        [
            {"time": "2026-05-20T10:00:00+00:00", "source": "kept", "path": str(existing)},
            {"time": "2026-05-20T11:00:00+00:00", "source": "missing", "path": str(missing)},
        ]
    )

    assert choices == [("2026-05-20T10:00:00+00:00 | kept | " + str(existing), str(existing))]
    assert _selected_saved_paths([str(existing), str(missing)]) == [str(existing)]


def test_web_ui_saved_rows_are_newest_first_and_limited(tmp_path) -> None:
    records = []
    for index in range(30):
        path = tmp_path / f"{index}.anonymized.txt"
        path.write_text(str(index), encoding="utf-8")
        records.append({"time": f"2026-05-20T00:{index:02d}:00+00:00", "source": str(index), "path": str(path)})

    rows = _saved_rows(records, limit=25)

    assert len(rows) == 25
    assert rows[0][1] == "29"
    assert rows[-1][1] == "5"


def test_web_ui_combines_selected_saved_outputs(tmp_path, monkeypatch) -> None:
    first = tmp_path / "first.anonymized.txt"
    second = tmp_path / "second.anonymized.txt"
    first.write_text("one", encoding="utf-8")
    second.write_text("two", encoding="utf-8")
    monkeypatch.setattr("anon_tool.web.SAVED_OUTPUT_DIR", tmp_path)

    combined = _write_combined_download([str(first), str(second)])

    text = Path(combined).read_text(encoding="utf-8")
    assert "# first.anonymized.txt\n\none" in text
    assert "# second.anonymized.txt\n\ntwo" in text
    assert Path(combined).suffix == ".md"


def test_web_ui_writes_markdown_by_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("anon_tool.web.SAVED_OUTPUT_DIR", tmp_path)
    details = {"summary": {"timestamp": "2026-06-09T12:00:00+00:00"}}
    lines = [InputLine(page=1, line_no=1, text="redacted")]

    output = Path(_write_download(lines, "case.pdf", details))

    assert output.name.endswith(".anonymized.md")
    assert output.read_text(encoding="utf-8") == (
        "# Sanitized Case Record\n\n## Case Content\n\n### Source Page 1\n\nredacted\n"
    )


def test_dashboard_enables_direct_download_after_anonymization(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("anon_tool.web.SAVED_OUTPUT_DIR", tmp_path)

    result = run_anonymization(None, "Status: Open", "Markdown", [], [])
    download_update = result[6]

    assert download_update["interactive"] is True
    assert Path(download_update["value"]).exists()
    assert Path(download_update["value"]).suffix == ".md"


def test_dashboard_disables_direct_download_when_anonymization_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("anon_tool.web.SAVED_OUTPUT_DIR", tmp_path)

    result = run_anonymization(None, "", "Markdown", [], [])
    download_update = result[6]

    assert download_update["interactive"] is False
    assert download_update["value"] is None


def test_web_settings_default_to_markdown_and_30_day_retention(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("anon_tool.web.WEB_SETTINGS_PATH", tmp_path / "settings.json")

    assert _load_web_settings() == {
        "default_output_format": "Markdown",
        "retention_days": 30,
    }


def test_web_settings_persist_plain_text_and_retention(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr("anon_tool.web.WEB_SETTINGS_PATH", settings_path)

    written = _write_web_settings("Plain text", 90)

    assert written == {"default_output_format": "Plain text", "retention_days": 90}
    assert json.loads(settings_path.read_text(encoding="utf-8")) == written
    assert _load_web_settings() == written


def test_cleanup_removes_only_expired_anonymized_outputs(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("anon_tool.web.SAVED_OUTPUT_DIR", tmp_path)
    now = datetime(2026, 6, 10, tzinfo=timezone.utc)
    expired = tmp_path / "expired.anonymized.md"
    retained = tmp_path / "retained.anonymized.txt"
    unrelated = tmp_path / "notes.txt"
    for path in (expired, retained, unrelated):
        path.write_text(path.name, encoding="utf-8")
    os.utime(expired, ((now - timedelta(days=31)).timestamp(),) * 2)
    os.utime(retained, ((now - timedelta(days=29)).timestamp(),) * 2)
    os.utime(unrelated, ((now - timedelta(days=100)).timestamp(),) * 2)

    deleted, failed = _cleanup_stale_outputs(30, now=now)

    assert (deleted, failed) == (1, 0)
    assert not expired.exists()
    assert retained.exists()
    assert unrelated.exists()


def test_saving_settings_updates_dashboard_and_prunes_saved_state(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    monkeypatch.setattr("anon_tool.web.WEB_SETTINGS_PATH", settings_path)
    monkeypatch.setattr("anon_tool.web.SAVED_OUTPUT_DIR", output_dir)
    expired = output_dir / "expired.anonymized.md"
    expired.write_text("old", encoding="utf-8")
    old_timestamp = (datetime.now(timezone.utc) - timedelta(days=11)).timestamp()
    os.utime(expired, (old_timestamp, old_timestamp))

    result = save_web_settings(
        "Plain text",
        10,
        [{"time": "2026-01-01T00:00:00+00:00", "source": "expired", "path": str(expired)}],
    )

    assert result[0]["value"] == "Plain text"
    assert result[1] == []
    assert "Removed 1 stale output file(s)." in result[7]


def test_refreshing_saved_outputs_applies_retention_policy(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    monkeypatch.setattr("anon_tool.web.WEB_SETTINGS_PATH", settings_path)
    monkeypatch.setattr("anon_tool.web.SAVED_OUTPUT_DIR", output_dir)
    _write_web_settings("Markdown", 10)
    expired = output_dir / "expired.anonymized.txt"
    expired.write_text("old", encoding="utf-8")
    old_timestamp = (datetime.now(timezone.utc) - timedelta(days=11)).timestamp()
    os.utime(expired, (old_timestamp, old_timestamp))

    refreshed = refresh_saved_outputs(
        [{"time": "2026-01-01T00:00:00+00:00", "source": "expired", "path": str(expired)}]
    )

    assert refreshed[0] == []
    assert not expired.exists()
