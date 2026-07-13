"""Tests for M7 Problem 9: no full-dataset dumps at INFO level.

INFO must carry counts and summaries; complete hash lists, price lists
and per-ad progress lines belong to DEBUG. At 3000 ads/day the old INFO
dumps churned the 5 MB rotating log handlers several times per run.
"""
import logging
import os
import sys

# container layout imports (app.wsmodules...)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "ws"))

from app.wsmodules import analytics, db_worker, web_scraper
from tests.db_mocks import mock_db


MARKER_HASH = "zzzy1"  # sentinel: must never appear in INFO output


def info_text(caplog):
    return " ".join(
        rec.getMessage() for rec in caplog.records if rec.levelno == logging.INFO
    )


def debug_text(caplog):
    return " ".join(
        rec.getMessage() for rec in caplog.records if rec.levelno == logging.DEBUG
    )


def test_compare_hashes_logs_counts_not_lists(caplog):
    hashes = [f"h{i:04d}" for i in range(200)] + [MARKER_HASH]
    with caplog.at_level(logging.DEBUG, logger="db_worker"):
        db_worker.compare_df_to_db_hashes(hashes, [])
    assert MARKER_HASH not in info_text(caplog)
    assert "201" in info_text(caplog)          # counts survive at INFO
    assert MARKER_HASH in debug_text(caplog)   # full dump available at DEBUG


def test_row_hash_extraction_logs_counts_not_lists(caplog):
    rows = [{
        "URL": f"https://ss.lv/msg/lv/real-estate/flats/riga-region/riga/{MARKER_HASH}.html"
    }]
    with caplog.at_level(logging.DEBUG, logger="db_worker"):
        db_worker.extract_url_hashes_from_rows(rows)
    assert MARKER_HASH not in info_text(caplog)
    assert MARKER_HASH in debug_text(caplog)


def test_db_hash_extraction_logs_counts_not_lists(monkeypatch, caplog):
    row = (MARKER_HASH, 2, 5, 3, 50000, 50, 1000, "Brivibas 1", "2021.07.01", 10)
    mock_db(monkeypatch, db_worker, [row])
    with caplog.at_level(logging.DEBUG, logger="db_worker"):
        db_worker.extract_listed_url_hashes_from_db()
    assert MARKER_HASH not in info_text(caplog)
    assert MARKER_HASH in debug_text(caplog)


def test_delete_logs_count_not_hashes(monkeypatch, caplog):
    mock_db(monkeypatch, db_worker, [])
    with caplog.at_level(logging.DEBUG, logger="db_worker"):
        db_worker.delete_db_listed_table_rows([MARKER_HASH, "aaaaa"])
    assert MARKER_HASH not in info_text(caplog)
    assert "2" in info_text(caplog)
    assert MARKER_HASH in debug_text(caplog)


def test_analytics_price_grouping_logs_counts_not_prices(caplog):
    marker_price = 987654
    rows = [
        {"Room_count": "2", "Price_in_eur": str(marker_price)},
        {"Room_count": "2", "Price_in_eur": "50000"},
    ]
    with caplog.at_level(logging.DEBUG, logger="analytics"):
        analytics.group_prices_by_room(rows)
    assert str(marker_price) not in info_text(caplog)
    assert str(marker_price) in debug_text(caplog)


def test_scraper_per_ad_progress_is_debug(monkeypatch, caplog):
    urls = [
        f"https://ss.lv/msg/lv/real-estate/flats/riga-region/riga/ad{i:03d}.html"
        for i in range(3)
    ]
    # every fetch "fails" -> loop runs without writing files or sleeping
    monkeypatch.setattr(web_scraper, "_fetch_page", lambda session, url: None)
    with caplog.at_level(logging.DEBUG, logger="web_scraper"):
        web_scraper.extract_data_from_url(urls, "unused-report.txt")

    per_ad_records = [
        rec for rec in caplog.records if rec.getMessage().startswith("Scraping ad")
    ]
    assert len(per_ad_records) == 3
    assert all(rec.levelno == logging.DEBUG for rec in per_ad_records)
    # the batch summary stays at INFO
    assert "Processing 3 of 3" in info_text(caplog)
