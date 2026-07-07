from bs4 import BeautifulSoup
from src.ws.app.wsmodules.web_scraper import find_single_page_urls
from src.ws.app.wsmodules.web_scraper import write_line
from src.ws.app.wsmodules.web_scraper import get_msg_field_info
from src.ws.app.wsmodules.web_scraper import create_file_copy
from src.ws.app.wsmodules.web_scraper import find_single_page_urls
from src.ws.app.wsmodules.web_scraper import extract_visits_count
from src.ws.app.wsmodules.web_scraper import get_msg_table_data

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


# === Item 13: Unit tests for visits extraction and parser changes ===
def test_extract_visits_count_from_fixture():
    """Test the dedicated extractor using the footer fixture."""
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "ad_footer_sample.html")
    with open(fixture_path, "r", encoding="utf-8") as f:
        html = f.read()
    soup = BeautifulSoup(html, "html.parser")
    visits = extract_visits_count(soup)
    assert visits == 997


def test_get_msg_table_data_footer_clean_parsing():
    """Test that get_msg_table_data now uses clean BS4 parsing (no HTML remnants)."""
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "ad_footer_sample.html")
    with open(fixture_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    # Mock the requests.get inside get_msg_table_data
    with patch('src.ws.app.wsmodules.web_scraper.requests.get') as mock_get:
        mock_response = create_mock_response(html_content)
        mock_get.return_value = mock_response

        footers = get_msg_table_data("https://example.com", "msg_footer")
        assert footers is not None
        # Check that the visits footer is clean, no <span> tags
        visits_footer = [f for f in footers if "Unikālo" in f][0]
        assert "<span" not in visits_footer
        assert "997" in visits_footer
        assert visits_footer == "Unikālo apmeklējumu skaits: 997"


# === Item 14: Integration-style test for visits in ad page ===
def test_visits_extracted_in_ad_page_context():
    """Integration test using fixture to simulate full ad page extraction for visits."""
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "ad_footer_sample.html")
    with open(fixture_path, "r", encoding="utf-8") as f:
        html = f.read()
    soup = BeautifulSoup(html, "html.parser")

    # Direct test of extractor (core of visits)
    visits = extract_visits_count(soup)
    assert visits == 997

    # Also verify via table data (simulating how footer is fetched)
    with patch('src.ws.app.wsmodules.web_scraper.requests.get') as mock_get:
        mock_response = create_mock_response(html)
        mock_get.return_value = mock_response
        footers = get_msg_table_data("https://example.com/ad", "msg_footer")
        assert any("Unikālo apmeklējumu skaits: 997" in f for f in footers)


# === Item 15: End-to-end pipeline validation (raw -> format -> clean) ===
def test_end_to_end_pipeline_with_unique_visits(tmp_path):
    """E2E test: raw report with UniqueVisits -> pandas_df -> cleaned DF has column with int value."""
    import pandas as pd
    from src.ws.app.wsmodules import data_format_changer as dfc
    from src.ws.app.wsmodules import df_cleaner as dfc_clean

    # Create a minimal raw report file with one ad including UniqueVisits
    raw_content = """https://ss.lv/msg/lv/real-estate/flats/ogre-and-reg/ogre/test.html
Istabas:>2
Platība:>50 m²
Stāvs:>3/9/lifts
Iela:><b>Test Street
Price:>100000 € (2000 €/m²)
Date:>01.07.2026
UniqueVisits:>997
"""
    raw_file = tmp_path / "test_raw_report.txt"
    raw_file.write_text(raw_content, encoding="utf-8")

    # Step 1: format to one-line DF (simulates data_format_changer)
    df = dfc.create_oneline_report(str(raw_file))
    assert df is not None
    assert "Unique_Visits" in df.columns
    assert "UniqueVisits:>997" in df["Unique_Visits"].iloc[0]

    # Step 2: clean (simulates df_cleaner)
    cleaned = dfc_clean.clean_data_frame(df.copy())
    assert "Unique_Visits" in cleaned.columns
    assert cleaned["Unique_Visits"].iloc[0] == 997
    assert pd.api.types.is_integer_dtype(cleaned["Unique_Visits"].dtype) or cleaned["Unique_Visits"].dtype == "Int64"


# === Action item #3: Reusable test fixture for msg_footer (including visits span) ===
def test_load_footer_fixture_has_visits_span():
    """Verifies that the static fixture for Phase 0/1 development contains the expected structure."""
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "ad_footer_sample.html")
    assert os.path.isfile(fixture_path), f"Fixture not found: {fixture_path}"

    with open(fixture_path, "r", encoding="utf-8") as f:
        html = f.read()

    soup = BeautifulSoup(html, "html.parser")

    # Check the visits span exists with expected value from sample
    span = soup.find("span", id="show_cnt_stat")
    assert span is not None, "Missing <span id='show_cnt_stat'> in fixture"
    assert span.get_text(strip=True) == "997"

    # Also ensure we have multiple msg_footer tds as in real pages (at least 4)
    footers = soup.find_all("td", class_="msg_footer")
    assert len(footers) >= 4, "Fixture should contain multiple msg_footer tds like real ss.lv pages"


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
