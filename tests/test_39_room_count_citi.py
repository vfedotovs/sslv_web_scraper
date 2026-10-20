"""Hotfix: non-numeric room count ("Istabas: Citi") must not fail db_worker.

2026-10-20 staging: jurmala ad bdpioh had room count "Citi". It reached the
integer room_count column as a string, Postgres rejected the batched insert
("invalid input syntax for type integer: "Citi"") and the run failed at
stage db_worker. These tests pin the fix: the ad is kept, room_count is NULL.
"""
import os
import sys

# container layout imports (app.wsmodules...)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "ws"))

from app.wsmodules import db_worker
from tests.db_mocks import mock_db


# The cleaned-sorted-df.csv rows from the failing staging run (trimmed).
CLEANED_CSV = (
    ",URL,Room_count,Floor,Street,Pub_date,Size_sqm,Price_in_eur,SQ_meter_price\n"
    "0,https://ss.lv/msg/lv/real-estate/flats/jurmala/kauguri/fcddb.html,"
    "2,3/5,Talsu šoseja 1,19.10.2026,50,60000,1200.0\n"
    "2,https://ss.lv/msg/lv/real-estate/flats/jurmala/dzintari/bdpioh.html,"
    "Citi,4/4,Grīšļa iela 5,19.10.2026,553,350000,632.91\n"
)


def load_cleaned_df(tmp_path):
    path = tmp_path / "jurmala-cleaned-sorted-df.csv"
    path.write_text(CLEANED_CSV, encoding="utf-8")
    return db_worker.load_csv_to_df(str(path))


def test_to_room_count_numeric_values():
    assert db_worker.to_room_count("2") == 2
    assert db_worker.to_room_count(" 3 ") == 3
    assert db_worker.to_room_count(4) == 4
    assert db_worker.to_room_count(5.0) == 5  # pandas float column (NaN present)


def test_to_room_count_non_numeric_is_none():
    assert db_worker.to_room_count("Citi") is None
    assert db_worker.to_room_count("") is None
    assert db_worker.to_room_count(None) is None
    assert db_worker.to_room_count(float("nan")) is None
    assert db_worker.to_room_count("2.5") is None


def test_citi_ad_is_kept_with_null_room_count(tmp_path):
    df = load_cleaned_df(tmp_path)
    data = db_worker.extract_new_msg_data(df, ["fcddb", "bdpioh"])
    assert data["bdpioh"][0] is None
    assert data["bdpioh"][3] == 350000  # rest of the ad is unchanged
    assert data["fcddb"][0] == 2


def test_citi_ad_inserts_null_not_string(monkeypatch, tmp_path):
    conn = mock_db(monkeypatch, db_worker, [])
    df = load_cleaned_df(tmp_path)
    data = db_worker.extract_new_msg_data(df, ["fcddb", "bdpioh"])
    db_worker.insert_data_to_listed_table(data)
    _, rows = conn.cur.executemany_calls[0]
    room_counts = {row[0]: row[1] for row in rows}
    assert room_counts == {"fcddb": 2, "bdpioh": None}
