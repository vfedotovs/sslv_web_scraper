#!/usr/bin/env python3
"""
data_format_changer.py module functionality is to convert scraped multiline
text data per advert entry in to singe line CSV format consumed by the
df_cleaner stage. (M8 Phase 2: pandas removed — stdlib csv only; the
output file keeps its historical pandas_df.csv name and exact format.)

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
import csv
import os
import re
import shutil
from datetime import datetime
import logging
import logging.handlers as handlers
from logging.handlers import RotatingFileHandler
import sys

# M7 P7: city-scoped hand-off filenames; fall back for standalone runs.
try:
    from app.wsmodules.file_paths import city_file
except Exception:
    def city_file(base_name, city=None):
        return f"{city}-{base_name}" if city else base_name


# M8 Phase 2: column order of the pandas_df.csv hand-off file (identical
# to the old DataFrame column order — the byte-level contract with
# df_cleaner and the golden-chain tests).
CSV_COLUMNS = ["URL", "Room_count", "Size_sq_m", "Floor",
               "Street", "Price", "Pub_date"]


log = logging.getLogger('data_format_changer')
log.setLevel(logging.INFO)
fastapi_log_format = logging.Formatter(
    "%(asctime)s [%(levelname)-5.5s] : %(funcName)s:"
    " %(lineno)d: %(message)s")

ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(fastapi_log_format)
log.addHandler(ch)

fh = handlers.RotatingFileHandler('raw_data_report_formatter.log',
                                  maxBytes=(1048576*5),
                                  backupCount=5)
fh.setFormatter(fastapi_log_format)
log.addHandler(fh)


def get_local_ws_fp(city_name: str = None) -> str:
    """Returns local web_scraper module output file path with today's date.
    Uses city_name if provided (e.g. 'jurmala-raw-data-report-...'), else legacy Ogre."""
    todays_date = datetime.today().strftime('%Y-%m-%d')
    prefix = (city_name + '-raw-data-report-') if city_name else 'Ogre-raw-data-report-'
    target_filename = prefix + todays_date + '.txt'
    return "data/" + target_filename


def get_cloud_ws_fp(city_name: str = None) -> str:
    """Returns cloud web_scraper module output file path with today's date.
    Uses city_name if provided, else legacy Ogre."""
    todays_date = datetime.today().strftime('%Y-%m-%d')
    prefix = (city_name + '-raw-data-report-') if city_name else 'Ogre-raw-data-report-'
    target_filename = prefix + todays_date + '.txt'
    return "local_lambda_raw_scraped_data/" + target_filename


def check_todays_cloud_data_file_exist() -> bool:
    """Checks if a cloud raw-data file for today exists in local_lambda_raw_scraped_data."""
    cloud_file_folder = "local_lambda_raw_scraped_data"
    todays_date = datetime.today().strftime('%Y-%m-%d')
    log.info("Attempting to find raw-data file scraped by lambda with date: %s ", todays_date)
    if not os.path.exists(cloud_file_folder):
        log.error("Folder %s does not exist. Creating empty folder ",
                  cloud_file_folder)
        os.makedirs(cloud_file_folder)
    for file_name in os.listdir(cloud_file_folder):
        if todays_date in file_name:
            log.info('File %s containing today'
                     ' date %s found', file_name, todays_date)
            return True
    log.info('File containing date %s not found', todays_date)
    return False


def get_detailed_file_path(city_name: str = None) -> str:
    """Returns detailed cloud file name matching today's date."""
    cloud_file_folder = "local_lambda_raw_scraped_data"
    todays_date = datetime.today().strftime('%Y-%m-%d')
    prefix = (city_name + '-raw-data-report-') if city_name else 'Ogre-raw-data-report-'
    for file_name in os.listdir(cloud_file_folder):
        if todays_date in file_name and (not city_name or city_name in file_name):
            return "local_lambda_raw_scraped_data/" + file_name
    # fallback
    for file_name in os.listdir(cloud_file_folder):
        if todays_date in file_name:
            return "local_lambda_raw_scraped_data/" + file_name


