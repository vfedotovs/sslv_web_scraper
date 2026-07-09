#!/usr/bin/env python3
"""
ss.lv web scraper module.

Fetches apartment sale listings for a city (via CITY_MAIN_URL env or param),
dynamically discovers the number of result pages, extracts ad data,
and writes a raw report file for the rest of the pipeline.
"""

import re
import os
import sys
import time
from datetime import datetime
import logging
from logging import handlers
from logging.handlers import RotatingFileHandler
import requests
from bs4 import BeautifulSoup
from requests.exceptions import ConnectionError, Timeout


logger = logging.getLogger("web_scraper")
logger.setLevel(logging.INFO)
ws_log_format = logging.Formatter(
    "%(asctime)s [%(levelname)-5.5s] %(name)s : %(funcName)s: %(lineno)d: %(message)s"
)

ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(ws_log_format)
logger.addHandler(ch)

fh = handlers.RotatingFileHandler(
    "web_scraper.log", maxBytes=(1048576 * 5), backupCount=7
)
fh.setFormatter(ws_log_format)
logger.addHandler(fh)


# Get CITY_MAIN_URL from environment variable
CITY_MAIN_URL = os.getenv("CITY_MAIN_URL")
logger.info("Using CITY_MAIN_URL: %s", CITY_MAIN_URL)

# Deplay between scraping each URL 5 sec
# (for Ogre 5 sec x 70 URLs = 350 sec or < 6 min should last )
SCRAPE_DELAY_SEC = 5
URL_LIMIT = 5

# true
SKIP_LAMBDA_FILE = True


def scrape_website(main_url: str = None, report_file: str = "Ogre-raw-data-report.txt"):
    """Main function of module calls all sub-functions.

    Dynamically discovers the total number of pages from the ss.lv pager
    and scrapes all pages (instead of hard-coded first page only).

    Args:
        main_url: Optional override for the city listing URL.
                  Falls back to CITY_MAIN_URL environment variable.
        report_file: Name of the raw report file to write (kept for backward
                     compatibility with existing pipeline; see plan Item 5/6).
    """
    if main_url is None:
        main_url = CITY_MAIN_URL

    logger.info("--- Starting web_scraper module ---")
    logger.info("Using listing URL: %s", main_url)
    logger.info("Extracting BS4 objects")
    remove_old_file(report_file)

    # Fetch first page and determine total pages
    try:
        page_one_resp = requests.get(main_url, timeout=10)
        page_one_resp.raise_for_status()
    except Exception as exc:
        logger.error("Failed to fetch first page %s: %s", main_url, exc)
        return

    page_one_bs_obj = BeautifulSoup(page_one_resp.content, "html.parser")

    total_pages = get_total_pages(page_one_bs_obj)
    logger.info("Detected %s page(s) of listings", total_pages)

    # Collect ad URLs from all pages
    all_msg_urls: list[str] = []
    for page_num in range(1, total_pages + 1):
        page_url = get_page_url(main_url, page_num)
        logger.info("Fetching page %s/%s: %s", page_num, total_pages, page_url)
        try:
            resp = requests.get(page_url, timeout=10)
            resp.raise_for_status()
            bs = BeautifulSoup(resp.content, "html.parser")
            page_urls = find_single_page_urls(bs)
            all_msg_urls.extend(page_urls)
            # Be polite between list pages
            if page_num < total_pages:
                time.sleep(1)
        except Exception as exc:
            logger.warning("Failed to fetch page %s (%s): %s", page_num, page_url, exc)
            # Continue with what we have

    valid_msg_urls = list(dict.fromkeys(all_msg_urls))  # preserve order, remove dups

    logger.info("Found %s parsable message URLs across %s page(s)", len(valid_msg_urls), total_pages)

    logger.info("Extracting data for city apartments for sell task")
    extract_data_from_url(valid_msg_urls, report_file)

    logger.info("Creating file copy in data folder")
    create_file_copy(report_file)
    logger.info("--- Finished web_scraper module ---")


