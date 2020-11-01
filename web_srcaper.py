"""
 This is ss.lv web scraper module.
 Module is adjusted to parse apartments for sale in Ogre city
"""


import requests
from bs4 import BeautifulSoup
import re


sell_flats_in_ogre = "https://www.ss.lv/lv/real-estate/flats/ogre-and-reg/ogre/sell/"
page = requests.get(sell_flats_in_ogre)
bs_object = BeautifulSoup(page.content, "html.parser")

def main():

    nondup_urls = find_single_page_urls(object)

    for url in nondup_urls:
        print(url)

    print("Geting table info from every message :")
    # Iterates over all messges

    for i in range(3):
        table_opt_names = get_msg_table_info(nondup_urls[i], "ads_opt_name")
        table_opt_values = get_msg_table_info(nondup_urls[i], "ads_opt")
        table_price = get_msg_table_info(nondup_urls[i], "ads_price")

        for i in range(len(table_opt_names) - 1):
            print(table_opt_names[i] , "-->", table_opt_values[i])
        print("---------->", table_price[0])


def find_single_page_urls(object) -> list:
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


def get_msg_table_info(msg_url: str, td_class: str) ->list:
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
        name = no_front.split("</",1)[0]
        table_fields.append(name)
    return table_fields



if __name__ == "__main__":
    main()

"""
# TODO - implement apartments for rent parsing
# rent_url = "https://www.ss.lv/lv/real-estate/flats/ogre-and-reg/hand_over/"
"""
