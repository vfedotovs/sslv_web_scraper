from bs4 import BeautifulSoup
from src.ws.app.wsmodules.web_scraper import find_single_page_urls
from src.ws.app.wsmodules.web_scraper import write_line
from src.ws.app.wsmodules.web_scraper import get_msg_field_info
from src.ws.app.wsmodules.web_scraper import create_file_copy
from src.ws.app.wsmodules.web_scraper import find_single_page_urls

import requests
import os
from unittest.mock import patch
from unittest.mock import Mock
mock = Mock()


def create_bs4_object(html_string: str) -> BeautifulSoup:
    """
    Function creates a bs4 object from an HTML string
    html_string: str - string containing the HTML code
    returns: BeautifulSoup object
    """
    return BeautifulSoup(html_string, 'html.parser')


def create_mock_response(html_string: str, status_code: int = 200) -> requests.Response:
    """
    Function creates a mock requests.Response object
    html_string: str - string containing the HTML code
    status_code: int - HTTP status code to be returned by the mock response
    returns: requests.Response object
    """
    mock_response = requests.Response()
    mock_response._content = html_string.encode()
    mock_response.status_code = status_code
    return mock_response


# def test_find_single_page_urls():
#     # Test with a bs4 object that contains one URL
#     bs_object = create_bs4_object(html_string="<a href='https://ss.lv/msg1'>Test URL</a>")
#     assert find_single_page_urls(bs_object) == ["https://ss.lv/msg1"]
#
#     # Test with a bs4 object that contains multiple URLs
#     bs_object = create_bs4_object(html_string="<a href='https://ss.lv/msg1'>Test URL 1</a>"
#                                               "<a href='https://ss.lv/msg2'>Test URL 2</a>"
#                                               "<a href='https://ss.lv/msg3'>Test URL 3</a>")
#     assert find_single_page_urls(bs_object) == ["https://ss.lv/msg1", "https://ss.lv/msg2", "https://ss.lv/msg3"]
#
#     # Test with a bs4 object that contains duplicate URLs
#     bs_object = create_bs4_object(html_string="<a href='https://ss.lv/msg1'>Test URL 1</a>"
#                                               "<a href='https://ss.lv/msg2'>Test URL 2</a>"
#                                               "<a href='https://ss.lv/msg1'>Test URL 3</a>")
#     assert find_single_page_urls(bs_object) == ["https://ss.lv/msg1", "https://ss.lv/msg2"]
#
#     # Test with a bs4 object that contains no URLs
#     bs_object = create_bs4_object(html_string="<p>No URLs in this object</p>")
#     assert find_single_page_urls(bs_object) == []


# def test_get_msg_field_info():
#     # Test with a message URL that contains the specified span ID
#     msg_url = "https://ss.lv/msg123"
#     span_id = "test-span"
#     mock_response = create_mock_response(html_string="<span id='test-span'>Test span text</span>")
#     with mock.patch('requests.get', return_value=mock_response):
#         assert get_msg_field_info(msg_url, span_id) == "Test span text"
#
#     # Test with a message URL that does not contain the specified span ID
#     msg_url = "https://ss.lv/msg456"
#     span_id = "test-span"
#     mock_response = create_mock_response(html_string="<span id='other-span'>Test span text</span>")
#     with mock.patch('requests.get', return_value=mock_response):
#         assert get_msg_field_info(msg_url, span_id) == None


def test_write_line():
    # Test with a text string and a file that already exists
    text = "Test line 2"
    file_name = "test_file.txt"
    write_line(text, file_name)
    with open(file_name, 'r') as the_file:
        assert the_file.read() == text

    # Clean up
    os.remove(file_name)


# def test_create_file_copy():
#     # Test with a file that exists in the current directory
#     with open("Ogre-raw-data-report.txt", "w") as the_file:
#         the_file.write("Test file")
#     create_file_copy()
#     assert os.path.exists("data/Ogre-raw-data-report-YYYY-MM-DD.txt")
#     with open("data/Ogre-raw-data-report-YYYY-MM-DD.txt", "r") as the_file:
#         assert the_file.read() == "Test file"
#     os.remove("data/Ogre-raw-data-report-YYYY-MM-DD.txt")
#     os.rmdir("data")
#
#     # Test with a file that does not exist in the current directory
#     create_file_copy()
#     assert not os.path.exists("data/Ogre-raw-data-report-YYYY-MM-DD.txt")
#     if os.path.exists("data"):
#         os.rmdir("data")

   
# def test_find_single_page_urls():
#     # Test with a bs4 object that contains one URL
#     bs_object = create_bs4_object(html_string="<a href='https://ss.lv/msg1'>Test URL</a>")
#     assert find_single_page_urls(bs_object) == ["https://ss.lv/msg1"]
#
#     # Test with a bs4 object that contains multiple URLs
#     bs_object = create_bs4_object(html_string="<a href='https://ss.lv/msg1'>Test URL 1</a>"
#                                               "<a href='https://ss.lv/msg2'>Test URL 2</a>"
#                                               "<a href='https://ss.lv/msg3'>Test URL 3</a>")
#     assert find_single_page_urls(bs_object) == ["https://ss.lv/msg1", "https://ss.lv/msg2", "https://ss.lv/msg3"]
#
#     # Test with a bs4 object that contains duplicate URLs
#     bs_object = create_bs4_object(html_string="<a href='https://ss.lv/msg1'>Test URL 1</a>"
#                                               "<a href='https://ss.lv/msg2'>Test URL 2</a>"
#                                               "<a href='https://ss.lv/msg1'>Test URL 3</a>")
#     assert find_single_page_urls(bs_object) == ["https://ss.lv/msg1", "https://ss.lv/msg2"]
#
#     # Test with a bs4 object that contains no URLs
#     bs_object = create_bs4_object(html_string="<p>No URLs in this object</p>")
#     assert find_single_page_urls(bs_object) == []


