"""
 This is ss.lv web scraper module.
 Module is adjusted to parse apartments for sale in Ogre or Jelgava city
"""


import requests
from bs4 import BeautifulSoup
import re


flats_ogre = "https://www.ss.lv/lv/real-estate/flats/ogre-and-reg/ogre/sell/"
flats_jelgava = "https://www.ss.lv/lv/real-estate/flats/jelgava-and-reg/jelgava/sell/"


def scrape_website():
    print("Debug info: Starting website parsing module ... ")
    print("Debug info: getting BS4 objects ...")
    ogre_object = get_bs_object(flats_ogre)
    print("Debug info: bulding non-duplicate URL list from BS4 objects ...")
    valid_msg_urls = find_single_page_urls(ogre_object)
    print("Debug info: found " + str(len(valid_msg_urls))
          + " parsable message URLs ...")
    extract_data_from_url(valid_msg_urls, 'Ogre-raw-data-report.txt')


def extract_data_from_url(nondup_urls: list, dest_file: str) -> None:
    """  Iterate over all first page msg urls extract info from
     each url and write to file
    """
    msg_url_count = len(nondup_urls)
    for idx in range(msg_url_count):
        current_msg_url = nondup_urls[idx] + "\n"
        table_opt_names = get_msg_table_info(nondup_urls[idx], "ads_opt_name")
        table_opt_values = get_msg_table_info(nondup_urls[idx], "ads_opt")
        table_price = get_msg_table_info(nondup_urls[idx], "ads_price")

        print("Debug info: extracting data from message URL ", idx + 1)
        write_line(current_msg_url, dest_file)
        for j in range(len(table_opt_names) - 1):
            text_line = table_opt_names[j] + ">" + table_opt_values[j] + "\n"
            write_line(text_line, dest_file)

        # Extract message price field
        price_line = "Price:>" + table_price[0] + "\n"
        write_line(price_line, dest_file)

        # Extract message publish date field
        table_date = get_msg_table_info(nondup_urls[idx], "msg_footer")
        for k in range(len(table_date)):
            if k == 2:
                date_str = table_date[k]
                date_and_time = date_str.replace("Datums:", "")
                date_clean = date_and_time.split()[0]
                date_field = "Date:>" + str(date_clean) + "\n"
        write_line(date_field, dest_file)

        # Extract message view count
        views = get_msg_field_info(nondup_urls[idx], "show_cnt_stat")
        view_count = "views:>" + str(views) + "\n"
        write_line(view_count, dest_file)


def get_bs_object(page_url: str):
    """
    Function loads webpage from url and returns bs4 object
    """
    page = requests.get(page_url)
    bs_object = BeautifulSoup(page.content, "html.parser")
    return bs_object


def find_single_page_urls(bs_object) -> list:
    """
    Function iterates over all a sections and gets all href lines

    object: bs4 object
    returns:  list of strings with all message URLs

    """
    url_list = []
    for a in bs_object.find_all('a', href=True):
        one_link = "https://ss.lv" + a['href']
        re_match = re.search("msg", one_link)
        if re_match:
            url_list.append(one_link)

    valid_urls = []
    for url in url_list:
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
    """
    Function parses message page and extracts td_class table fields

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
    """ Append text to end of the file

    """
    with open(file_name, 'a') as the_file:
        the_file.write(text)


scrape_website()
