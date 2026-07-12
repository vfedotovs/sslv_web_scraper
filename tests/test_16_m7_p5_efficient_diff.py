"""Tests for M7 Problem 5: set/dict-based diffing instead of O(N²) loops.

Covers the four refactored db_worker functions:
- compare_df_to_db_hashes (three-way diff via sets)
- extract_new_msg_data (single df pass with hash-set lookup)
- extract_to_remove_msg_data (single table pass with hash-set lookup)
- extract_to_increment_msg_data (single table pass with hash-set lookup)
"""
import os
import sys
import time

import pandas as pd

# container layout imports (app.wsmodules...)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "ws"))

from app.wsmodules import db_worker
from tests.db_mocks import mock_db as _mock_db


URL_TEMPLATE = "https://ss.lv/msg/lv/real-estate/flats/ogre-and-reg/ogre/{}.html"


def make_df(rows):
    """rows: list of (hash, floor, pub_date) tuples -> minimal scraper df."""
    return pd.DataFrame(
        {
            "URL": [URL_TEMPLATE.format(h) for h, _, _ in rows],
            "Room_count": [2 for _ in rows],
            "Floor": [floor for _, floor, _ in rows],
            "Street": ["Brivibas 1" for _ in rows],
            "Pub_date": [pub for _, _, pub in rows],
            "Size_sqm": [50 for _ in rows],
            "Price_in_eur": [50000 for _ in rows],
            "SQ_meter_price": [1000 for _ in rows],
        }
    )


def mock_db(monkeypatch, table_rows):
    """Patch config + psycopg2.connect with the shared fake DB."""
    return _mock_db(monkeypatch, db_worker, table_rows)


# --- compare_df_to_db_hashes -------------------------------------------------

def test_three_way_diff_basic():
    new, existing, removed = db_worker.compare_df_to_db_hashes(
        ["aaaaa", "bbbbb", "ccccc"], ["bbbbb", "ccccc", "ddddd"]
    )
    assert new == ["aaaaa"]
    assert existing == ["bbbbb", "ccccc"]
    assert removed == ["ddddd"]


def test_three_way_diff_empty_db_all_new():
    new, existing, removed = db_worker.compare_df_to_db_hashes(["aaaaa"], [])
    assert (new, existing, removed) == (["aaaaa"], [], [])


def test_three_way_diff_empty_scrape_all_removed():
    new, existing, removed = db_worker.compare_df_to_db_hashes([], ["aaaaa"])
    assert (new, existing, removed) == ([], [], ["aaaaa"])


def test_three_way_diff_preserves_input_order():
    new, existing, removed = db_worker.compare_df_to_db_hashes(
        ["zzzzz", "mmmmm", "aaaaa"], ["ddddd", "bbbbb"]
    )
    assert new == ["zzzzz", "mmmmm", "aaaaa"]
    assert removed == ["ddddd", "bbbbb"]


def test_three_way_diff_is_fast_at_scale():
    """10k vs 10k hashes with ~50% overlap must finish near-instantly.

    The old list-membership version needed ~200M comparisons here and
    took minutes; the set version does 3 linear passes.
    """
    df_hashes = [f"h{i:05d}" for i in range(10_000)]
    db_hashes = [f"h{i:05d}" for i in range(5_000, 15_000)]
    start = time.monotonic()
    new, existing, removed = db_worker.compare_df_to_db_hashes(df_hashes, db_hashes)
    elapsed = time.monotonic() - start
    assert len(new) == 5_000
    assert len(existing) == 5_000
    assert len(removed) == 5_000
    assert elapsed < 2.0


# --- extract_new_msg_data ----------------------------------------------------

def test_extract_new_msg_data_picks_only_new_hashes():
    df = make_df(
        [("aaaaa", "3/5", "01.07.2021"), ("bbbbb", "1/9", "02.07.2021")]
    )
    data = db_worker.extract_new_msg_data(df, ["bbbbb"])
    assert list(data.keys()) == ["bbbbb"]
    row = data["bbbbb"]
    assert row[0] == 2            # Room_count
    assert row[1] == "9"          # house floors
    assert row[2] == "1"          # apt floor
    assert row[3] == 50000        # price
    assert row[7] == "2021.07.02" # rotated pub date


def test_extract_new_msg_data_empty_hash_list_returns_empty():
    df = make_df([("aaaaa", "3/5", "01.07.2021")])
    assert db_worker.extract_new_msg_data(df, []) == {}


def test_extract_new_msg_data_skips_rows_not_in_hash_set():
    """Rows for known ads must not be parsed at all — a malformed Floor
    value on a non-selected row must not break extraction (the old
    per-hash full-frame loop parsed every row every time)."""
    df = make_df(
        [("aaaaa", "no-slash", "01.07.2021"), ("bbbbb", "2/4", "03.07.2021")]
    )
    data = db_worker.extract_new_msg_data(df, ["bbbbb"])
    assert list(data.keys()) == ["bbbbb"]


# --- extract_to_remove_msg_data ----------------------------------------------

LISTED_ROW_A = ("aaaaa", 2, 5, 3, 50000, 50, 1000, "Brivibas 1", "2021.07.01", 10)
LISTED_ROW_B = ("bbbbb", 3, 9, 1, 70000, 70, 1000, "Skolas 2", "2021.07.02", 20)


def test_extract_to_remove_only_matching_hashes(monkeypatch):
    mock_db(monkeypatch, [LISTED_ROW_A, LISTED_ROW_B])
    data = db_worker.extract_to_remove_msg_data(["bbbbb"])
    assert list(data.keys()) == ["bbbbb"]
    row = data["bbbbb"]
    assert row[0] == 3                 # room_count
    assert row[7] == "2021.07.02"      # list_date
    assert row[8] == db_worker.gen_removed_date()
    assert row[9] == 20                # days_listed carried over


def test_extract_to_remove_empty_hashes(monkeypatch):
    mock_db(monkeypatch, [LISTED_ROW_A])
    assert db_worker.extract_to_remove_msg_data([]) == {}


# --- extract_to_increment_msg_data --------------------------------------------

def test_extract_to_increment_only_matching_hashes(monkeypatch):
    mock_db(monkeypatch, [LISTED_ROW_A, LISTED_ROW_B])
    data = db_worker.extract_to_increment_msg_data(["aaaaa"])
    assert data == {"aaaaa": ["2021.07.01", 10]}


def test_extract_to_increment_empty_table_returns_none(monkeypatch):
    mock_db(monkeypatch, [])
    assert db_worker.extract_to_increment_msg_data(["aaaaa"]) is None


def test_extract_to_increment_empty_hashes_returns_none(monkeypatch):
    mock_db(monkeypatch, [LISTED_ROW_A])
    assert db_worker.extract_to_increment_msg_data([]) is None
