#!/usr/bin/env python3

""" df_cleaner.py module

Main features of this module:
    1. Read csv to pandas df in memory
    2. Clean up values in df columns
    3. Save as clean df  in csv format
"""
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import pandas as pd


log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

LOG_FILE = "dfcleaner.log"
# Create a rotating file handler
file_handler = RotatingFileHandler(LOG_FILE,
                                   maxBytes=1024 * 1024,
                                   backupCount=9)
file_formatter = logging.Formatter(
    "%(asctime)s [%(threadName)-12.12s] "
    "[%(levelname)-5.5s] : %(funcName)s: %(lineno)d: %(message)s")

file_handler.setFormatter(file_formatter)
log.addHandler(file_handler)

# Create a stdout (console) handler
stdout_handler = logging.StreamHandler(sys.stdout)
stdout_formatter = logging.Formatter(
    "%(asctime)s [%(threadName)-12.12s] "
    "[%(levelname)-5.5s] : %(funcName)s: %(lineno)d: %(message)s")

stdout_handler.setFormatter(stdout_formatter)
log.addHandler(stdout_handler)


def clean_data_frame(df_name):
    """Delete multiple latvian keywords from data frame to clean df"""
    log.info("Started latvian keyword remove from data frame")
    df = df_name.replace(to_replace=r'Istabas:>', value='', regex=True)
    df.replace(to_replace=r'Platiba:>', value='', regex=True, inplace=True)
    df.replace(to_replace=r'Stavs:>', value='', regex=True, inplace=True)
    df.replace(to_replace=r'/lifts', value='', regex=True, inplace=True)
    df.replace(to_replace=r'Iela:><b>', value='', regex=True, inplace=True)
    df.replace(to_replace=r'Price:>', value='', regex=True, inplace=True)
    df.replace(to_replace=r'Date:>', value='', regex=True, inplace=True)
    log.info("Completed latvian keyword remove from data frame")
    return df


def clean_sqm_column(df_name):
    """TODO: add docstring"""
    # Sptitting column value in to new columns by separator
    log.info("Started sqm column cleanup from data frame")
    df = df_name["Size_sq_m"].str.split(
        " ", n=1, expand=True)  # n=1 == in 2 slices
    # Create new column and sourcing data from 0th split index
    df_name["Size_sqm"] = df[0]  # 0 - index at separation
    df = df_name.loc[:, df_name.columns !=
                     'Size_sq_m']  # Drop old split column
    clean_df = df.loc[:, df.columns != 'Unnamed: 0']  # Drop duplicate  column
    log.info("Completed sqm column cleanup from data frame")
    return clean_df


def split_price_column(df_name):
    """TODO: add docstring"""
    # Spitting and cleanup for price column
    # value in to new columns by separator
    log.info("Started price column split")
    new = df_name["Price"].str.split("(", n=1, expand=True)
    # Creating separate columns for price and SQM new data frame
    df_name["Price_EUR"] = new[0]
    df_name["SQ_M_EUR"] = new[1]
    # Remove EUR sign in price column and remove space (split at 3 slices)
    no_euro_symb = df_name["Price_EUR"].str.split(" ", n=2, expand=True)
    # Creates new column and combines 2 indexes
    df_name["Price_in_eur"] = no_euro_symb[0] + no_euro_symb[1]
    # drop old split columns
    df = df_name.loc[:, df_name.columns != 'Price']
    final_df = df.loc[:, df.columns != 'Price_EUR']
    return final_df


def clean_sqm_eur_col(df_name):
    """TODO: add docstring"""
    # Split value at EUR  symbol
    log.info("Started EUR sqm column cleanup")
    new = df_name["SQ_M_EUR"].str.split("€", n=1, expand=True)
    # Create new column with from split df  and use only 0 index
    df_name["SQ_meter_price"] = new[0]
    # Remvoe space from clumn value strings
    df_name['SQ_meter_price'] = df_name['SQ_meter_price'].str.replace(' ', '')
    # Convert to float
    df_name['SQ_meter_price'] = df_name['SQ_meter_price'].astype(float)
    # Drop old SQ_M_EUR column
    final_df = df_name.loc[:, df_name.columns != 'SQ_M_EUR']
    log.info("combines EUR sqm column cleanup")
    return final_df


