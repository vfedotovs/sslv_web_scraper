#!/usr/bin/env python3
"""
ss.lv web scraper module.

Fetches apartment sale listings for a city (via CITY_MAIN_URL env or param),
dynamically discovers the number of result pages (Phase 1 Items 2-4),
and writes a raw report file.

Phase 1 Item 5 support: can produce city-prefixed files such as
"jurmala-raw-data-report.txt" (via city_slug or auto-derivation from URL)
instead of the previous hard-coded "Ogre-raw-data-report.txt".

See derive_city_slug(), get_total_pages(), get_page_url(), and scrape_website().
"""

# --- Phase 1 Item 1: Pagination research notes ---
# All cities in config/cities.yaml use the same pager structure:
#   <div class=td2> ... <button class=navia>1</button> <a class="navi">2</a> ...
#
# Observed last page numbers (research performed 2026-07):
#   jurmala     : 6
#   marupes-pag : ~2
#   ogre        : ~2
#   sigulda     : ~1
#   salaspils   : ~1
#   adazu-nov   : ~1
#
# Non-existent pages (e.g. /page99.html) redirect to the base listing page.
# This is why we must discover the count from page 1 instead of guessing.

import re
import os
import sys
import time
from datetime import datetime
from urllib.parse import urlparse
import logging
from logging import handlers
from logging.handlers import RotatingFileHandler
import requests
from bs4 import BeautifulSoup
from requests.exceptions import ConnectionError, Timeout

# Optional: runtime city config loader (Phase 4 Item 12)
# Note on Item 13: Cloud Lambda scraper parity (full pages) should be verified
# separately; this local path now handles dynamic pages fully.
try:
    from .city_config import get_display_name, validate_city_slug, get_city_info
except Exception:
    def get_display_name(slug, default=None): return default or slug
    def validate_city_slug(slug): return True
    def get_city_info(slug): return None


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

# Delay between scraping each individual ad URL (detail pages)
# (for ~70 URLs: 5s x 70 = ~6 min)
SCRAPE_DELAY_SEC = int(os.getenv("SCRAPE_DELAY_SEC", "5"))

# Delay between fetching list pages (for politeness when scraping multiple pages)
SCRAPE_LIST_DELAY_SEC = int(os.getenv("SCRAPE_LIST_DELAY_SEC", "1"))

# URL_LIMIT controls how many individual ad pages are fully scraped per run.
# Default = 5 (safe dev default to keep runs fast).
# Set SCRAPE_URL_LIMIT=0 (or a very high number) in env to process ALL ads.
# This is the recommended dev toggle / config for full vs limited scraping.
_raw_limit = os.getenv("SCRAPE_URL_LIMIT", "5")
try:
    URL_LIMIT = int(_raw_limit) if _raw_limit else 5
except (ValueError, TypeError):
    logger.warning("Invalid SCRAPE_URL_LIMIT value, falling back to 5")
    URL_LIMIT = 5

if URL_LIMIT <= 0:
    logger.info("SCRAPE_URL_LIMIT=%s → will process ALL discovered ads", _raw_limit)
else:
    logger.info("SCRAPE_URL_LIMIT=%s (dev safety limit)", URL_LIMIT)

# true
SKIP_LAMBDA_FILE = True


