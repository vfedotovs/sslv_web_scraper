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
        file_time = datetime.datetime.fromtimestamp(os.path.getmtime(file_path))
        now = datetime.datetime.now()

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
    """Iterate over all first page msg urls extract info from each url and write to file """
    msg_url_count = len(nondup_urls)
    for i in range(msg_url_count):
        current_msg_url = nondup_urls[i] + "\n"
        table_opt_names = get_msg_table_info(nondup_urls[i], "ads_opt_name")
        table_opt_values = get_msg_table_info(nondup_urls[i], "ads_opt")
        table_price = get_msg_table_info(nondup_urls[i], "ads_price")

        logger.info("Extracting data from message URL %s" , str(i + 1))
        write_line(current_msg_url, dest_file)
        for idx in range(len(table_opt_names) - 1):
            text_line = table_opt_names[idx] + \
                ">" + table_opt_values[idx] + "\n"
            write_line(text_line, dest_file)

        # Extract message price field
        price_line = "Price:>" + table_price[0] + "\n"
        write_line(price_line, dest_file)

        # Extract message publish date field
        table_date = get_msg_table_info(nondup_urls[i], "msg_footer")
        for date_idx in range(len(table_date)):
            if date_idx == 2:
                date_str = table_date[date_idx]
                date_and_time = date_str.replace("Datums:", "")
                date_clean = date_and_time.split()[0]
                date_field = "Date:>" + str(date_clean) + "\n"
        write_line(date_field, dest_file)
        time.sleep(SCRAPE_DELAY_SEC)

        # TODO: Fix-me Extract message view count always returns view count = 1
        # views = get_msg_field_info(nondup_urls[i], "show_cnt_stat")
        # view_count =  "views:>" + str(views) + "\n"
        # write_line(view_count, dest_file)


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

    table_fields = []

    table_data = table.findAll('td', {"class": td_class})
    for data in table_data:
        tostr = str(data)
        no_front = tostr.split('">', 1)[1]
        name = no_front.split("</", 1)[0]
        table_fields.append(name)
    return table_fields


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


if __name__ == "__main__":
    scrape_website()