def save_text_report_to_file(text_lines: list, file_name: str) -> None:
    """Writes oneline data text to mailer report file"""
    log.info(f"Saving text report to file : {file_name}")
    with open(file_name, 'a') as the_file:
        for text_line in text_lines:
            the_file.write(f"{text_line}\n")
    text_line_cnt = len(text_lines)
    log.info(
        f"Completed writing {text_line_cnt} lines to {file_name} file ")


def create_email_body(clean_data_frame, file_name: str) -> None:
    """Creates categorized by room count ad hash : data for email body.

    Requires:
        clean_data_frame: pandas data frame

    Creates:
        email_body_txt_m4.txt: text file"""
    log.info(f"Started creation of {file_name} file")
    email_body_txt = []
    for room_count in range(4):
        room_count_str = str(room_count + 1)
        section_line = str(room_count_str + " room apartment segment:")
        email_body_txt.append(section_line)
        filtered_by_room_count = clean_data_frame.loc[clean_data_frame['Room_count'] == int(
            room_count_str)]
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
    log.info(f"Completed creation of {file_name} file")
    save_text_report_to_file(email_body_txt, file_name)


def df_cleaner_main():
    """ Cleans df, sorts df by price in EUR, save to csv file """
    log.info(" --- Started df_cleaner module ---")
    RAW_DATA_FILE = 'pandas_df.csv'
    DEFAULT_DATA_FILE = 'pandas_df_default.csv'
    EMAIL_BODY_OUTPUT_FILE = 'email_body_txt_m4.txt'
    try:
        log.info(f'Loading {RAW_DATA_FILE} file.')
        with open(RAW_DATA_FILE, 'r') as file:
            content = file.read()
            raw_data_frame = pd.read_csv(RAW_DATA_FILE)
            clean_df = clean_data_frame(raw_data_frame)
            clean_sqm_col = clean_sqm_column(clean_df)
            clean_price_col = split_price_column(clean_sqm_col)
            clean_df = clean_sqm_eur_col(clean_price_col)
            sorted_df = clean_df.sort_values(by='Price_in_eur', ascending=True)
            sorted_df.to_csv("cleaned-sorted-df.csv")
            all_ads_df = pd.read_csv("cleaned-sorted-df.csv", index_col=False)
            create_file_copy()
            create_email_body(all_ads_df, EMAIL_BODY_OUTPUT_FILE)
            log.info(
                f'Completed write data email template to {EMAIL_BODY_OUTPUT_FILE} file.')
            create_mb_file_copy()
    except FileNotFoundError:
        log.error(f'File {RAW_DATA_FILE} not found')
        try:
            log.info(f'Loading {DEFAULT_DATA_FILE} file.')
            with open(DEFAULT_DATA_FILE, 'r') as file:
                content = file.read()
                empty_df_mail_template = "No data was collected during last scraping job."
                with open(EMAIL_BODY_OUTPUT_FILE, 'w') as out_file:
                    # Write the entire string to the file
                    out_file.write(empty_df_mail_template)
                log.info(
                    f'Completed write empty email template to {EMAIL_BODY_OUTPUT_FILE} file.')
        except FileNotFoundError:
            log.error(f'{DEFAULT_DATA_FILE} does not exist.')
        except Exception as e:
            log.error(f"An error occurred: {e}")
    log.info(" --- Completed df_cleaner module ---")


def create_file_copy() -> None:
    """Creates file copy in data folder"""
    log.info(
        "Started copy of cleaned-sorted-df-YYYY-MM-DD.csv in data folder")
    todays_date = datetime.today().strftime('%Y-%m-%d')
    dest_file = 'cleaned-sorted-df-' + todays_date + '.csv'
    copy_cmd = 'cp cleaned-sorted-df.csv data/' + dest_file
    if not os.path.exists('data'):
        os.makedirs('data')
    os.system(copy_cmd)
    log.info(f"Completed creating file copy of {dest_file}")


def create_mb_file_copy() -> None:
    """Creates file copy in data folder"""
    log.info(
        "Started copy of email_body_txt_m4-YYYY-MM-DD.txt in data folder")
    todays_date = datetime.today().strftime('%Y-%m-%d')
    dest_file = 'email_body_txt_m4-' + todays_date + '.txt'
    copy_cmd = 'cp email_body_txt_m4.txt data/' + dest_file
    if not os.path.exists('data'):
        os.makedirs('data')
    os.system(copy_cmd)
    log.info(f"Completed creating file copy of {dest_file}")


if __name__ == "__main__":
    df_cleaner_main()