def remove_old_file(filename: str = "Ogre-raw-data-report.txt") -> None:
    """
    Remove the given report file in the current directory if it is older
    than a certain number of days.
    """
    days_old = 1
    file_path = os.path.join(os.getcwd(), filename)
    logger.info("Removing file %s if older than %s day(s)", filename, days_old)
    if os.path.isfile(file_path):
        file_time = datetime.fromtimestamp(os.path.getmtime(file_path))
        now = datetime.now()

        if (now - file_time).days > days_old:
            os.remove(file_path)
            logger.info("Removed %s with success", file_path)
        else:
            logger.info(
                "The file %s is not older than %s day(s) and was not removed.",
                filename,
                str(days_old),
            )
    else:
        logger.info("The file %s does not exist in the current directory.", filename)


def extract_data_from_url(nondup_urls: list, dest_file: str) -> None:
    """Iterate over all first page msg urls extract info from each url and write to file"""
    # msg_url_count = len(nondup_urls)
    # for i in range(msg_url_count):
    for i in range(URL_LIMIT):
        current_msg_url = nondup_urls[i] + "\n"
        logger.info("Started scraping data from message URL %s", str(i + 1))
        table_opt_names = get_msg_table_data(nondup_urls[i], "ads_opt_name")
        if table_opt_names:
            pass
        else:
            logger.warning(
                f"Skipping {nondup_urls[i]} due to repeated connection failures."
            )
        time.sleep(1)
        table_opt_values = get_msg_table_data(nondup_urls[i], "ads_opt")
        if table_opt_values:
            pass
        else:
            logger.warning(
                f"Skipping {nondup_urls[i]} due to repeated connection failures."
            )
        time.sleep(1)
        table_price = get_msg_table_data(nondup_urls[i], "ads_price")
        if table_price:
            pass
        else:
            logger.warning(
                f"Skipping {nondup_urls[i]} due to repeated connection failures."
            )
        try:
            write_line(current_msg_url, dest_file)
            for idx in range(len(table_opt_names) - 1):
                text_line = table_opt_names[idx] + ">" + table_opt_values[idx] + "\n"
                write_line(text_line, dest_file)
        except TypeError as e:
            logger.error(f"Error writing data from {current_msg_url} to file : {e}")

        if not table_price:
            logging.error(
                f"Error writing data from {current_msg_url} to file: table_price is None or empty"
            )
            continue  # Skip further processing for this URL
        try:
            # Assuming table_price is a list and we want the first element
            price_line = "Price:>" + table_price[0] + "\n"
            write_line(price_line, dest_file)
        except (TypeError, IndexError) as e:
            logging.error(f"Error writing data from {current_msg_url} to file: {e}")

        price_line = "Price:>" + table_price[0] + "\n"

        time.sleep(1)
        table_date = get_msg_table_data(nondup_urls[i], "msg_footer")
        if table_date:
            pass
        else:
            logger.warning(
                f"Skipping {nondup_urls[i]} due to repeated connection failures."
            )

        try:
            for date_idx in range(len(table_date)):
                if date_idx == 2:
                    date_str = table_date[date_idx]
                    date_and_time = date_str.replace("Datums:", "")
                    date_clean = date_and_time.split()[0]
                    date_field = "Date:>" + str(date_clean) + "\n"
            write_line(date_field, dest_file)
        except TypeError as e:
            logger.error(f"Error writing data from {current_msg_url} to file : {e}")
        time.sleep(3)


def get_bs_object(page_url: str):
    """Function loads webpage from url and returns bs4 object"""
    page = requests.get(page_url, timeout=10)
    bs_object = BeautifulSoup(page.content, "html.parser")
    return bs_object


def find_single_page_urls(bs_object) -> list:
    """Function iterates over all a sections and gets all href lines
    object: bs4 object
    returns:  list of strings with all message URLs
    """
    urls = []
    for a in bs_object.find_all("a", href=True):
        one_link = "https://ss.lv" + a["href"]
        re_match = re.search("msg", one_link)
        if re_match:
            urls.append(one_link)

    valid_urls = []
    for url in urls:
        if url not in valid_urls:
            valid_urls.append(url)
    return valid_urls


def get_page_url(base_url: str, page_num: int) -> str:
    """Build URL for a given page number on an ss.lv listing.

    ss.lv uses the pattern: <base>/pageN.html for N >= 2
    Page 1 is the base URL itself.
    """
    if not base_url:
        return base_url
    if page_num <= 1:
        return base_url
    # Ensure trailing slash for clean concatenation
    base = base_url.rstrip("/")
    return f"{base}/page{page_num}.html"


