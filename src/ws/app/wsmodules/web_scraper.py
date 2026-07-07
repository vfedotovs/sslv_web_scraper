#!/usr/bin/env python3
"""
This is ss.lv parser project web scraper module.
Module main purpouse is to use ss.lv website as data source and
using requests and bs4 libraries to extract data (price, URL, sqm, street)
from Ogre city apartments for sale advertisements and save
to file Ogre-raw-data-report.txt
"""
import re
import os
import sys
import time
from datetime import datetime
import logging
from logging import handlers
from logging.handlers import RotatingFileHandler
from typing import Optional

import requests
from bs4 import BeautifulSoup
from requests.exceptions import ConnectionError, Timeout


logger = logging.getLogger('web_scraper')
logger.setLevel(logging.INFO)
ws_log_format = logging.Formatter(
    "%(asctime)s [%(levelname)-5.5s] %(name)s : %(funcName)s: %(lineno)d: %(message)s")

ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(ws_log_format)
logger.addHandler(ch)

fh = handlers.RotatingFileHandler(
    'web_scraper.log', maxBytes=(1048576*5), backupCount=7)
fh.setFormatter(ws_log_format)
logger.addHandler(fh)


FLATS_OGRE = "https://www.ss.lv/lv/real-estate/flats/ogre-and-reg/ogre/sell/"
# Deplay between scraping each URL 5 sec
# (for Ogre 5 sec x 70 URLs = 350 sec or < 6 min should last )
SCRAPE_DELAY_SEC = 5

# === Decision from implementation plan (item #1) ===
# Output key for the unique visits counter.
# Chosen: "UniqueVisits:>" (consistent with Date:>, Price:>)
# Optional for initial implementation: write only if value successfully extracted,
# otherwise log a warning.
UNIQUE_VISITS_OUTPUT_KEY = "UniqueVisits:>"


def scrape_website():
    """Main function of module calls all sub-functions"""
    logger.info("--- Starting web_scraper module ---")
    logger.info("Extracting BS4 objects")
    remove_old_file()
    # ogre_object = get_bs_object(FLATS_OGRE)
    # logger.info("Building non-duplicate URL list from BS4 objects")
    # valid_msg_urls = find_single_page_urls(ogre_object)
    # Original code with bug
    # page = requests.get("https://www.ss.lv/lv/real-estate/flats/ogre-and-reg/ogre/sell/")
    # bs_ogre_object = BeautifulSoup(page.content, "html.parser")
    # valid_msg_urls = find_single_page_urls(bs_ogre_object)
    # New static way of extracting data from first three pages
    # TODO: make page count extraction dynamic
    page_one = requests.get(
        "https://www.ss.lv/lv/real-estate/flats/ogre-and-reg/ogre/sell/", timeout=10)
    page_two = requests.get(
        "https://www.ss.lv/lv/real-estate/flats/ogre-and-reg/ogre/sell/page2.html", timeout=10)
    page_three = requests.get(
        "https://www.ss.lv/lv/real-estate/flats/ogre-and-reg/ogre/sell/page3.html", timeout=10)
    # Error handling behavior by ss.lv
    # If non existing page requested for example
    # https://www.ss.lv/lv/real-estate/flats/ogre-and-reg/ogre/sell/page4.html
    # it rederacts to first page
    # https://www.ss.lv/lv/real-estate/flats/ogre-and-reg/ogre/sell/page.html

    page_one_bs_obj = BeautifulSoup(page_one.content, "html.parser")
    page_two_bs_obj = BeautifulSoup(page_two.content, "html.parser")
    page_three_bs_obj = BeautifulSoup(page_three.content, "html.parser")

    page_one_msg_urls = find_single_page_urls(page_one_bs_obj)
    page_two_msg_urls = find_single_page_urls(page_two_bs_obj)
    page_three_msg_urls = find_single_page_urls(page_three_bs_obj)
    combined_urls = page_one_msg_urls + page_two_msg_urls + page_three_msg_urls
    # Since currently there is no dynamic page cound extraction avilable
    # curent behavior of ss.lv if you request none existing page it redirects to
    # first page current quick fix is to remove duplicate entries because of scenario
    # if page 3 is missing an you have requested it will gra  urls from first page and
    # it will end up with duplicate entries
    valid_msg_urls = list(set(combined_urls))

    logger.info("Found %s parsable message URLs", str(len(valid_msg_urls)))
    logger.info(
        "Extracting data for Ogre city apartments "
        "for sell task and saving as Ogre-raw-data-report.txt")
    extract_data_from_url(valid_msg_urls, 'Ogre-raw-data-report.txt')
    logger.info("Creating file Ogre-raw-data-report.txt copy in data folder")
    create_file_copy()
    logger.info("--- Finished web_scraper module ---")