def scrape_website(main_url: str = None, report_file: str = None, city_slug: str = None):
    """Main function of module calls all sub-functions.

    Dynamically discovers the total number of pages from the ss.lv pager
    and scrapes all pages (instead of hard-coded first page only).

    For Phase 1 (Item 5), this function now supports producing city-prefixed
    working files (e.g. "jurmala-raw-data-report.txt") instead of always
    hard-coding "Ogre-raw-data-report.txt".

    Args:
        main_url: Optional override for the city listing URL.
                  Falls back to CITY_MAIN_URL environment variable.
        report_file: Explicit name for the raw report file.
                     If None, will be derived from city_slug or main_url.
        city_slug: Optional explicit city identifier (e.g. "jurmala", "ogre").
                   Takes precedence over URL derivation when report_file is None.
    """
    if main_url is None:
        main_url = CITY_MAIN_URL

    # Item 5 (Phase 1): derive city-prefixed report file when not explicitly provided.
    # We keep the legacy "Ogre-raw-data-report.txt" name for the classic Ogre URL
    # so that the rest of the current pipeline continues to work without changes
    # (per Phase 1 success criteria: "no change to file names outside the scraper yet").
    if report_file is None:
        if city_slug is None:
            city_slug = derive_city_slug(main_url)
        if city_slug == "ogre":
            report_file = "Ogre-raw-data-report.txt"
        else:
            report_file = f"{city_slug}-raw-data-report.txt"

    logger.info("--- Starting web_scraper module ---")
    logger.info("Using listing URL: %s", main_url)

    city_display = city_slug or derive_city_slug(main_url)
    display_name = get_display_name(city_display, city_display)

    logger.info("Using report file: %s (city=%s / %s)", report_file, city_display, display_name)
    logger.info("Extracting BS4 objects")
    remove_old_file(report_file)

    # Use a session for connection reuse + polite headers (Item 8)
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; SS.LV-Scraper/1.6; +http://propertydata.lv/)",
        "Accept": "text/html,application/xhtml+xml",
    })

    # Fetch first page and determine total pages
    page_one_bs_obj = _fetch_list_page(session, main_url)
    if page_one_bs_obj is None:
        logger.error("Failed to fetch first page %s", main_url)
        raise RuntimeError(
            f"web_scraper: failed to fetch first listing page {main_url} after retries"
        )

    total_pages = get_total_pages(page_one_bs_obj)
    logger.info("Detected %s page(s) of listings", total_pages)

    # Collect ad URLs from all pages
    all_msg_urls: list[str] = []
    city_display = city_slug or derive_city_slug(main_url)
    display_name = get_display_name(city_display, city_display)

    # Always collect from page 1 (we already fetched it)
    page_urls = find_single_page_urls(page_one_bs_obj)
    all_msg_urls.extend(page_urls)
    logger.info("Scraping page 1/%s (%s) — found %s new ad URLs (total so far: %s)",
                total_pages, display_name, len(page_urls), len(all_msg_urls))

    # Fetch remaining pages
    for page_num in range(2, total_pages + 1):
        page_url = get_page_url(main_url, page_num)
        log_msg = f"Scraping page {page_num}/{total_pages} ({city_display})"
        logger.info(log_msg)

        bs = _fetch_list_page(session, page_url)
        if bs is None:
            logger.warning("Skipping page %s after failures: %s", page_num, page_url)
            continue

        page_urls = find_single_page_urls(bs)
        all_msg_urls.extend(page_urls)
        logger.info("Page %s/%s (%s) — found %s new ad URLs (total so far: %s)",
                    page_num, total_pages, display_name, len(page_urls), len(all_msg_urls))

        # Be polite between list pages (configurable)
        if page_num < total_pages:
            time.sleep(SCRAPE_LIST_DELAY_SEC)

    session.close()

    valid_msg_urls = list(dict.fromkeys(all_msg_urls))  # preserve order, remove dups

    logger.info("Found %s parsable message URLs across %s page(s)", len(valid_msg_urls), total_pages)

    if URL_LIMIT > 0:
        logger.info("Dev limit active: only first %s ads will be processed for details", URL_LIMIT)
    else:
        logger.info("No dev limit: processing all %s ads for details", len(valid_msg_urls))

    logger.info("Extracting data for city apartments for sell task")
    extract_data_from_url(valid_msg_urls, report_file)

    logger.info("Creating file copy in data folder")
    create_file_copy(report_file)
    logger.info("--- Finished web_scraper module ---")


def remove_old_file(filename: str = "Ogre-raw-data-report.txt") -> None:
    """
    Remove the given report file (default legacy Ogre name for compat)
    if it is older than a certain number of days.
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
    """Iterate over discovered ad URLs and extract details (respecting URL_LIMIT)."""
    if not nondup_urls:
        logger.warning("No ad URLs to process.")
        return

    # Compute how many to process. URL_LIMIT <= 0 means "all"
    if URL_LIMIT > 0:
        num_to_process = min(URL_LIMIT, len(nondup_urls))
    else:
        num_to_process = len(nondup_urls)

    logger.info("Processing %s of %s discovered ads (URL_LIMIT=%s)", 
                num_to_process, len(nondup_urls), URL_LIMIT)

    for i in range(num_to_process):
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

    Used together with get_total_pages() during the dynamic scraping loop
    (see scrape_website, Phase 1 Item 4).
    """
    if not base_url:
        # Graceful handling for empty base (mostly for tests)
        return f"/page{page_num}.html" if page_num > 1 else ""
    if page_num <= 1:
        return base_url
    # Ensure trailing slash for clean concatenation
    base = base_url.rstrip("/")
    return f"{base}/page{page_num}.html"


