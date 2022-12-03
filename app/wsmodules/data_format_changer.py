#!/usr/bin/env python3
"""
data_format_changer.py Module

Module functions:
[x] 1. Reads scraped data from Ogre-raw-data-report-2022-12-03.txt file
(text files can not be read by padas)
[x] 2. Changes format 12 lines per ad entry to 1 line per ad entry.
[x] 3. Writes pandas_df.csv and creates copy data/pandas_df.csv_2022-12-03.csv
(later used as input file in analitics.py module and
csv file can be very easy inported as pandas DataFrame.)

#TODO: Implement these features
[ ] 4. Some data like Serija,Majas tips and Kadastra numurs are not
transfered to outut file.
[ ] 5. Rename pandas_df.csv_2022-12-03.csv to better name
ogre_city_data_2022_12_03.csv and Upload renamed file ro new S3 bucket
(Big perfommance improvement by eliminating need to re-scrape data on each run)
(This architectual steep can reduce email recieving time by 4-5 min avoiding
re-scraping data multiple times per day)


Module requires:
[x] If today is 2022-12-03 file data/Ogre-raw-data-report-2022-12-03.txt must exist for module to run

Mudule creates:
[x] File pandas_df.csv and makes copy data/pandas_df.csv_2022-12-03.csv
"""
import os
import re
from datetime import datetime
import pandas as pd


def get_file_path(city_name: str) -> str:
    """Builds file name based on date"""
    todays_date = datetime.today().strftime('%Y-%m-%d')
    target_filename = city_name + '-raw-data-report-' + todays_date + '.txt'
    return "data/" + target_filename


def data_formater_main() -> None:
    """Read raw data from Ogre-raw-data-report.txt and save to pandas_df.csv"""
    print("Debug info: Started dat_formater module ... ")
    data_file_location = get_file_path('Ogre')
    ogre_city_data_frame = create_oneline_report(data_file_location)
    ogre_city_data_frame.to_csv("pandas_df.csv")
    create_file_copy()
    print("Debug info: Ended data_formater module ... ")


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
    with open(source_file) as file_handle:
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
            'Size_sq_m' : room_sizes,
            'Floor': room_floors,
            "Street": room_streets,
            'Price': room_prices,
            'Pub_date': publish_dates }
    pandas_df = pd.DataFrame(mydict)
    return pandas_df


def create_file_copy() -> None:
    """Creates copy of pandas_df.csv in as data/pandas_df.csv_2022-12-03.csv"""
    todays_date = datetime.today().strftime('%Y-%m-%d')
    dest_file = 'pandas_df_' + todays_date + '.csv'
    copy_cmd = 'cp pandas_df.csv data/' + dest_file
    if not os.path.exists('data'):
        os.makedirs('data')
    os.system(copy_cmd)


# Main
data_formater_main()
