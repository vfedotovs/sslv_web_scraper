#!/usr/bin/env python3
"""
data_format_changer.py module functionality is to convert scraped multiline
text data per advert entry in to singe line CSV format that later can be loaded
in to pandas dataftame.

Module functions:
[x] Reads scraped data from Ogre-raw-data-report-2022-12-03.txt file
    (resolves limitation that text files can not be read by padas)
[x] Changes format 12 lines per ad entry to 1 line per ad entry.
[x] Writes pandas_df.csv and creates copy data/pandas_df.csv_2022-12-03.csv
    (later used as input file in analitics.py module and csv file can be very
    easy inported as pandas DataFrame.)
[x] Allows to utilise daily AWS labmda scrape job output file that leads to
    big perfommance improvement by eliminating need to re-scrape data on each
    app deployment (This architectual steep does reduce email recieving time
    by 4-5 min avoiding re-scraping data multiple times per day)


# TODO: Implement these features
[ ] Some data like Serija,Majas tips and Kadastra numurs are not
    transfered to outut file.
[ ] Rename pandas_df.csv_2022-12-03.csv to better name for example to
    ogre_city_data_2022_12_03.csv


Module requires:
[x] If today is 2022-12-03 file data/Ogre-raw-data-report-2022-12-03.txt 
    must exist for module to run

Mudule creates:
[x] File pandas_df.csv and makes copy data/pandas_df.csv_2022-12-03.csv
"""
import os
import re
from datetime import datetime
import logging
import logging.handlers as handlers
from logging.handlers import RotatingFileHandler
import sys
import pandas as pd


log = logging.getLogger('data_format_changer')
log.setLevel(logging.INFO)
fastapi_log_format = logging.Formatter(
    "%(asctime)s [%(threadName)-12.12s]"
    " [%(levelname)-5.5s] : %(funcName)s:"
    " %(lineno)d: %(message)s")

ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(fastapi_log_format)
log.addHandler(ch)

fh = handlers.RotatingFileHandler('df_changer.log',
                                  maxBytes=(1048576*5),
                                  backupCount=5)
fh.setFormatter(fastapi_log_format)
log.addHandler(fh)


def get_local_ws_fp() -> str:
    """Returns local web_scraper module
    output file path with todays date"""
    todays_date = datetime.today().strftime('%Y-%m-%d')
    target_filename = 'Ogre-raw-data-report-' + todays_date + '.txt'
    return "data/" + target_filename


def get_cloud_ws_fp() -> str:
    """Returns cloud web_scraper module
    output file path with todays date"""
    todays_date = datetime.today().strftime('%Y-%m-%d')
    target_filename = 'Ogre-raw-data-report-' + todays_date + '.txt'
    return "local_lambda_raw_scraped_data/" + target_filename


def check_todays_cloud_data_file_exist() -> bool:
    """Checks if file Ogre-raw-data-report-YYYY-MM-DDTMM-HH-SS.txt
    which was generated by AWS lambda scraper and downloaded from S3 bucket
    exist in local_lambda_raw_scraped_datafolder with todays date"""
    cloud_file_folder = "local_lambda_raw_scraped_data"
    todays_date = datetime.today().strftime('%Y-%m-%d')
    log.info("Searching for cloud files with todays date: %s ", todays_date)
    if not os.path.exists(cloud_file_folder):
        log.error("Folder %s does not exist. Creating empty folder ",
                  cloud_file_folder)
        os.makedirs(cloud_file_folder)
    cwd = os.getcwd()
    for file_name in os.listdir(cloud_file_folder):
        print(f"Current path: {cwd}")
        if todays_date in file_name:
            log.info('File %s containing today'
                     ' date %s found, ', file_name, todays_date)
            return True
    log.info('File containing today date %s was not found,'
             ' will try to find local craper file', todays_date)
    return False


def get_detailed_file_path() -> str:
    """ Returns detailed file name that matches todays date
    local_lambda_raw_scraped_data/Ogre-raw-data-report-YYYY-MM-DDTMM-HH-SS.txt
    """
    cloud_file_folder = "local_lambda_raw_scraped_data"
    todays_date = datetime.today().strftime('%Y-%m-%d')
    for file_name in os.listdir(cloud_file_folder):
        if todays_date in file_name:
            return "local_lambda_raw_scraped_data/" + file_name


