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
    # for url in nondup_urls:
    #    get_tableinfo_single_url(url)

    # Working on first 3 examples for now
    for i in range(3):
        get_tableinfo_single_url(nondup_urls[i])



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


def remove_duplicate_urls(urls: list) -> list:
    """
    Function takes string list with duplicate entries and removes all duplicates

    urls: list with strings
    returns: valid_urls
    """
    valid_urls = []
    for url in urls:
        if url not in valid_urls:
            valid_urls.append(url)
    return valid_urls


def get_msg_table_info():
    pass

def get_tableinfo_single_url(single_url: str):

    page = requests.get(single_url)
    soup = BeautifulSoup(page.content, "html.parser")
    opts_names = []
    opts_values = []
    opts_prices = []

    # print("--------- Table names - debug info ----------")
    table = soup.find('table', id="page_main")

    opts = table.findAll('td', {"class": "ads_opt_name"})
    for opt in opts:
        tostr = str(opt)
        no_front = tostr.split(">", 1)[1]
        name = no_front.split("<")[0]
        opts_names.append(name)

    # print("--------- Table values - debug info ----------")
    data_results = table.findAll('td', {"class": "ads_opt"})
    for result in data_results:
        tostr = str(result)
        nofront = tostr.split('"">', 1)[1]
        value = nofront.split("</", 1)[0]
        opts_values.append(value)

    # print("--------- Table price - debug info ----------")
    prices = table.findAll('td', {"class": "ads_price"})
    for price in prices:
        tostr = str(price)
        nofront = tostr.split('"top">', 1)[1]
        value = nofront.split("</", 1)[0]
        opts_prices.append(value)


    for i in range(len(opts_names) - 1):
        print(opts_names[i], " -> " , opts_values[i] )
    print("-----> Price:", opts_prices[0])
    print("")
    print("")



if __name__ == "__main__":
    main()

"""
# TODO - implement apartments for rent parsing
# rent_url = "https://www.ss.lv/lv/real-estate/flats/ogre-and-reg/hand_over/"
"""
