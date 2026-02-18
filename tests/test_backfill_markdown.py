"""Tests for the backfill-markdown pipeline stage."""

from __future__ import annotations

import json

from src.pipeline import _backfill_markdown_connection


# ---------------------------------------------------------------------------
# Minimal in-memory DB stubs (no psycopg required)
# ---------------------------------------------------------------------------


class _Cursor:
    def __init__(self, db: "_DB") -> None:
        self._db = db
        self._rows: list[tuple] = []

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *_) -> bool:
        return False

    def execute(self, query: str, params: tuple = ()) -> None:
        q = query.strip().upper()
        if q.startswith("SELECT"):
            # Return all rows whose content contains '<' (mirrors the LIKE '%<%' filter)
            self._rows = [
                (sid, meta)
                for sid, meta in self._db.sources.values()
                if "<" in meta.get("content", "")
            ]
        elif q.startswith("UPDATE"):
            # params = (json_markdown, source_id)
            markdown_json, source_id = params
            markdown = json.loads(markdown_json)
            if source_id in self._db.sources:
                _id, meta = self._db.sources[source_id]
                meta = dict(meta)
                meta["content"] = markdown
                self._db.sources[source_id] = (_id, meta)
                self._db.updates.append(source_id)

    def fetchall(self) -> list[tuple]:
        return self._rows


class _DB:
    def __init__(self, rows: list[tuple[int, dict]]) -> None:
        self.sources: dict[int, tuple[int, dict]] = {row[0]: row for row in rows}
        self.updates: list[int] = []
        self.commits: int = 0

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def commit(self) -> None:
        self.commits += 1


def _make_db(*rows: tuple[int, dict]) -> _DB:
    return _DB(list(rows))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_html_source_converted():
    db = _make_db((1, {"content": "<p>Tactical analysis.</p>", "url": "https://example.com"}))
    converted, skipped = _backfill_markdown_connection(db)
    assert converted == 1
    assert skipped == 0
    _, meta = db.sources[1]
    assert "<p>" not in meta["content"]
    assert "Tactical analysis." in meta["content"]


def test_plain_text_source_not_matched():
    # The SELECT query filters with LIKE '%<%', so plain text never reaches the loop.
    db = _make_db((1, {"content": "Plain text, no HTML.", "url": "https://example.com"}))
    converted, skipped = _backfill_markdown_connection(db)
    assert converted == 0
    assert db.updates == []


def test_source_with_no_content_not_matched():
    db = _make_db((1, {"url": "https://example.com"}))
    converted, skipped = _backfill_markdown_connection(db)
    assert converted == 0
    assert db.updates == []


def test_multiple_html_sources_all_converted():
    db = _make_db(
        (1, {"content": "<h2>High Press</h2><p>Analysis.</p>"}),
        (2, {"content": "<ul><li>Item one</li><li>Item two</li></ul>"}),
    )
    converted, skipped = _backfill_markdown_connection(db)
    assert converted == 2

    _, meta1 = db.sources[1]
    assert "## High Press" in meta1["content"]
    assert "Analysis." in meta1["content"]

    _, meta2 = db.sources[2]
    assert "- Item one" in meta2["content"]
    assert "- Item two" in meta2["content"]


def test_script_tags_stripped_during_backfill():
    db = _make_db((1, {"content": "<p>Keep this.</p><script>drop()</script>"}))
    _backfill_markdown_connection(db)
    _, meta = db.sources[1]
    assert "drop()" not in meta["content"]
    assert "Keep this." in meta["content"]


def test_commit_called_at_least_once():
    db = _make_db((1, {"content": "<p>Some content.</p>"}))
    _backfill_markdown_connection(db)
    assert db.commits >= 1


def test_returns_correct_counts():
    db = _make_db(
        (1, {"content": "<p>HTML article.</p>"}),
        (2, {"content": "<em>Also HTML.</em>"}),
    )
    converted, skipped = _backfill_markdown_connection(db)
    assert converted == 2
    assert skipped == 0


def test_batch_commits_fired():
    # With batch_size=1, every converted row triggers an intermediate commit.
    db = _make_db(
        (1, {"content": "<p>One.</p>"}),
        (2, {"content": "<p>Two.</p>"}),
        (3, {"content": "<p>Three.</p>"}),
    )
    _backfill_markdown_connection(db, batch_size=1)
    # 3 intermediate commits (one per batch) + 1 final commit
    assert db.commits >= 4