def cloud_data_formater_main(city_name: str = None) -> None:
    """Read raw data from {city}-raw-data-report.txt (or legacy Ogre) and
    save to {city}-pandas_df.csv (M7 P7: city-scoped hand-off file)."""
    log.info(' --- Started data_format_changer module ---')
    output_csv = city_file("pandas_df.csv", city_name)
    todays_cloud_ws_fp = get_cloud_ws_fp(city_name)
    log.info("Lambda scraped raw-data file path: %s ", todays_cloud_ws_fp)
    todays_local_ws_fp = get_local_ws_fp(city_name)
    todays_cloud_ws_file_exist = check_todays_cloud_data_file_exist()
    if todays_cloud_ws_file_exist is True:
        log.info("Lambda scraped raw-data file exists: %s ",
                str(todays_cloud_ws_file_exist))
        log.info("Creating one-line report from lambda "
                 "scraped raw-data file: %s", todays_cloud_ws_fp)
        detailed_cws_fp = get_detailed_file_path(city_name)
        rows = create_oneline_report(detailed_cws_fp)
        write_rows_to_csv(rows, output_csv)
        create_file_copy(output_csv)
    elif todays_cloud_ws_file_exist is False:
        log.warning("Lambda scraped raw-data file does not exist, "
                    "falling back to local scraper source file")
        log.info("Converting to csv format from local scraped "
                 "raw-data file: %s format", todays_local_ws_fp)
        rows = create_oneline_report(todays_local_ws_fp)
        if rows is not None:
            log.info("Saving csv format data to file %s ", output_csv)
            write_rows_to_csv(rows, output_csv)
            log.info("Saving csv format data file "
                     "%s completed with success", output_csv)
            create_file_copy(output_csv)
        if rows is None:
            log.error('row data is None')
            log.error("Saving csv format data file %s has failed", output_csv)
    log.info(' --- Finished data_format_changer module --- ')


