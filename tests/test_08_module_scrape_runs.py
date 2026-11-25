"""Tests for scrape_runs module (M6 monitoring Item 2)."""
import os
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

# scrape_runs imports "app.wsmodules.config" (container layout), so make
# src/ws importable the same way the ws container does.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "ws"))

from app.wsmodules import scrape_runs


def make_mock_conn(fetchone_result=None, fetchall_result=None):
    """Returns (conn, cursor) mocks wired like psycopg2."""
    cursor = MagicMock()
    cursor.fetchone.return_value = fetchone_result
    cursor.fetchall.return_value = fetchall_result or []
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


def test_record_counts_rejects_unknown_column():
    with pytest.raises(ValueError):
        scrape_runs.record_counts(not_a_column=1)


def test_record_counts_noop_without_active_run():
    scrape_runs._current_run_id = None
    with patch.object(scrape_runs, "_connect") as mock_connect:
        scrape_runs.record_counts(new_ads=5)
        mock_connect.assert_not_called()


def test_record_counts_updates_current_run():
    conn, cursor = make_mock_conn()
    scrape_runs._current_run_id = 42
    try:
        with patch.object(scrape_runs, "_connect", return_value=conn):
            scrape_runs.record_counts(new_ads=3, removed_ads=1)
        sql, params = cursor.execute.call_args[0]
        assert "UPDATE scrape_runs SET" in sql
        assert "new_ads = %s" in sql
        assert "removed_ads = %s" in sql
        assert params == [3, 1, 42]
        conn.commit.assert_called_once()
    finally:
        scrape_runs._current_run_id = None


def test_record_counts_swallows_db_errors():
    """Telemetry must never fail a stage that is otherwise succeeding."""
    scrape_runs._current_run_id = 42
    try:
        with patch.object(scrape_runs, "_connect", side_effect=Exception("db down")):
            scrape_runs.record_counts(new_ads=3)  # must not raise
    finally:
        scrape_runs._current_run_id = None


def test_start_run_sets_current_run_and_returns_id():
    conn, cursor = make_mock_conn(fetchone_result=(7,))
    with patch.object(scrape_runs, "_connect", return_value=conn):
        run_id = scrape_runs.start_run("ogre")
    assert run_id == 7
    assert scrape_runs._current_run_id == 7
    sql, params = cursor.execute.call_args[0]
    assert "INSERT INTO scrape_runs" in sql
    assert params == ("ogre",)
    scrape_runs._current_run_id = None


def test_start_run_raises_on_db_error():
    scrape_runs._current_run_id = None
    with patch.object(scrape_runs, "_connect", side_effect=Exception("db down")):
        with pytest.raises(Exception):
            scrape_runs.start_run("ogre")
    assert scrape_runs._current_run_id is None


def test_finish_run_success_clears_current_run():
    conn, cursor = make_mock_conn()
    scrape_runs._current_run_id = 9
    with patch.object(scrape_runs, "_connect", return_value=conn):
        scrape_runs.finish_run("success")
    assert scrape_runs._current_run_id is None
    sql, params = cursor.execute.call_args[0]
    assert "SET status = %s" in sql
    assert params == ("success", None, None, 9)


def test_finish_run_failed_records_stage_and_error():
    conn, cursor = make_mock_conn()
    scrape_runs._current_run_id = 9
    with patch.object(scrape_runs, "_connect", return_value=conn):
        scrape_runs.finish_run("failed", failed_stage="db_worker", error="boom")
    sql, params = cursor.execute.call_args[0]
    assert params == ("failed", "db_worker", "boom", 9)


def test_finish_run_rejects_invalid_status():
    with pytest.raises(ValueError):
        scrape_runs.finish_run("done")


def test_has_succeeded_today_true_and_false():
    conn, cursor = make_mock_conn(fetchone_result=(1,))
    with patch.object(scrape_runs, "_connect", return_value=conn):
        assert scrape_runs.has_succeeded_today("ogre") is True
    conn2, _ = make_mock_conn(fetchone_result=None)
    with patch.object(scrape_runs, "_connect", return_value=conn2):
        assert scrape_runs.has_succeeded_today("ogre") is False


def test_format_recent_runs_success_and_failed_lines():
    runs = [
        {
            "run_id": 2, "city": "ogre", "status": "success",
            "started_at": datetime(2026, 7, 12, 0, 41), "finished_at": None,
            "failed_stage": None, "error": None,
            "pages_fetched": 2, "urls_discovered": 63, "new_ads": 3,
            "still_listed_ads": 58, "removed_ads": 2,
            "listed_table_rows": 61, "removed_table_rows": 940,
        },
        {
            "run_id": 1, "city": "ogre", "status": "failed",
            "started_at": datetime(2026, 7, 11, 0, 41), "finished_at": None,
            "failed_stage": "db_worker", "error": "connection refused",
            "pages_fetched": 2, "urls_discovered": 60, "new_ads": None,
            "still_listed_ads": None, "removed_ads": None,
            "listed_table_rows": None, "removed_table_rows": None,
        },
    ]
    with patch.object(scrape_runs, "get_recent_runs", return_value=runs):
        text = scrape_runs.format_recent_runs("ogre")
    lines = text.splitlines()
    assert lines[0].startswith("Scrape run history")
    assert "2026-07-12 00:41 ogre success" in lines[1]
    assert "new: 3 still: 58 removed: 2" in lines[1]
    assert "LA TBL rows: 61 RA TBL rows: 940" in lines[1]
    assert "stage: db_worker error: connection refused" in lines[2]
