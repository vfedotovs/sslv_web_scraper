"""
data_formater_v14.py Module.

Module functions:
[x] 1. Take as input file Ogre-raw-data-report.txt creates pandas_df.csv
[x] 2. pandas_df.csv will be used in analitics.py module

"""
import os
import re
import pandas as pd
from datetime import datetime


def get_file_path(city_name: str) -> str:
    """Builds file name based on date"""
    todays_date = datetime.today().strftime('%Y-%m-%d')
    target_filename = city_name + '-raw-data-report-' + todays_date + '.txt'
    return "data/" + target_filename


def data_formater_main() -> None:
    """Read raw data from Ogre-raw-data-report.txt and save to pandas_df.csv"""
    print("Debug info: Started dat_formater module ... ")
    data_file_location = get_file_path('Ogre')
    df = create_oneline_report(data_file_location)
    df.to_csv("pandas_df.csv")
    create_file_copy
    print("Debug info: Ended data_formater module ... ")


def create_oneline_report(source_file: str):
    """ Converts multiline advert data from  txt to Python data frame object
    Args:
        source_file: raw-data text file for example Ogre-raw-data-report.txt
    Returns:
       df: Pandas data frame object
    """
    urls = []
    room_counts = []
    room_sizes = []
    room_streets = []
    room_prices = []
    room_floors = []
    publish_dates = []
    oneline_report = []
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
    df = pd.DataFrame(mydict)
    return df


def create_file_copy() -> None:
    """Creates report file copy in data folder"""
    copy_cmd = 'mv cleaned-sorted-df.csv data/'
    if not os.path.exists('data'):
        os.makedirs('data')
    os.system(copy_cmd)


# Main
data_formater_main()