def write_rows_to_csv(rows: list, dest_file: str) -> None:
    """M8 Phase 2: write ad row dicts to the pandas_df csv hand-off file.

    Byte-identical to the old DataFrame.to_csv() output: leading unnamed
    running-index column, CSV_COLUMNS order, '\\n' line endings, utf-8.
    An empty rows list still writes the header line (zero-new-ads day)."""
    log.info("Writing %d ad rows to %s", len(rows), dest_file)
    with open(dest_file, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow([""] + CSV_COLUMNS)
        for idx, row in enumerate(rows):
            writer.writerow([idx] + [row[column] for column in CSV_COLUMNS])


def get_file_path(city_name: str) -> str:
    """Builds file name based on date"""
    todays_date = datetime.today().strftime('%Y-%m-%d')
    if city_name is None:
        log.error('Error: city_name is None')
    if city_name is not None:
        target_filename = city_name + '-raw-data-report-' + todays_date + '.txt'
        full_file_path = "data/" + target_filename
        log.info("File path: %s", full_file_path )
        return full_file_path


def create_oneline_report(source_file: str) -> list:
    """Changes text file format(12 lines per ad entry)
    to csv file format (1 line per ad entry)

    12 line data format for each scraped ad entry in {city}-raw-data-report-YYYY-MM-DD.txt
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
    0,https://ss.lv/msg/lv/real-estate/flats/ogre-and-reg/ogre/fxobe.html,
    Istabas:>2,Platiba:>50 m²,Stavs:>3/9/lifts,Iela:><b>Jaunatnes iela 4, 
    Price:>57 000 € (1 140 €/m²),Date:>01.02.2022


    Args:
        source_file: text file data/{city}-raw-data-report-YYYY-MM-DD.txt
    Returns:
       list of dicts, one per ad, keyed by CSV_COLUMNS
       (M8 Phase 2: replaced the pd.DataFrame return)
    """
    urls = []
    room_counts = []
    room_sizes = []
    room_streets = []
    room_prices = []
    room_floors = []
    publish_dates = []
    log.info("Converting raw-text 12 lines per entry fromat into "
             " 1 line per entry csv file format ")
    log.info("Reading data from file : %s", source_file )
    try:
        with open(source_file, 'r', encoding='utf-8') as file_handle:
            while True:
                line = file_handle.readline()
                match_url = re.search("https", line)
                if match_url:
                    # log.info("L1 element: %s" ,line )
                    urls.append(line.rstrip('\n'))
                match_room_count = re.search("Istabas:", line)
                if match_room_count:
                    # log.info("L2 element: %s" ,line )
                    room_counts.append(line.rstrip('\n'))
                match_room_street_count = re.search("Iela:", line)
                if match_room_street_count:
                    # log.info("L3 element: %s" ,line )
                    room_streets.append(line.rstrip('\n'))
                match_room_price = re.search("Price:", line)
                if match_room_price:
                    # log.info("L4 element: %s" ,line )
                    room_prices.append(line.rstrip('\n'))
                match_pub_date = re.search("Date:", line)
                if match_pub_date:
                    # log.info("L5 element: %s" ,line )
                    publish_dates.append(line.rstrip('\n'))
                match_room_size = re.search("Platība:", line)
                if match_room_size:
                    tmp = line.rstrip('\n')
                    sizes = tmp.replace("Platība:", "Platiba:")
                    # log.info("L6 element: %s" , sizes )
                    room_sizes.append(sizes)
                match_room_floor = re.search("Stāvs:", line)
                if match_room_floor:
                    tmp = line.rstrip('\n')
                    floors = tmp.replace("Stāvs:", "Stavs:")
                    # log.info("L7 element: %s" ,floors )
                    room_floors.append(floors)
                if not line:
                    break
            lists = [urls, room_counts, room_sizes, room_floors,
                room_streets, room_prices, publish_dates]
            validate_list_lengths(lists)
            trimmed_lists = trim_lists_to_min_length(
                urls,
                room_counts,
                room_sizes,
                room_floors,
                room_streets,
                room_prices,
                publish_dates
            )
            validate_list_lengths(trimmed_lists)
            (nurls, nroom_counts, nroom_sizes, nroom_floors,
            nroom_streets, nroom_prices, npublish_dates) = trimmed_lists
            log.info("Creating row dicts from scraped raw data list datastructures")
            # M8 Phase 2: plain row dicts instead of a pandas DataFrame
            ad_rows = [
                dict(zip(CSV_COLUMNS, values))
                for values in zip(nurls, nroom_counts, nroom_sizes,
                                  nroom_floors, nroom_streets,
                                  nroom_prices, npublish_dates)
            ]
            log.info("Created %d ad row(s) from raw data", len(ad_rows))
            return ad_rows
    except FileNotFoundError:
        log.error("Source raw-data text file: %s does not exist", source_file)
        raise
    except Exception as e:
        log.error(
            "An error occurred while processing the file %s : %s ", source_file, str(e))
        raise


def validate_list_lengths(lists) -> None:
    """
    Validates that all provided lists have the same length.

    Args:
        lists (list of lists): A list containing the lists to be validated.

    Raises:
        ValueError: If any of the lists have different lengths, the error is logged and then raised.
    """
    log.info("Validating that all provided data element lists have the same length")
    list_lengths = [len(lst) for lst in lists]
    if len(set(list_lengths)) > 1:
        error_message = f"All lists must have the same length. Found lengths: {list_lengths}"
        log.error(error_message)
        # raise ValueError(error_message)
    log.info("Validation for all provided data element lists completed successfully")


def trim_lists_to_min_length(list1, list2, list3,
                             list4, list5, list6, list7) -> list:
    """
    Trims all input lists to the length of the shortest list.

    Args:
        list1, list2, list3, list4, list5 ...: Input lists to be trimmed.

    Returns:
        A list containing the five trimmed lists.
    """
    log.info("Started triming lists to the same len... ")
    lists = [list1, list2, list3, list4, list5, list6, list7]
    min_length = min(len(lst) for lst in lists)
    trimmed_lists = [lst[:min_length] for lst in lists]
    return trimmed_lists


def create_file_copy(source_file: str = "pandas_df.csv") -> None:
    """
    Creates a timestamped backup copy of the pandas_df csv in the 'data'
    directory (e.g. 'jurmala-pandas_df_YYYY-MM-DD.csv'). M7 P7: the source
    name is city-scoped and the copy uses shutil instead of os.system(cp).

    Raises:
        OSError: If the copying of the file fails, although this is not
        explicitly caught in this function.
    """
    todays_date = datetime.today().strftime('%Y-%m-%d')
    base_name = source_file[:-len('.csv')] if source_file.endswith('.csv') else source_file
    dest_file = base_name + '_' + todays_date + '.csv'
    log.info("Creating backup of file: %s into folder 'data/'", dest_file)

    if not os.path.exists('data'):
        log.warning("'data' folder does not exist. Creating folder.")
        os.makedirs('data')

    try:
        dest_path = os.path.join('data', dest_file)
        shutil.copy2(source_file, dest_path)
        file_size = os.path.getsize(dest_path)
        log.info("Completed moving file: %s to folder 'data/' with success."
                 "File size: %d bytes", dest_file, file_size)
    except OSError as e:
        log.error("Failed to copy %s to data/: %s", source_file, str(e))


if __name__ == "__main__":
    cloud_data_formater_main()
