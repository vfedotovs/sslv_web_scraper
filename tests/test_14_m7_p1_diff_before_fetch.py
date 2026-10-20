"""Tests for M7 Problem 1: diff-before-fetch (skip ads already in listed_ads)."""
import os
import sys
import time

# container layout imports (app.wsmodules...)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "ws"))

from app.wsmodules import db_worker, web_scraper

URL_A = "https://ss.lv/msg/lv/real-estate/flats/ogre-and-reg/ogre/aaaaa.html"
URL_B = "https://ss.lv/msg/lv/real-estate/flats/ogre-and-reg/ogre/bbbbb.html"
URL_C = "https://ss.lv/msg/lv/real-estate/flats/riga-region/sigulda/ccccc.html"


def test_extract_hash_is_shared_between_scraper_and_db_worker():
    """Both diff sides must use the same hash function."""
    assert web_scraper.extract_hash is db_worker.extract_hash


def test_extract_hash_from_ss_lv_url():
    assert db_worker.extract_hash(URL_A) == "aaaaa"
    assert db_worker.extract_hash(URL_C) == "ccccc"


def test_standalone_fallback_hash_matches_canonical():
    """web_scraper's no-DB fallback formula must agree with db_worker's."""
    def fallback(full_url):
        chunks = full_url.split("/", 9)
        return chunks[9].split(".")[0] if len(chunks) > 9 else full_url
    for url in (URL_A, URL_B, URL_C):
        assert fallback(url) == db_worker.extract_hash(url)


def test_select_new_urls_filters_known_hashes():
    new = web_scraper.select_new_urls([URL_A, URL_B, URL_C], {"aaaaa", "ccccc"})
    assert new == [URL_B]


def test_select_new_urls_all_new_when_db_empty():
    urls = [URL_A, URL_B]
    assert web_scraper.select_new_urls(urls, set()) == urls


def test_select_new_urls_all_known_returns_empty():
    assert web_scraper.select_new_urls([URL_A], {"aaaaa"}) == []


def test_write_discovered_urls_roundtrip(tmp_path):
    dest = str(tmp_path / "discovered-urls.txt")
    web_scraper.write_discovered_urls([URL_A, URL_B], dest_file=dest)
    hashes = db_worker.load_todays_discovered_hashes(dest)
    assert hashes == ["aaaaa", "bbbbb"]


def test_load_discovered_hashes_missing_file_returns_none(tmp_path):
    assert db_worker.load_todays_discovered_hashes(str(tmp_path / "nope.txt")) is None


def test_load_discovered_hashes_stale_file_returns_none(tmp_path):
    dest = str(tmp_path / "discovered-urls.txt")
    web_scraper.write_discovered_urls([URL_A], dest_file=dest)
    yesterday = time.time() - 26 * 3600
    os.utime(dest, (yesterday, yesterday))
    assert db_worker.load_todays_discovered_hashes(dest) is None


def test_load_discovered_hashes_skips_blank_lines(tmp_path):
    dest = str(tmp_path / "discovered-urls.txt")
    with open(dest, "w") as fh:
        fh.write(URL_A + "\n\n" + URL_B + "\n")
    assert db_worker.load_todays_discovered_hashes(dest) == ["aaaaa", "bbbbb"]