# --- New tests for dynamic page count (M6) ---

from src.ws.app.wsmodules.web_scraper import (
    get_total_pages,
    get_page_url,
    derive_city_slug,
    scrape_website,
    find_single_page_urls,
)


JURMALA_PAGER_HTML = """
<div align=center class=td2 nowrap>
  <a name="nav_id" rel="prev" class="navi" href="/lv/real-estate/flats/jurmala/sell/page6.html">Iepriekšējie</a>
  &nbsp;&nbsp;
  <button onclick="return false;" class=navia>1</button>
  <a name="nav_id" rel="next" class="navi" href="/lv/real-estate/flats/jurmala/sell/page2.html">2</a>
  <a name="nav_id" rel="next" class="navi" href="/lv/real-estate/flats/jurmala/sell/page3.html">3</a>
  <a name="nav_id" rel="next" class="navi" href="/lv/real-estate/flats/jurmala/sell/page4.html">4</a>
  <a name="nav_id" rel="next" class="navi" href="/lv/real-estate/flats/jurmala/sell/page5.html">5</a>
  <a name="nav_id" rel="next" class="navi" href="/lv/real-estate/flats/jurmala/sell/page6.html">6</a>
  &nbsp;&nbsp;
  <a name="nav_id" rel="next" class="navi" href="/lv/real-estate/flats/jurmala/sell/page2.html">Nākamie</a>
</div>
"""

OGRE_PAGER_HTML = """
<div align=center class=td2 nowrap>
  <a name="nav_id" rel="prev" class="navi" href="/lv/real-estate/flats/ogre-and-reg/ogre/sell/page2.html">Iepriekšējie</a>
  &nbsp;&nbsp;
  <button onclick="return false;" class=navia>1</button>
  <a name="nav_id" rel="next" class="navi" href="/lv/real-estate/flats/ogre-and-reg/ogre/sell/page2.html">2</a>
  &nbsp;&nbsp;
  <a name="nav_id" rel="next" class="navi" href="/lv/real-estate/flats/ogre-and-reg/ogre/sell/page2.html">Nākamie</a>
</div>
"""

SINGLE_PAGE_HTML = """
<html><body>
  <div align=center class=td2 nowrap>
    <button onclick="return false;" class=navia>1</button>
  </div>
  <table><a href="/msg/lv/real-estate/flats/ogre/fake1.html">ad1</a></table>
</body></html>
"""

NO_PAGER_HTML = """
<html><body>
  <table><a href="/msg/lv/real-estate/flats/ogre/fake1.html">ad1</a></table>
</body></html>
"""


def test_get_page_url():
    base = "https://www.ss.lv/lv/real-estate/flats/jurmala/sell/"
    assert get_page_url(base, 1) == base
    assert get_page_url(base, 2) == "https://www.ss.lv/lv/real-estate/flats/jurmala/sell/page2.html"
    assert get_page_url(base.rstrip("/"), 6) == "https://www.ss.lv/lv/real-estate/flats/jurmala/sell/page6.html"
    assert get_page_url(base, 0) == base
    assert get_page_url("", 3) == "/page3.html"


def test_get_total_pages_jurmala():
    bs = create_bs4_object(JURMALA_PAGER_HTML)
    assert get_total_pages(bs) == 6


def test_get_total_pages_ogre():
    bs = create_bs4_object(OGRE_PAGER_HTML)
    assert get_total_pages(bs) == 2


def test_get_total_pages_single_page():
    bs = create_bs4_object(SINGLE_PAGE_HTML)
    assert get_total_pages(bs) == 1


def test_get_total_pages_no_pager():
    bs = create_bs4_object(NO_PAGER_HTML)
    assert get_total_pages(bs) == 1
    assert get_total_pages(bs, default=1) == 1


