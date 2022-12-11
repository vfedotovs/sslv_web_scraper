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


def test_find_single_page_urls():
    # Test with a bs4 object that contains one URL
    bs_object = create_bs4_object(html_string="<a href='https://ss.lv/msg1'>Test URL</a>")
    assert find_single_page_urls(bs_object) == ["https://ss.lv/msg1"]

    # Test with a bs4 object that contains multiple URLs
    bs_object = create_bs4_object(html_string="<a href='https://ss.lv/msg1'>Test URL 1</a>"
                                              "<a href='https://ss.lv/msg2'>Test URL 2</a>"
                                              "<a href='https://ss.lv/msg3'>Test URL 3</a>")
    assert find_single_page_urls(bs_object) == ["https://ss.lv/msg1", "https://ss.lv/msg2", "https://ss.lv/msg3"]

    # Test with a bs4 object that contains duplicate URLs
    bs_object = create_bs4_object(html_string="<a href='https://ss.lv/msg1'>Test URL 1</a>"
                                              "<a href='https://ss.lv/msg2'>Test URL 2</a>"
                                              "<a href='https://ss.lv/msg1'>Test URL 3</a>")
    assert find_single_page_urls(bs_object) == ["https://ss.lv/msg1", "https://ss.lv/msg2"]

    # Test with a bs4 object that contains no URLs
    bs_object = create_bs4_object(html_string="<p>No URLs in this object</p>")
    assert find_single_page_urls(bs_object) == []


def test_get_msg_field_info():
    # Test with a message URL that contains the specified span ID
    msg_url = "https://ss.lv/msg123"
    span_id = "test-span"
    mock_response = create_mock_response(html_string="<span id='test-span'>Test span text</span>")
    with mock.patch('requests.get', return_value=mock_response):
        assert get_msg_field_info(msg_url, span_id) == "Test span text"

    # Test with a message URL that does not contain the specified span ID
    msg_url = "https://ss.lv/msg456"
    span_id = "test-span"
    mock_response = create_mock_response(html_string="<span id='other-span'>Test span text</span>")
    with mock.patch('requests.get', return_value=mock_response):
        assert get_msg_field_info(msg_url, span_id) == None


def test_write_line():
    # Test with a text string and a file that already exists
    text = "Test line 2"
    file_name = "test_file.txt"
    write_line(text, file_name)
    with open(file_name, 'r') as the_file:
        assert the_file.read() == text

    # Clean up
    os.remove(file_name)


def test_create_file_copy():
    # Test with a file that exists in the current directory
    with open("Ogre-raw-data-report.txt", "w") as the_file:
        the_file.write("Test file")
    create_file_copy()
    assert os.path.exists("data/Ogre-raw-data-report-YYYY-MM-DD.txt")
    with open("data/Ogre-raw-data-report-YYYY-MM-DD.txt", "r") as the_file:
        assert the_file.read() == "Test file"
    os.remove("data/Ogre-raw-data-report-YYYY-MM-DD.txt")
    os.rmdir("data")

    # Test with a file that does not exist in the current directory
    create_file_copy()
    assert not os.path.exists("data/Ogre-raw-data-report-YYYY-MM-DD.txt")
    if os.path.exists("data"):
        os.rmdir("data")

   
def test_find_single_page_urls():
    # Test with a bs4 object that contains one URL
    bs_object = create_bs4_object(html_string="<a href='https://ss.lv/msg1'>Test URL</a>")
    assert find_single_page_urls(bs_object) == ["https://ss.lv/msg1"]

    # Test with a bs4 object that contains multiple URLs
    bs_object = create_bs4_object(html_string="<a href='https://ss.lv/msg1'>Test URL 1</a>"
                                              "<a href='https://ss.lv/msg2'>Test URL 2</a>"
                                              "<a href='https://ss.lv/msg3'>Test URL 3</a>")
    assert find_single_page_urls(bs_object) == ["https://ss.lv/msg1", "https://ss.lv/msg2", "https://ss.lv/msg3"]

    # Test with a bs4 object that contains duplicate URLs
    bs_object = create_bs4_object(html_string="<a href='https://ss.lv/msg1'>Test URL 1</a>"
                                              "<a href='https://ss.lv/msg2'>Test URL 2</a>"
                                              "<a href='https://ss.lv/msg1'>Test URL 3</a>")
    assert find_single_page_urls(bs_object) == ["https://ss.lv/msg1", "https://ss.lv/msg2"]

    # Test with a bs4 object that contains no URLs
    bs_object = create_bs4_object(html_string="<p>No URLs in this object</p>")
    assert find_single_page_urls(bs_object) == []