def get_total_pages(bs_object: BeautifulSoup, default: int = 1) -> int:
    """Extract the total number of result pages from the ss.lv pager.

    ss.lv renders pagination inside a <div class="td2"> (or nearby) using:
      - <button class=navia>1</button> for the current page
      - <a class="navi" ...>N</a> for other pages
      - "Nākamie" (next) and "Iepriekšējie" (previous) links

    This function collects all integer labels from elements with "navi" or "navia"
    classes and returns the maximum (i.e. the last page).

    Observed page counts (as of research against config/cities.yaml):
      - jurmala: 6 pages
      - marupes_pag: ~2 pages
      - ogre: ~2 pages
      - salaspils, sigulda, adazu_nov: often 1 page

    Edge cases handled:
      - Single page listings (only the navia button "1")
      - No pager present at all → returns `default` (1)
      - Requesting a non-existent high page number redirects to the first page

    This was implemented as part of Phase 1 (Item 2) to replace the previous
    hard-coded "only scrape page 1" behavior.
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


def _fetch_list_page(session: requests.Session, url: str, retries: int = 3, backoff: float = 0.5):
    """Fetch a listing page with retries. Returns BeautifulSoup or None on failure.

    This provides resilience for list page fetches (separate from detail page retries).
    """
    for attempt in range(retries):
        try:
            resp = session.get(url, timeout=15)
            resp.raise_for_status()
            return BeautifulSoup(resp.content, "html.parser")
        except Exception as exc:
            wait = backoff * (2 ** attempt)
            logger.warning("List page fetch failed (attempt %s/%s) for %s: %s. Retrying in %.1fs",
                           attempt + 1, retries, url, exc, wait)
            time.sleep(wait)
    return None


def derive_city_slug(main_url: str) -> str:
    """Derive a filesystem-friendly city slug from an ss.lv listing URL.

    Used by the scraper (Item 5) to generate city-prefixed report files
    such as "jurmala-raw-data-report.txt" instead of hard-coded "Ogre-...".

    Examples:
      - https://www.ss.lv/lv/real-estate/flats/jurmala/sell/          → "jurmala"
      - https://www.ss.lv/lv/real-estate/flats/ogre-and-reg/ogre/sell/ → "ogre"
      - https://www.ss.lv/lv/real-estate/flats/riga-region/sigulda/sell/ → "sigulda"
      - https://www.ss.lv/lv/real-estate/flats/riga-region/marupes-pag/sell/ → "marupes_pag"

    Falls back to "city" when detection fails.
    """
    if not main_url:
        return "city"
    try:
        path = urlparse(main_url).path.lower()
        segments = [s for s in path.split("/") if s]

        # Known city hints (from config/cities.yaml + common patterns)
        known = {
            "jurmala": "jurmala",
            "ogre": "ogre",
            "sigulda": "sigulda",
            "salaspils": "salaspils",
            "marupes-pag": "marupes_pag",
            "marupes_pag": "marupes_pag",
            "adazu-nov": "adazu_nov",
            "adazu_nov": "adazu_nov",
        }

        for seg in segments:
            if seg in known:
                return known[seg]
            # partial matches for compound paths
            for key, val in known.items():
                if key in seg:
                    return val

        # Fallback: segment immediately before "sell"
        if "sell" in segments:
            idx = segments.index("sell")
            if idx > 0:
                candidate = segments[idx - 1]
                return candidate.replace("-", "_")

        return "city"
    except Exception:
        return "city"


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
    """Creates a dated copy of the (city-aware) report file in the data/ folder
    (for check_lst_run_state) and also in local_lambda_raw_scraped_data/."""
    todays_date = datetime.today().strftime("%Y-%m-%d")
    base = report_file.replace(".txt", "")
    dest_file = f"{base}-{todays_date}.txt"

    # Copy to data/ so check_lst_run_state and data_format_changer can find it
    if not os.path.exists("data"):
        os.makedirs("data")
    os.system(f"cp {report_file} data/{dest_file}")

    # Copy for cloud/lambda compatibility
    if not os.path.exists("local_lambda_raw_scraped_data"):
        os.makedirs("local_lambda_raw_scraped_data")
    os.system(f"cp {report_file} local_lambda_raw_scraped_data/{dest_file}")


if __name__ == "__main__":
    scrape_website()
