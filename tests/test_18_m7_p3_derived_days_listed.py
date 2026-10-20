"""Tests for M7 Problem 3: days_listed derived at read time, daily
increment stage deleted.

Covers:
- calc_days_listed correctness, including ads listed >999 days (the old
  str(timedelta) parsing silently returned 0 for those)
- get_days_listed_count (insert-time initial value) same fix
- extract_to_remove_msg_data derives days_listed from list_date instead
  of trusting the stored (possibly stale) column value
- the increment stage is gone: no UPDATE of days_listed anywhere in a
  full db_worker_main run
"""
import os
import sys
from datetime import datetime, timedelta

# container layout imports (app.wsmodules...)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "ws"))

from app.wsmodules import db_worker
from tests.db_mocks import FakeConn, mock_db


def test_calc_days_listed_basic():
    assert db_worker.calc_days_listed("2021.07.01", until=datetime(2021, 7, 21)) == 20


def test_calc_days_listed_same_day_is_zero():
    assert db_worker.calc_days_listed("2021.07.21", until=datetime(2021, 7, 21)) == 0


def test_calc_days_listed_over_999_days():
    """The old str(timedelta) parsing returned 0 past 999 days."""
    assert db_worker.calc_days_listed("2021.01.01", until=datetime(2024, 1, 1)) == 1095


def test_calc_days_listed_defaults_to_today():
    ten_days_ago = (datetime.now() - timedelta(days=10)).strftime("%Y.%m.%d")
    assert db_worker.calc_days_listed(ten_days_ago) == 10


def test_get_days_listed_count_over_999_days():
    """Insert-time initial value must survive >999 days too (dd.mm.yyyy)."""
    long_ago = (datetime.now() - timedelta(days=1500)).strftime("%d.%m.%Y")
    assert db_worker.get_days_listed_count(long_ago) == 1500


def test_get_days_listed_count_same_day_is_zero():
    today = datetime.now().strftime("%d.%m.%Y")
    assert db_worker.get_days_listed_count(today) == 0


def test_removed_ad_days_listed_ignores_stale_stored_value(monkeypatch):
    """Stored days_listed=10 is stale; the derived value from list_date
    must be used when the ad moves to removed_ads."""
    list_date = (datetime.now() - timedelta(days=42)).strftime("%Y.%m.%d")
    stale_row = ("aaaaa", 2, 5, 3, 50000, 50, 1000, "Brivibas 1", list_date, 10)
    mock_db(monkeypatch, db_worker, [stale_row])
    data = db_worker.extract_to_remove_msg_data(["aaaaa"])
    assert data["aaaaa"][9] == 42          # derived, not the stored 10
    assert data["aaaaa"][8] == db_worker.gen_removed_date()


def test_increment_stage_functions_are_gone():
    assert not hasattr(db_worker, "extract_to_increment_msg_data")
    assert not hasattr(db_worker, "update_dlv_in_db_table")
    assert not hasattr(db_worker, "calc_valid_dlv")
    assert not hasattr(db_worker, "update_single_column_value")


def test_main_run_issues_no_days_listed_updates(monkeypatch, tmp_path):
    """A full run with still-listed ads must not UPDATE days_listed."""
    monkeypatch.chdir(tmp_path)
    # DB knows one ad; today's discovered set contains the same ad and no
    # new ones -> pure "still listed" day, which previously triggered the
    # increment stage.
    list_date = (datetime.now() - timedelta(days=30)).strftime("%Y.%m.%d")
    row = ("aaaaa", 2, 5, 3, 50000, 50, 1000, "Brivibas 1", list_date, 5)
    (tmp_path / "cleaned-sorted-df.csv").write_text(
        "URL,Room_count,Floor,Street,Pub_date,Size_sqm,Price_in_eur,SQ_meter_price\n"
    )
    (tmp_path / "discovered-urls.txt").write_text(
        "https://ss.lv/msg/lv/real-estate/flats/ogre-and-reg/ogre/aaaaa.html\n"
    )

    conn = FakeConn([row])
    monkeypatch.setattr(db_worker, "config", lambda: {})
    monkeypatch.setattr(db_worker.psycopg2, "connect", lambda **kw: conn)
    monkeypatch.setattr(db_worker, "record_counts", lambda **kw: None)

    db_worker.db_worker_main()

    all_sql = [sql for sql, _ in conn.cur.executed] + [
        sql for sql, _ in conn.cur.executemany_calls
    ]
    assert not any("UPDATE" in sql.upper() for sql in all_sql)
    assert conn.commits == 2  # DDL + run transaction, nothing else
    assert conn.closed