def cloud_data_formater_main() -> None:
    """Read raw data from Ogre-raw-data-report.txt and save to pandas_df.csv"""
    log.info(' --- Started data_format_changer module ---')
    todays_cloud_ws_fp = get_cloud_ws_fp()
    log.info("AWS lambda scraped file path: %s ", todays_cloud_ws_fp)
    todays_local_ws_fp = get_local_ws_fp()
    todays_cloud_ws_file_exist = check_todays_cloud_data_file_exist()
    log.info("AWS lambda scraped file exists: %s ",
             str(todays_cloud_ws_file_exist))
    if todays_cloud_ws_file_exist is True:
        log.info("Creating one-line report using lambda scraped file: %s",
                 todays_cloud_ws_fp)
        detailed_cws_fp = get_detailed_file_path()
        ogre_city_data_frame = create_oneline_report(detailed_cws_fp)
        ogre_city_data_frame.to_csv("pandas_df.csv")
        create_file_copy()
    elif todays_cloud_ws_file_exist is False:
        log.info(
            "Creating one-line report using locally scraped file: %s ", todays_local_ws_fp)
        ogre_city_data_frame = create_oneline_report(todays_local_ws_fp)
        if ogre_city_data_frame is not None:
            ogre_city_data_frame.to_csv("pandas_df.csv")
            create_file_copy()
        if ogre_city_data_frame is None:
            log.error('Error: ogre_city_data_frame is None')
    log.info(' --- Ended data_format_changer module --- ')


def get_file_path(city_name: str) -> str:
    """Builds file name based on date"""
    todays_date = datetime.today().strftime('%Y-%m-%d')
    if city_name is None:
        log.error('Error: city_name is None')
    if city_name is not None:
        target_filename = city_name + '-raw-data-report-' + todays_date + '.txt'
        return "data/" + target_filename


def create_oneline_report(source_file: str) -> pd.DataFrame:
    """Changes text file format(12 lines per ad entry)
    to csv file format (1 line per ad entry)

    12 line data format for each scraped ad entry in Ogre-raw-data-report-2022-12-03.txt
    https://ss.lv/msg/lv/real-estate/flats/ogre-and-reg/ogre/fxobe.html
    Pilsēta, rajons:><b>Ogre un raj.
    Pilsēta/pagasts:><b>Ogre
    Iela:><b>Jaunatnes iela 4
    Istabas:>2
    Platība:>50 m²
    Stāvs:>3/9/lifts
    Sērija:>602.
    Mājas tips:>Paneļu
    Kadastra numurs:>74019004158
    Price:>57 000 € (1 140 €/m²)
    Date:>01.02.2022


    Data format of pandas_df_2022-12-03.csv is one line per ad
    ,URL,Room_count,Size_sq_m,Floor,Street,Price,Pub_date
    0,https://ss.lv/msg/lv/real-estate/flats/ogre-and-reg/ogre/fxobe.html,Istabas:>2,Platiba:>50 m²,Stavs:>3/9/lifts,Iela:><b>Jaunatnes iela 4,Price:>57 000 € (1 140 €/m²),Date:>01.02.2022


    Args:
        source_file: text file data/Ogre-raw-data-report-2022-12-03.txt
    Returns:
       df: pd.DataFrame object
    """
    urls = []
    room_counts = []
    room_sizes = []
    room_streets = []
    room_prices = []
    room_floors = []
    publish_dates = []
    try:
        with open(source_file, 'r', encoding='utf-8') as file_handle:
            while True:
                line = file_handle.readline()
                match_url = re.search("https", line)
                if match_url:
                    urls.append(line.rstrip('\n'))
                match_room_count = re.search("Istabas:", line)
                if match_room_count:
                    room_counts.append(line.rstrip('\n'))
                match_room_street_count = re.search("Iela:", line)
                if match_room_street_count:
                    room_streets.append(line.rstrip('\n'))
                match_room_price = re.search("Price:", line)
                if match_room_price:
                    room_prices.append(line.rstrip('\n'))
                match_pub_date = re.search("Date:", line)
                if match_pub_date:
                    publish_dates.append(line.rstrip('\n'))
                match_room_size = re.search("Platība:", line)
                if match_room_size:
                    tmp = line.rstrip('\n')
                    sizes = tmp.replace("Platība:", "Platiba:")
                    room_sizes.append(sizes)
                match_room_floor = re.search("Stāvs:", line)
                if match_room_floor:
                    tmp = line.rstrip('\n')
                    floors = tmp.replace("Stāvs:", "Stavs:")
                    room_floors.append(floors)
                if not line:
                    break
            # Create pandas data frame
            mydict = {'URL': urls,
                      'Room_count': room_counts,
                      'Size_sq_m': room_sizes,
                      'Floor': room_floors,
                      'Street': room_streets,
                      'Price': room_prices,
                      'Pub_date': publish_dates}
            pandas_df = pd.DataFrame(mydict)
            return pandas_df

    except FileNotFoundError:
        log.error("Error: The file %s does not exist", source_file)
    except Exception as e:
        log.error(
            "An error occurred while processing the file %s : %s ", source_file, str(e))


def create_file_copy() -> None:
    """Creates copy of pandas_df.csv in as data/pandas_df.csv_2022-12-03.csv"""
    # TODO: add more robust try except mv
    todays_date = datetime.today().strftime('%Y-%m-%d')
    dest_file = 'pandas_df_' + todays_date + '.csv'
    copy_cmd = 'cp pandas_df.csv data/' + dest_file
    if not os.path.exists('data'):
        os.makedirs('data')
    os.system(copy_cmd)


if __name__ == "__main__":
    cloud_data_formater_main()