def remove_old_file() -> None:
    """
    Remove the 'Ogre-raw-data-report.txt' file in the current 
    directory if it is older than a certain number of days.
    """
    days_old = 1
    filename = "Ogre-raw-data-report.txt"
    file_path = os.path.join(os.getcwd(), filename)
    logger.info("Removing file %s  as if oloder "
                "than %s  day(s)", filename, days_old)
    if os.path.isfile(file_path):
        file_time = datetime.fromtimestamp(os.path.getmtime(file_path))
        now = datetime.now()

        if (now - file_time).days > days_old:
            os.remove(file_path)
            logger.info("Removed %s  with sucess", file_path)
        else:
            logger.info("The file %s is not older than %s "
                        "day(s) and was not removed.", filename, str(days_old) )
    else:
        logger.info("The file %s does not exist in the "
                    "current directory.", filename)


def extract_data_from_url(nondup_urls: list, dest_file: str) -> None:
    """Iterate over all message urls, extract info from each url and write to file.

    Refactored (items 6+7):
    - Uses per-ad dict for cleaner data structure.
    - Integrates extract_visits_count for UniqueVisits.
    - Writes visits line after Date:> .
    - Handles missing/non-numeric visits gracefully (log + skip).
    """
    msg_url_count = len(nondup_urls)
    for i in range(msg_url_count):
        url = nondup_urls[i]
        current_msg_url = url + "\n"
        logger.info("Started scraping data from message URL %s", str(i + 1))

        # Collect data in a cleaner per-ad structure
        ad_data = {
            "url": url,
            "opt_names": [],
            "opt_values": [],
            "price": None,
            "date": None,
            "unique_visits": None,
        }

        table_opt_names = get_msg_table_data(url, "ads_opt_name")
        ad_data["opt_names"] = table_opt_names or []
        if not table_opt_names:
            logger.warning(f"Skipping opts names for {url} due to repeated connection failures.")
        time.sleep(1)

        table_opt_values = get_msg_table_data(url, "ads_opt")
        ad_data["opt_values"] = table_opt_values or []
        if not table_opt_values:
            logger.warning(f"Skipping opts values for {url} due to repeated connection failures.")
        time.sleep(1)

        table_price = get_msg_table_data(url, "ads_price")
        if table_price:
            ad_data["price"] = table_price[0]
        else:
            logger.warning(f"Skipping price for {url} due to repeated connection failures.")

        try:
            write_line(current_msg_url, dest_file)
            for idx in range(len(ad_data["opt_names"]) - 1):
                text_line = ad_data["opt_names"][idx] + ">" + ad_data["opt_values"][idx] + "\n"
                write_line(text_line, dest_file)
        except (TypeError, IndexError) as e:
            logger.error(f"Error writing data from {current_msg_url} to file : {e}")

        if not ad_data["price"]:
            logging.error(f"Error writing data from {current_msg_url} to file: price is None or empty")
            continue  # Skip further processing for this URL

        try:
            price_line = f"Price:>{ad_data['price']}\n"
            write_line(price_line, dest_file)
        except (TypeError, IndexError) as e:
            logging.error(f"Error writing data from {current_msg_url} to file: {e}")

        time.sleep(1)
        table_date = get_msg_table_data(url, "msg_footer")
        if table_date:
            pass
        else:
            logger.warning(f"Skipping date for {url} due to repeated connection failures.")

        date_clean = None
        try:
            for date_idx in range(len(table_date)):
                if date_idx == 2:
                    date_str = table_date[date_idx]
                    date_and_time = date_str.replace("Datums:", "")
                    date_clean = date_and_time.split()[0]
                    date_field = f"Date:>{date_clean}\n"
                    write_line(date_field, dest_file)
                    ad_data["date"] = date_clean
        except TypeError as e:
            logger.error(f"Error writing data from {current_msg_url} to file : {e}")

        # === Items 6+7: Integrate UniqueVisits output ===
        # Fetch once more for visits (keeps original sleep pattern for rate limiting)
        time.sleep(1)
        visits = None
        try:
            page = requests.get(url, timeout=15)
            soup = BeautifulSoup(page.content, "html.parser")
            visits = extract_visits_count(soup)
            ad_data["unique_visits"] = visits
        except Exception as e:
            logger.warning(f"Failed to fetch/extract visits for {url}: {e}")

        if visits is not None:
            visits_line = f"{UNIQUE_VISITS_OUTPUT_KEY}{visits}\n"
            write_line(visits_line, dest_file)
        else:
            logger.warning(f"Could not extract {UNIQUE_VISITS_OUTPUT_KEY} for {url} (missing or non-numeric)")
        time.sleep(3)