def get_total_pages(bs_object: BeautifulSoup, default: int = 1) -> int:
    """Extract the total number of result pages from the ss.lv pager.

    Looks for <button class=navia> and <a class="navi"> elements that contain
    numeric page labels (as observed on ss.lv listing pages).
    Returns the highest page number found, or `default` (usually 1).
    """
    if bs_object is None:
        return default

    page_nums: set[int] = set()

    # Prefer searching inside the known pager container
    pager = bs_object.find("div", class_="td2")
    elements = pager.find_all(["a", "button"]) if pager else bs_object.find_all(["a", "button"])

    for el in elements:
        classes = " ".join(el.get("class", []))
        if "navi" in classes or "navia" in classes:
            text = el.get_text(strip=True)
            if text.isdigit():
                page_nums.add(int(text))

    if page_nums:
        return max(page_nums)
    return default


def get_msg_field_info(msg_url: str, span_id: str):
    """Function finds span id in url and return value"""
    response = requests.get(msg_url, timeout=10)
    data = response.text
    soup = BeautifulSoup(data, "html.parser")
    span = soup.find("span", id=span_id)
    return span.text


def get_msg_table_info(msg_url: str, td_class: str) -> list:
    """Function parses message page and extracts td_class table fields
    Paramters:
    msg_url: message web page link
    td_class: table field name
    returns: str list with table field data
    """
    page = requests.get(msg_url, timeout=10)
    soup = BeautifulSoup(page.content, "html.parser")
    table = soup.find("table", id="page_main")

    table_fields = []

    table_data = table.findAll("td", {"class": td_class})
    for data in table_data:
        tostr = str(data)
        no_front = tostr.split('">', 1)[1]
        name = no_front.split("</", 1)[0]
        clean_name = name.replace("\t", "").replace("\r", "").replace("\n", "")
        table_fields.append(clean_name)
    return table_fields


def get_msg_table_data(msg_url: str, td_class: str, retries=3, backoff_factor=0.3):
    """
    Fetch data from the given URL with a retry mechanism.

    :param msg_url: The URL to scrape.
    :param table_name: The table name to retrieve information from.
    :param retries: Number of retries in case of a connection error.
    :param backoff_factor: The factor by which the delay increases after each retry.
    :return: Response content or None if the request fails.
    """
    attempt = 0
    while attempt < retries:
        try:
            logging.info(f"Attempting to fetch data from {msg_url}")
            page = requests.get(msg_url)
            soup = BeautifulSoup(page.content, "html.parser")
            table = soup.find("table", id="page_main")

            table_fields = []

            table_data = table.findAll("td", {"class": td_class})
            for data in table_data:
                tostr = str(data)
                no_front = tostr.split('">', 1)[1]
                name = no_front.split("</", 1)[0]
                clean_name = name.replace("\t", "").replace("\r", "").replace("\n", "")
                table_fields.append(clean_name)
            return table_fields
        except ConnectionError as e:
            logging.error(
                f"ConnectionError: {e}, retrying in {backoff_factor * (2**attempt)} seconds..."
            )
            attempt += 1
            time.sleep(backoff_factor * (2**attempt))

    logging.error(f"Failed to fetch data from {msg_url} after {retries} attempts.")
    return None


def write_line(text: str, file_name: str) -> None:
    """Append text to end of the file"""
    with open(file_name, "a") as the_file:
        the_file.write(text)


def create_file_copy(report_file: str = "Ogre-raw-data-report.txt") -> None:
    """Creates a dated copy of the report file in the data folder."""
    todays_date = datetime.today().strftime("%Y-%m-%d")
    # Keep legacy "Ogre-" prefix in the archive name for now for compatibility
    # (full city naming is tracked in plan Item 5/7)
    base = report_file.replace(".txt", "")
    dest_file = f"{base}-{todays_date}.txt"
    copy_cmd = f"cp {report_file} local_lambda_raw_scraped_data/" + dest_file
    if not os.path.exists("local_lambda_raw_scraped_data"):
        os.makedirs("local_lambda_raw_scraped_data")
    os.system(copy_cmd)


if __name__ == "__main__":
    scrape_website()
