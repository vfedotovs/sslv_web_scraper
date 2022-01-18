"""
data_formater_v14.py Module.

Module functions:
[x] 1. Take as input file Ogre-raw-data-report.txt creates pandas_df.csv
[x] 2. pandas_df.csv will be used in analitics.py module

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
    df = create_oneline_report(data_file_location)
    df.to_csv("pandas_df.csv")
    create_file_copy()
    all_ads_df = pd.read_csv("cleaned-sorted-df.csv", index_col=False)
    create_email_body(all_ads_df, 'email_body_txt_m4.txt')

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


def save_text_report_to_file(text: list, file_name: str) -> None:
    """Writes oneline data text to mailer report file"""
    with open(file_name, 'a') as the_file:
        for line in text:
            the_file.write(f"{line}\n")


def create_email_body(clean_data_frame, file_name: str) -> None:
    """Creates categorized by room count ad hash : data for email body.

    Requires:
        clean_data_frame: pandas data frame

    Creates:
        email_body_txt_m4.txt : text file"""

    email_body_txt = ['Sendgrid mailer Milestone 4 report:']
    for room_count in range(4):
        room_count_str = str(room_count + 1)
        section_line = str(room_count_str + " room apartment section: ")
        email_body_txt.append(section_line)
        filtered_by_room_count = clean_data_frame.loc[clean_data_frame['Room_count'] == int(room_count_str)]
        colum_line = "[Rooms, Floor, Size , Price, SQM Price, Apartment Street, Pub_date,  URL]"
        email_body_txt.append(colum_line)
        for index, row in filtered_by_room_count.iterrows():
            url_str = row["URL"]
            sqm_str = row["Size_sqm"]
            floor_str = row["Floor"]
            total_price = row["Price_in_eur"]
            sqm_price = row['SQ_meter_price']
            rooms_str = row['Room_count']
            street_str = row['Street']
            pub_date_str = row['Pub_date']
            report_line = "  " + str(rooms_str) + "     " + \
                          str(floor_str) + "    " + \
                          str(sqm_str) + "   " + \
                          str(total_price) + "    " + \
                          str(sqm_price) + "   " + \
                          str(street_str) + "   " + \
                          str(pub_date_str) + " " + \
                          str(url_str)
            email_body_txt.append(report_line)

    save_text_report_to_file(email_body_txt, file_name)


# Main
data_formater_main()