def get_bs_object(page_url: str):
    """ Function loads webpage from url and returns bs4 object"""
    page = requests.get(page_url, timeout=10)
    bs_object = BeautifulSoup(page.content, "html.parser")
    return bs_object


def find_single_page_urls(bs_object) -> list:
    """ Function iterates over all a sections and gets all href lines
    object: bs4 object
    returns:  list of strings with all message URLs
    """
    urls = []
    for a in bs_object.find_all('a', href=True):
        one_link = "https://ss.lv" + a['href']
        re_match = re.search("msg", one_link)
        if re_match:
            urls.append(one_link)

    valid_urls = []
    for url in urls:
        if url not in valid_urls:
            valid_urls.append(url)
    return valid_urls


def get_msg_field_info(msg_url: str, span_id: str):
    """ Function finds span id in url and return value """
    response = requests.get(msg_url, timeout=10)
    data = response.text
    soup = BeautifulSoup(data, "html.parser")
    span = soup.find("span", id=span_id)
    return span.text


def _extract_clean_text(element) -> str:
    """Helper: Use proper BeautifulSoup to extract clean text from an element.
    Replaces the old brittle str(td).split() logic (action item #4).
    Handles nested tags (e.g. <b>, <span>) gracefully.
    """
    if element is None:
        return ""
    # get_text handles nested elements better than string splitting
    text = element.get_text(separator=" ", strip=True)
    # Normalize multiple whitespace
    return " ".join(text.split())


def get_msg_table_info(msg_url: str, td_class: str) -> list:
    """ Function parses message page and extracts td_class table fields
    Paramters:
    msg_url: message web page link
    td_class: table field name
    returns: str list with table field data
    """
    page = requests.get(msg_url, timeout=10)
    soup = BeautifulSoup(page.content, "html.parser")
    table = soup.find('table', id="page_main")

    if table is None:
        return []

    table_fields = []

    table_data = table.find_all('td', {"class": td_class})
    for td in table_data:
        clean_name = _extract_clean_text(td)
        table_fields.append(clean_name)
    return table_fields


def get_msg_table_data(msg_url: str, td_class: str, retries=3, backoff_factor=0.3):
    """
    Fetch data from the given URL with a retry mechanism.
    Refactored (item #4) to use proper BeautifulSoup extraction instead of
    fragile str(td).split('">') logic.

    :param msg_url: The URL to scrape.
    :param td_class: The table cell class to retrieve information from.
    :param retries: Number of retries in case of a connection error.
    :param backoff_factor: The factor by which the delay increases after each retry.
    :return: List of cleaned text values or None if the request fails.
    """
    attempt = 0
    while attempt < retries:
        try:
            logging.info(f"Attempting to fetch data from {msg_url}")
            page = requests.get(msg_url, timeout=15)
            soup = BeautifulSoup(page.content, "html.parser")
            table = soup.find('table', id="page_main")

            if table is None:
                logging.warning(f"No page_main table found for {msg_url}")
                return []

            table_fields = []

            table_data = table.find_all('td', {"class": td_class})
            for td in table_data:
                clean_name = _extract_clean_text(td)
                table_fields.append(clean_name)
            return table_fields
        except ConnectionError as e:
            logging.error(f"ConnectionError: {e}, retrying in {backoff_factor * (2 ** attempt)} seconds...")
            attempt += 1
            time.sleep(backoff_factor * (2 ** attempt))
        except Exception as e:
            logging.error(f"Unexpected error fetching {msg_url}: {e}")
            return None

    logging.error(f"Failed to fetch data from {msg_url} after {retries} attempts.")
    return None


def write_line(text: str, file_name: str) -> None:
    """Append text to end of the file"""
    with open(file_name, 'a') as the_file:
        the_file.write(text)


def create_file_copy() -> None:
    """Creates report file copy in data folder"""
    todays_date = datetime.today().strftime('%Y-%m-%d')
    dest_file = 'Ogre-raw-data-report-' + todays_date + '.txt'
    copy_cmd = 'cp Ogre-raw-data-report.txt local_lambda_raw_scraped_data/' + dest_file
    if not os.path.exists('local_lambda_raw_scraped_data'):
        os.makedirs('local_lambda_raw_scraped_data')
    os.system(copy_cmd)


