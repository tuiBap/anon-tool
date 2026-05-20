from __future__ import annotations

from pathlib import Path

import pytest

from anon_tool.web import (
    _load_sources,
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
    assert "===== first.anonymized.txt =====\none" in text
    assert "===== second.anonymized.txt =====\ntwo" in text
