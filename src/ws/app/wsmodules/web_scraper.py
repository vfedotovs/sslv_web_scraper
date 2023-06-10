"""
This is ss.lv parser project web scraper module.
Module main purpouse is to use ss.lv website as data source and
using requests and bs4 libraries to extract data (price, URL, sqm, street)
from Ogre city apartments for sale advertisements and save
to file Ogre-raw-data-report.txt
"""
import re
import requests
from bs4 import BeautifulSoup
import sys
import os
from datetime import datetime
import logging
from logging import handlers
from logging.handlers import RotatingFileHandler
import time


logger = logging.getLogger('web_scraper')
logger.setLevel(logging.INFO)
ws_log_format = logging.Formatter(
        "%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s] %(name)s : %(funcName)s: %(lineno)d: %(message)s")

ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(ws_log_format)
logger.addHandler(ch)

fh = handlers.RotatingFileHandler('web_scraper.log', maxBytes=(1048576*5), backupCount=7)
fh.setFormatter(ws_log_format)
logger.addHandler(fh)


FLATS_OGRE = "https://www.ss.lv/lv/real-estate/flats/ogre-and-reg/ogre/sell/"
city_name = 'Ogre'


def scrape_website():
    """Main function of module calls all sub-functions"""
    logger.info("--- Starting web_scraper module ---")
    logger.info("Extracting BS4 objects")
    ogre_object = get_bs_object(FLATS_OGRE)
    logger.info("Building non-duplicate URL list from BS4 objects")
    valid_msg_urls = find_single_page_urls(ogre_object)
    logger.info(f"Found {str(len(valid_msg_urls))} parsable message URLs")
    logger.info("Extracting data for Ogre city apartments for sell task and saving as Ogre-raw-data-report.txt")
    extract_data_from_url(valid_msg_urls, 'Ogre-raw-data-report.txt')
    logger.info("Creating file Ogre-raw-data-report.txt copy in data folder")
    create_file_copy()
    logger.info("--- Finished web_scraper module ---")


def extract_data_from_url(nondup_urls: list, dest_file: str) -> None:
    """Iterate over all first page msg urls extract info from each url and write to file """
    msg_url_count = len(nondup_urls)
    for i in range(msg_url_count):
        current_msg_url = nondup_urls[i] + "\n"
        table_opt_names = get_msg_table_info(nondup_urls[i], "ads_opt_name")
        table_opt_values = get_msg_table_info(nondup_urls[i], "ads_opt")
        table_price = get_msg_table_info(nondup_urls[i], "ads_price")

        logger.info(f"Extracting data from message URL  {i + 1}")
        write_line(current_msg_url, dest_file)
        for idx in range(len(table_opt_names) - 1):
            text_line = table_opt_names[idx] + ">" + table_opt_values[idx] + "\n"
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
        # adding deplay between scraping each URL 5 sec (for Ogre 5x30=150 sec or 2.5 min should last ) 
        time.sleep(5)


        # TODO: Fix-me Extract message view count always returns view count = 1
        # views = get_msg_field_info(nondup_urls[i], "show_cnt_stat")
        # view_count =  "views:>" + str(views) + "\n"
        # write_line(view_count, dest_file)


def get_bs_object(page_url: str):
    """ Function loads webpage from url and returns bs4 object"""
    page = requests.get(page_url)
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
    r = requests.get(msg_url)
    data = r.text
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
    page = requests.get(msg_url)
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
    copy_cmd = 'cp Ogre-raw-data-report.txt data/' + dest_file
    if not os.path.exists('data'):
        os.makedirs('data')
    os.system(copy_cmd)


scrape_website()