def test_get_total_pages_from_fixture_files():
    """Use real downloaded fixture files (more realistic).

    Fixtures were captured during Phase 1 Item 1 research against
    all cities listed in config/cities.yaml.
    """
    for fname, expected in [
        ("tests/fixtures/sslv/jurmala-page1.html", 6),
        ("tests/fixtures/sslv/ogre-page1.html", 2),
        # marupes-pag also ~2 pages (see research)
    ]:
        with open(fname, encoding="utf-8", errors="ignore") as f:
            html = f.read()
        bs = create_bs4_object(html)
        got = get_total_pages(bs)
        assert got == expected, f"{fname} expected {expected} got {got}"


# --- Tests for Item 5 city slug derivation (Phase 1) ---

def test_derive_city_slug():
    assert derive_city_slug("https://www.ss.lv/lv/real-estate/flats/jurmala/sell/") == "jurmala"
    assert derive_city_slug("https://www.ss.lv/lv/real-estate/flats/ogre-and-reg/ogre/sell/") == "ogre"
    assert derive_city_slug("https://www.ss.lv/lv/real-estate/flats/riga-region/sigulda/sell/") == "sigulda"
    assert derive_city_slug("https://www.ss.lv/lv/real-estate/flats/riga-region/marupes-pag/sell/") == "marupes_pag"
    assert derive_city_slug("https://www.ss.lv/lv/real-estate/flats/riga-region/salaspils/sell/") == "salaspils"
    assert derive_city_slug("https://www.ss.lv/lv/real-estate/flats/riga-region/adazu-nov/sell/") == "adazu_nov"
    assert derive_city_slug(None) == "city"
    assert derive_city_slug("") == "city"


# --- Revived + new tests for Item 9 (Phase 2) ---

from unittest.mock import patch, MagicMock


def test_find_single_page_urls_basic():
    """Revived basic test for find_single_page_urls."""
    bs_object = create_bs4_object(html_string="<a href='/msg/lv/real-estate/flats/jurmala/fake1.html'>Ad 1</a>")
    urls = find_single_page_urls(bs_object)
    assert len(urls) == 1
    assert urls[0].endswith("fake1.html")


def test_find_single_page_urls_dedup():
    """Revived dedup test."""
    html = (
        "<a href='/msg/lv/real-estate/flats/jurmala/a1.html'>1</a>"
        "<a href='/msg/lv/real-estate/flats/jurmala/a2.html'>2</a>"
        "<a href='/msg/lv/real-estate/flats/jurmala/a1.html'>1 again</a>"
    )
    bs_object = create_bs4_object(html_string=html)
    urls = find_single_page_urls(bs_object)
    assert len(urls) == 2


@patch("src.ws.app.wsmodules.web_scraper.requests.Session")
@patch("src.ws.app.wsmodules.web_scraper.extract_data_from_url")
@patch("src.ws.app.wsmodules.web_scraper.remove_old_file")
@patch("src.ws.app.wsmodules.web_scraper.create_file_copy")
def test_scrape_website_multi_page_mocked(mock_create, mock_remove, mock_extract, mock_session_class):
    """Integration-style test for multi-page scraping (Item 9 / Phase 2).

    Mocks the session + heavy side-effect functions so we test the page discovery + collection logic cleanly.
    """
    # Use a 2-page pager so detection reports only 2 pages (not the 6 from JURMALA_PAGER_HTML)
    TWO_PAGE_PAGER = """
    <div align=center class=td2 nowrap>
      <button onclick="return false;" class=navia>1</button>
      <a name="nav_id" rel="next" class="navi" href="/lv/real-estate/flats/jurmala/sell/page2.html">2</a>
    </div>
    """

    page1_html = TWO_PAGE_PAGER + '<a href="/msg/lv/real-estate/flats/jurmala/ad1.html">ad1</a>'
    page2_html = '<a href="/msg/lv/real-estate/flats/jurmala/ad2.html">ad2</a>'

    mock_resp1 = MagicMock()
    mock_resp1.content = page1_html.encode()
    mock_resp1.raise_for_status = MagicMock()

    mock_resp2 = MagicMock()
    mock_resp2.content = page2_html.encode()
    mock_resp2.raise_for_status = MagicMock()

    mock_session = MagicMock()
    mock_session.get.side_effect = [mock_resp1, mock_resp2]
    mock_session.headers = {}
    mock_session_class.return_value = mock_session

    # Force no URL limit for the test
    with patch("src.ws.app.wsmodules.web_scraper.URL_LIMIT", 0):
        scrape_website(main_url="https://www.ss.lv/lv/real-estate/flats/jurmala/sell/")

    # Should have fetched exactly two list pages (page 1 for detection + page 2)
    assert mock_session.get.call_count == 2

    # extract_data_from_url should have been called with 2 URLs (ad1 + ad2)
    assert mock_extract.called
    called_urls = mock_extract.call_args[0][0]
    assert len(called_urls) == 2
    assert any("ad1" in u for u in called_urls)
    assert any("ad2" in u for u in called_urls)

