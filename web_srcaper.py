"""
 This is ss.lv web scraper module
"""


import requests
from bs4 import BeautifulSoup
import re

# URL = "ss.lv"
URL = "http://www.example.com"
sell_flats_in_ogre = "https://www.ss.lv/lv/real-estate/flats/ogre-and-reg/ogre/sell/"
# rent_url = "https://www.ss.lv/lv/real-estate/flats/ogre-and-reg/hand_over/"

page = requests.get(sell_flats_in_ogre)
bs_object = BeautifulSoup(page.content, "html.parser")

# print(bs_object) # works


def find_single_page_urls() -> list:
    url_list = []
    for a in bs_object.find_all('a', href=True):
        # print("DEBUG: Found the URL:", a['href'])
        one_link = "https://ss.lv" + a['href']
        re_match = re.search("msg", one_link)
        if re_match:
            url_list.append(one_link)
    return url_list


filtered_urls = find_single_page_urls()


def remove_duplicate_urls(urls: list) -> list:
    tmp = []
    for url in urls:
        if url not in tmp:
            tmp.append(url)
    return tmp


nondup_urls = remove_duplicate_urls(filtered_urls)

for url in nondup_urls:
    print(url)

print("Geting street info:")

test_url = "https://ss.lv/msg/lv/real-estate/flats/ogre-and-reg/ogre/ahdlj.html"
def get_tableinfo_single_url(single_url: str):

    page = requests.get(single_url)
    soup = BeautifulSoup(page.content, "html.parser")

    # message_text = soup.find("div", {"id": "msg_div_msg"})
    # print(message_text) # working
    print("--------- Table names - debug info ----------")
    table = soup.find('table', id="page_main")

    opts = table.findAll('td', {"class": "ads_opt_name"})
    for opt in opts:
        tostr = str(opt)
        no_front = tostr.split(">", 1)[1]
        name = no_front.split("<")[0]
        print(name)

    print("--------- Table values - debug info ----------")
    data_results = table.findAll('td', {"class": "ads_opt"})
    for result in data_results:
        tostr = str(result)
        nofront = tostr.split('"">', 1)[1]
        value = nofront.split("</", 1)[0]
        print(value)

    print("--------- Table price - debug info ----------")
    prices = table.findAll('td', {"class": "ads_price"})
    for price in prices:
        tostr = str(price)
        nofront = tostr.split('"top">', 1)[1]
        value = nofront.split("</", 1)[0]
        print(value)


# get_tableinfo_single_url(test_url)

for url in nondup_urls:
    get_tableinfo_single_url(url)
