"""
 This is ss.lv web scraper module.
 Module is adjusted to parse apartments for sale in Ogre or Jelgava city
"""


import requests
from bs4 import BeautifulSoup
import re


flats_ogre = "https://www.ss.lv/lv/real-estate/flats/ogre-and-reg/ogre/sell/"
flats_jelgava = "https://www.ss.lv/lv/real-estate/flats/jelgava-and-reg/jelgava/sell/"

def main():

    jel_object = get_bs_object(flats_jelgava)
    #ogre_object = get_bs_object(flats_ogre)

    nondup_urls = find_single_page_urls(jel_object)
    #nondup_urls = find_single_page_urls(ogre_object)

    for url in nondup_urls:
        print(url)

    print("Geting table info from every message :")
    # Iterates over all messges

    for i in range(5):
        current_msg_url = nondup_urls[i] + "\n"
        table_opt_names = get_msg_table_info(nondup_urls[i], "ads_opt_name")
        table_opt_values = get_msg_table_info(nondup_urls[i], "ads_opt")
        table_price = get_msg_table_info(nondup_urls[i], "ads_price")


        write_line('This is 5 message report about Ogre flats for sale: \n', 'Ogre-report.txt')
        print("Debug info: working on message ", i)
        write_line(current_msg_url, 'Ogre-report.txt')
        for i in range(len(table_opt_names) - 1):
            # print(table_opt_names[i] , "-->", table_opt_values[i])
            text_line = table_opt_names[i] + "-->" + table_opt_values[i] + "\n"
            write_line(text_line, 'Ogre-report.txt')
        price_line = "Price:--->" + table_price[0] + "\n"
        write_line(price_line, 'Ogre-report.txt')



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


def write_line(text: str,file_name: str) ->None:
    """ Append text to end of the file

    """
    with open(file_name, 'a') as the_file:
            the_file.write(text)




if __name__ == "__main__":
    main()

"""
# TODO - implement apartments for rent parsing
# rent_url = "https://www.ss.lv/lv/real-estate/flats/ogre-and-reg/hand_over/"
"""