# === Phase 0: Debug / Instrumentation helper (action item #2) ===
def debug_ad_visits(msg_url: str = None) -> dict:
    """
    Debug helper for extracting and inspecting the unique visits counter.

    Dumps:
    - HTTP response headers (for bot detection analysis)
    - All td.msg_footer elements (text + short html)
    - Attempt to extract #show_cnt_stat value
    - Warning for suspiciously low counts (< 10)

    Usage (from project root):
        python -m src.ws.app.wsmodules.web_scraper --debug [optional-url]

    Returns a dict with the findings (useful in tests too).
    """
    if msg_url is None:
        msg_url = "https://www.ss.lv/msg/lv/real-estate/flats/ogre-and-reg/ogre/adggo.html"

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "lv-LV,lv;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.ss.lv/lv/real-estate/flats/ogre-and-reg/ogre/sell/",
    }

    result = {
        "url": msg_url,
        "status_code": None,
        "headers": {},
        "footers": [],
        "visits": None,
        "warning": None,
    }

    print(f"\n=== DEBUG: Fetching ad page for visits inspection ===")
    print(f"URL: {msg_url}")

    try:
        resp = requests.get(msg_url, headers=headers, timeout=15)
        result["status_code"] = resp.status_code
        result["headers"] = {k: resp.headers.get(k) for k in ["Server", "Date", "Content-Type", "Cache-Control"] if k in resp.headers}

        print(f"HTTP Status: {resp.status_code}")
        print("Relevant response headers:")
        for k, v in result["headers"].items():
            print(f"  {k}: {v}")

        soup = BeautifulSoup(resp.content, "html.parser")
        table = soup.find("table", id="page_main")
        if not table:
            print("WARNING: No <table id=\"page_main\"> found on page")
            return result

        footers = table.find_all("td", {"class": "msg_footer"})
        print(f"\nFound {len(footers)} td.msg_footer elements:")

        for idx, td in enumerate(footers):
            text = td.get_text(separator=" ", strip=True)
            html_snippet = str(td)[:280].replace("\n", " ").replace("\r", "")
            footer_info = {"index": idx, "text": text[:150], "html": html_snippet}
            result["footers"].append(footer_info)

            print(f"  [{idx}] text: {text[:120]}")
            if "Unikālo apmeklējumu skaits" in text or "show_cnt_stat" in str(td):
                span = td.find("span", {"id": "show_cnt_stat"})
                if span:
                    visits = span.get_text(strip=True)
                    result["visits"] = visits
                    print(f"      *** EXTRACTED VISITS: {visits} ***")
                    if visits.isdigit():
                        val = int(visits)
                        if val < 10:
                            result["warning"] = f"suspiciously_low ({val})"
                            print(f"      WARNING: suspiciously_low visits count: {val}")
                else:
                    print(f"      (found 'Unikālo' text but no #show_cnt_stat span)")

        if result["visits"]:
            print(f"\nFinal extracted visits: {result['visits']}")
        else:
            print("\nCould not extract visits count (may need better headers or JS simulation)")

        # Also run the dedicated extractor (item #5) for comparison
        visits2 = extract_visits_count(soup)
        print(f"extract_visits_count(soup) result: {visits2}")
        if visits2 is not None:
            result["visits"] = visits2

        return result

    except Exception as e:
        print(f"DEBUG ERROR: {type(e).__name__}: {e}")
        result["error"] = str(e)
        return result


# === Item #5: Dedicated extractor for unique visits count ===
def extract_visits_count(soup: BeautifulSoup) -> Optional[int]:
    """Reliably extract the 'Unikālo apmeklējumu skaits' value.

    Primary method: find the <span id="show_cnt_stat">
    Fallback: search msg_footer tds for the text and extract the number.

    Returns the integer count or None if not found / unparseable.
    """
    if soup is None:
        return None

    try:
        # Primary: dedicated span (cleanest)
        span = soup.find("span", id="show_cnt_stat")
        if span:
            text = span.get_text(strip=True)
            if text.isdigit():
                return int(text)

        # Fallback using the footer cells (more robust against span changes)
        footers = soup.find_all("td", {"class": "msg_footer"})
        for td in footers:
            text = _extract_clean_text(td)
            if "Unikālo apmeklējumu skaits" in text:
                # Find the first (or only) number in the text
                match = re.search(r"(\d+)", text)
                if match:
                    return int(match.group(1))

        return None
    except Exception as e:
        logging.warning(f"Failed to extract visits count: {e}")
        return None


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--debug":
        url = sys.argv[2] if len(sys.argv) > 2 else None
        debug_ad_visits(url)
    else:
        scrape_website()
