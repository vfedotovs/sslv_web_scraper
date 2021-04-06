""" data_formater.py Module.
This module main 4 main functions:
    1. Take as input file Ogre-raw-data-report.txt and crete as output file
    Mailer_report.txt
    2. Ogre-raw-data-report.txt does not have pretty oneline fromtting for each
    message  this module converts multiline message information to single line
    3. Mailer_report.txt is later used by gmailer.py module to message insert
    more user frendly oneline messages in email
    4. Creates Pandas data frame file  pandas_df.csv that is used in
    analitics.py module
TODO:
    1.FIXME failure to handle Latvian characters in email
    Due to Latian characters (āčēģīķļņšūž) triggers ACSI error
    durin send email process and fails to sond email
    Currently as workaround apartment sreet info is not included in
    Mailer_report.txt
"""
import re
import pandas as pd


def create_mailer_report() -> None:
    """ Main module function
    Function will use for example Ogre-raw-data-report.txt will load data to
    pandas data frame and save to pandas_df.csv file and
    will format data in one line and will create Mailer_report.txt
    that will be used by gmailer.py module """
    # Load text from raw data file to df in memmory
    msg_data_frame = create_oneline_report('Ogre-raw-data-report.txt')
    # Saves to csv for other module usage
    msg_data_frame.to_csv("pandas_df.csv")
    # Export to txt for gmailer.py consumable txt file
    data_for_save = format_text_to_oneline(msg_data_frame)
    save_text_report_to_file(data_for_save, 'Mailer_report.txt')
    # Creates file for pdf_creator.py module
    filer_df_by_value_in_column(msg_data_frame, 'Istabas:>1', '1_rooms_tmp.txt')


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


def filer_df_by_value_in_column(data_frame, keyword, file_name: str) -> None:
    """ Filters df rows for keyword and saves to txt file
    - requred for pfd_generator module """
    filtered_lines = []
    filtered_df = data_frame.loc[data_frame['Room_count'] == keyword]
    for index, row in filtered_df.iterrows():
        url_str = row["URL"]
        sqm_str = row["Size_sq_m"]
        floor_str = row["Floor"]
        total_price = row["Price"]
        rooms_str = row['Room_count']
        ad_in_oneline = url_str + " " + \
                        rooms_str + " " + \
                        sqm_str + " " + \
                        total_price
        filtered_lines.append(ad_in_oneline)
    #Save filtered_lines to file 1_rooms_tmp.txt
    save_text_report_to_file(filtered_lines, file_name)


def format_text_to_oneline(data_frame) -> list:
    """ Function will format text to oneline format and create 2 output files from data frame:
        1. txt_export_file - save data frame to txt for gmailer.py module
        2. TODO: habdle Latvian characters
    Required  Format for email
    Report for 1 rooms:
    URL:: Istabas:>1 Stavs:>2/9 Platiba:>30 m sq   Price:>33 000  EUR (1 100  EUR/m sq)
    TODO:
        match with re and replace EUR sign to EUR word - handled in gmailer.py
        match m2 wiht re and replace with sqm - handled in gmailer.py
        implement: LV charater cleanup and address include to email
    """
    text_data = []
    filter_kywords = ['Istabas:>1' , 'Istabas:>2', 'Istabas:>3', 'Istabas:>4'] # quick and ditry way
    count = 1
    for keyword in filter_kywords:
        filtered_df = data_frame.loc[data_frame['Room_count'] == keyword]
        room_count_line = "\n Room count: " + str(count)
        text_data.append(room_count_line)
        for index, row in filtered_df.iterrows():
            url_str = row["URL"]
            sqm_str = row["Size_sq_m"]
            floor_str = row["Floor"]
            total_price = row["Price"]
            rooms_str = row['Room_count']
            ad_in_oneline = url_str + " " + \
                            rooms_str + " " + \
                            sqm_str + " " + \
                            total_price
            text_data.append(ad_in_oneline)
        print("")
        count += 1
    return text_data


def save_text_report_to_file(text: list,file_name: str) ->None:
    """ Writes oneline data text to mailer report file """
    with open(file_name, 'a') as the_file:
        for line in text:
            the_file.write(f"{line}\n")


# Main code driver function of module
create_mailer_report()

