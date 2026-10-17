"""Tests for M7 Problem 4: batched SQL, shared connection, one transaction.

Covers:
- executemany-batched inserts (listed_ads / removed_ads)
- single parameterized bulk DELETE (no per-hash string-built statements)
- filtered SELECTs (WHERE url_hash = ANY) instead of full-table fetches
- shared-connection contract: functions given a conn must not commit/close it
- db_worker_main: one connection for the whole run, writes committed
(the batched days_listed UPDATE tests were removed with the whole
increment stage in M7 P3)
"""
import os
import sys
from datetime import datetime, timedelta

# container layout imports (app.wsmodules...)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "ws"))

from app.wsmodules import db_worker
from tests.db_mocks import FakeConn, mock_db


LISTED_ROW_A = ("aaaaa", 2, 5, 3, 50000, 50, 1000, "Brivibas 1", "2021.07.01", 10)
LISTED_ROW_B = ("bbbbb", 3, 9, 1, 70000, 70, 1000, "Skolas 2", "2021.07.02", 20)

NEW_MSG_DATA = {
    "ccccc": [2, "5", "3", 60000, 55, 1090, "Ausekla 3", "2021.07.03", 0],
}
REMOVED_MSG_DATA = {
    "aaaaa": [2, 5, 3, 50000, 50, 1000, "Brivibas 1", "2021.07.01", "2021.07.21", 20],
}


# --- batched inserts ----------------------------------------------------------

def test_insert_listed_uses_single_executemany(monkeypatch):
    conn = mock_db(monkeypatch, db_worker, [])
    db_worker.insert_data_to_listed_table(NEW_MSG_DATA)
    assert len(conn.cur.executemany_calls) == 1
    sql, rows = conn.cur.executemany_calls[0]
    assert "INSERT INTO listed_ads" in sql
    assert rows == [("ccccc", 2, "5", "3", 60000, 55, 1090, "Ausekla 3", "2021.07.03", 0)]
    assert conn.cur.executed == []  # no per-row execute calls
    assert conn.commits == 1  # standalone call commits itself
    assert conn.closed


def test_insert_removed_uses_single_executemany(monkeypatch):
    conn = mock_db(monkeypatch, db_worker, [])
    db_worker.insert_data_to_removed_table(REMOVED_MSG_DATA)
    assert len(conn.cur.executemany_calls) == 1
    sql, rows = conn.cur.executemany_calls[0]
    assert "INSERT INTO removed_ads" in sql
    assert rows[0][0] == "aaaaa"
    assert rows[0][9] == "2021.07.21"  # removed_date
    assert rows[0][10] == 20           # days_listed
    assert conn.commits == 1


def test_insert_with_shared_conn_does_not_commit_or_close():
    conn = FakeConn([])
    db_worker.insert_data_to_listed_table(NEW_MSG_DATA, conn=conn)
    assert len(conn.cur.executemany_calls) == 1
    assert conn.commits == 0
    assert not conn.closed


# --- bulk delete ----------------------------------------------------------------

def test_delete_is_single_parameterized_statement(monkeypatch):
    conn = mock_db(monkeypatch, db_worker, [LISTED_ROW_A, LISTED_ROW_B])
    db_worker.delete_db_listed_table_rows(["aaaaa", "bbbbb"])
    assert len(conn.cur.executed) == 1
    sql, params = conn.cur.executed[0]
    assert sql == "DELETE FROM listed_ads WHERE url_hash = ANY(%s)"
    assert params == (["aaaaa", "bbbbb"],)
    assert conn.commits == 1


def test_delete_does_not_inline_hash_values(monkeypatch):
    """Hashes must travel as bind parameters, never inside the SQL string."""
    conn = mock_db(monkeypatch, db_worker, [])
    evil = "x'; DROP TABLE listed_ads; --"
    db_worker.delete_db_listed_table_rows([evil])
    sql, params = conn.cur.executed[0]
    assert evil not in sql
    assert params == ([evil],)


def test_delete_empty_hash_list_touches_no_db(monkeypatch):
    conn = mock_db(monkeypatch, db_worker, [LISTED_ROW_A])
    db_worker.delete_db_listed_table_rows([])
    assert conn.cur.executed == []
    assert conn.commits == 0


# --- filtered selects -------------------------------------------------------------

def test_extract_to_remove_queries_only_needed_hashes(monkeypatch):
    conn = mock_db(monkeypatch, db_worker, [LISTED_ROW_A, LISTED_ROW_B])
    data = db_worker.extract_to_remove_msg_data(["bbbbb"])
    sql, params = conn.cur.executed[0]
    assert "WHERE url_hash = ANY(%s)" in sql
    assert "SELECT *" not in sql
    assert params == (["bbbbb"],)
    assert list(data.keys()) == ["bbbbb"]


# --- db_worker_main: one connection, one transaction ------------------------------

def test_main_uses_single_connection_and_commits(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    pub_date = (datetime.now() - timedelta(days=3)).strftime("%d.%m.%Y")
    csv_lines = [
        "URL,Room_count,Floor,Street,Pub_date,Size_sqm,Price_in_eur,SQ_meter_price",
        f"https://ss.lv/msg/lv/real-estate/flats/ogre-and-reg/ogre/ccccc.html,"
        f"2,3/5,Ausekla 3,{pub_date},55,60000,1090",
    ]
    (tmp_path / "cleaned-sorted-df.csv").write_text("\n".join(csv_lines) + "\n")

    conn = FakeConn([])
    connect_calls = []

    def fake_connect(**kwargs):
        connect_calls.append(kwargs)
        return conn

    monkeypatch.setattr(db_worker, "config", lambda: {})
    monkeypatch.setattr(db_worker.psycopg2, "connect", fake_connect)
    monkeypatch.setattr(db_worker, "record_counts", lambda **kw: None)

    db_worker.db_worker_main()

    assert len(connect_calls) == 1          # one connection for the whole run
    assert conn.commits == 2                # DDL commit + one run transaction
    assert conn.closed
    insert_calls = [
        c for c in conn.cur.executemany_calls if "INSERT INTO listed_ads" in c[0]
    ]
    assert len(insert_calls) == 1
    assert insert_calls[0][1][0][0] == "ccccc"


def test_main_rolls_back_and_closes_on_failure(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cleaned-sorted-df.csv").write_text(
        "URL,Room_count,Floor,Street,Pub_date,Size_sqm,Price_in_eur,SQ_meter_price\n"
    )

    conn = FakeConn([])
    monkeypatch.setattr(db_worker, "config", lambda: {})
    monkeypatch.setattr(db_worker.psycopg2, "connect", lambda **kw: conn)
    monkeypatch.setattr(db_worker, "record_counts", lambda **kw: None)

    def boom(*args, **kwargs):
        raise RuntimeError("scrape run table unavailable")

    monkeypatch.setattr(db_worker, "load_todays_discovered_hashes", boom)

    try:
        db_worker.db_worker_main()
        raised = False
    except RuntimeError:
        raised = True
    assert raised
    assert conn.rollbacks == 1
    assert conn.closed
