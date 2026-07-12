"""Tests for M7 Problem 2: single fetch per ad detail page."""
import os
import sys
from unittest.mock import patch

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "ws"))

from app.wsmodules import web_scraper

AD_PAGE_HTML = """
<html><body><table id="page_main"><tr>
<td class="ads_opt_name">Istabas:</td><td class="ads_opt">2</td>
<td class="ads_opt_name">Platība:</td><td class="ads_opt">45 m²</td>
<td class="ads_opt_name">Stāvs:</td><td class="ads_opt">2/5</td>
<td class="ads_price">50 000 €</td>
<td class="msg_footer">Kods:#123</td>
<td class="msg_footer">Skatījumi:9</td>
<td class="msg_footer">Datums:01.07.2026 10:15</td>
</tr></table></body></html>
"""

URL_1 = "https://ss.lv/msg/lv/real-estate/flats/ogre-and-reg/ogre/aaaaa.html"
URL_2 = "https://ss.lv/msg/lv/real-estate/flats/ogre-and-reg/ogre/bbbbb.html"


def make_bs():
    return BeautifulSoup(AD_PAGE_HTML, "html.parser")


# --- parse_msg_table_fields ---

def test_parse_opt_names_and_values():
    bs = make_bs()
    assert web_scraper.parse_msg_table_fields(bs, "ads_opt_name") == [
        "Istabas:", "Platība:", "Stāvs:"]
    assert web_scraper.parse_msg_table_fields(bs, "ads_opt") == [
        "2", "45 m²", "2/5"]


def test_parse_price_and_footer():
    bs = make_bs()
    assert web_scraper.parse_msg_table_fields(bs, "ads_price") == ["50 000 €"]
    footer = web_scraper.parse_msg_table_fields(bs, "msg_footer")
    assert footer[2] == "Datums:01.07.2026 10:15"


def test_parse_missing_table_returns_empty():
    bs = BeautifulSoup("<html><body>changed layout</body></html>", "html.parser")
    assert web_scraper.parse_msg_table_fields(bs, "ads_price") == []


# --- extract_data_from_url: one fetch per ad, report format preserved ---

def run_extract(urls, tmp_path, fetch_results=None, url_limit=0):
    dest = str(tmp_path / "report.txt")
    if fetch_results is None:
        fetch_results = [make_bs() for _ in urls]
    with patch.object(web_scraper, "_fetch_page", side_effect=fetch_results) as fetch, \
         patch.object(web_scraper.time, "sleep") as sleep, \
         patch.object(web_scraper, "URL_LIMIT", url_limit):
        web_scraper.extract_data_from_url(urls, dest)
    content = ""
    if os.path.exists(dest):
        with open(dest) as fh:
            content = fh.read()
    return fetch, sleep, content


def test_single_fetch_per_ad(tmp_path):
    fetch, _, _ = run_extract([URL_1, URL_2], tmp_path)
    assert fetch.call_count == 2  # was 8 (4 GETs per ad) before M7 P2


def test_report_format_preserved(tmp_path):
    _, _, content = run_extract([URL_1], tmp_path)
    lines = content.splitlines()
    assert lines[0] == URL_1
    # legacy quirk preserved: last opt_name is dropped (range(len-1))
    assert lines[1] == "Istabas:>2"
    assert lines[2] == "Platība:>45 m²"
    assert lines[3] == "Price:>50 000 €"
    assert lines[4] == "Date:>01.07.2026"
    assert len(lines) == 5


def test_one_configurable_delay_between_ads(tmp_path):
    _, sleep, _ = run_extract([URL_1, URL_2], tmp_path)
    # exactly one pause between 2 ads (was 6s of sleeps per ad before)
    sleep.assert_called_once_with(web_scraper.SCRAPE_DELAY_SEC)


def test_fetch_failure_skips_ad_completely(tmp_path):
    fetch_results = [None, make_bs()]  # first ad unreachable
    _, _, content = run_extract([URL_1, URL_2], tmp_path, fetch_results)
    assert URL_1 not in content  # no partial record
    assert URL_2 in content


def test_missing_price_skips_ad(tmp_path):
    no_price = BeautifulSoup(
        '<table id="page_main"><td class="ads_opt_name">Istabas:</td></table>',
        "html.parser")
    _, _, content = run_extract([URL_1], tmp_path, [no_price])
    assert content == ""


def test_url_limit_caps_fetches(tmp_path):
    fetch, _, _ = run_extract([URL_1, URL_2], tmp_path,
                              fetch_results=[make_bs()], url_limit=1)
    assert fetch.call_count == 1


def test_own_session_created_and_closed_when_none_given(tmp_path):
    dest = str(tmp_path / "report.txt")
    with patch.object(web_scraper.requests, "Session") as session_cls, \
         patch.object(web_scraper, "_fetch_page", return_value=make_bs()), \
         patch.object(web_scraper.time, "sleep"), \
         patch.object(web_scraper, "URL_LIMIT", 0):
        web_scraper.extract_data_from_url([URL_1], dest)
    session_cls.return_value.close.assert_called_once()
