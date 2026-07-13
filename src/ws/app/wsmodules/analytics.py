#!/usr/bin/env python3
""" analitics.py module
This module  main functionality:
    1. Load ad rows from cleaned-sorted-df.csv file (M8 Phase 4:
       stdlib csv, pandas removed)
    2. Group ad prices by room count value
    3. Calculate basic price stats (min/max/average price for each cateogry)
       and save to file  basic_price_stats.txt
    4. basic_price_stats.txt later is used by aws_mailer.py module to
       include in the report email

# Functionality that is planned to be implemented
    # - FIXME: need to implement
    # Category 2 - analysis by advert square meter price
    # 6. get min / max / average sqm size
    # 7. print chart price sqm

    # - FIXME: need to implement
    # Category 2 - filter adverts by floor location analysis
    #    - improves filtering out not needed candidates
    #    - complexity to implement easy
    #    - need to detect first and last flor  1/x or  5/5 or x/9
    #    - need exclude first and last floor and 9 floor houses

    # - FIXME: need to implemet
    # This will be when database milestone will be implemented
    # Category 5 listed date analysis - requires correct datapoint fix bug
    # Category 6 advert view count analysis
    #     - requires correct datapoint fix bug
    # Category 4 advert street location analysis
"""
import csv
import logging
from logging import handlers
from logging.handlers import RotatingFileHandler
import sys
import os
from tabulate import tabulate

# M7 P7: city-scoped hand-off filenames; fall back for standalone runs.
try:
    from app.wsmodules.file_paths import city_file
except Exception:
    def city_file(base_name, city=None):
        return f"{city}-{base_name}" if city else base_name


log = logging.getLogger('analytics')
log.setLevel(logging.INFO)
fa_log_format = logging.Formatter(
    "%(asctime)s [%(levelname)-5.5s]: %(funcName)s: %(lineno)d: %(message)s"
)
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(fa_log_format)
log.addHandler(ch)
fh = handlers.RotatingFileHandler(
    'analytics.log', maxBytes=(1048576*5), backupCount=7)
fh.setFormatter(fa_log_format)
log.addHandler(fh)


DATA_FRAME_FILE = 'cleaned-sorted-df.csv'
ROOM_COUNT_COLUMN = 'Room_count'
PRICE_COLUMN = 'Price_in_eur'
TEMP_OUTPUT_FILE = 'basic_price_stats.txt'  # is used by pdf_cretor.py module
# PRICE_STATS_DATA = 'Price_stats_by_room_segment.txt'


def analytics_main(city_name: str = None) -> None:
    """Main enrty point in module.
    M7 P7: input/output hand-off filenames are city-scoped when given.
    M8 Phase 4: stdlib csv + dict grouping instead of pandas."""
    log.info(" --- Starting analitics module --- ")
    data_frame_file = city_file(DATA_FRAME_FILE, city_name)
    output_file = city_file(TEMP_OUTPUT_FILE, city_name)
    data_frame_file_exists = file_exists(data_frame_file)
    if data_frame_file_exists:
        log.info(f'Requred input file {data_frame_file} exists.')
        with open(data_frame_file, 'r', encoding='utf-8', newline='') as fh:
            ad_rows = list(csv.DictReader(fh))
        price_stats_by_room = group_prices_by_room(ad_rows)
        calc_price_data = calculate_price_stats(price_stats_by_room)
        formatted_price_stats = format_price_stats_data(
            calc_price_data)
        write_report_to(output_file, formatted_price_stats)
    else:
        log.error(f'Requred input file {data_frame_file} DOES NOT exist.')
    log.info(" --- Ended analitics module --- ")


def group_prices_by_room(ad_rows: list) -> dict:
    """Groups ad prices by room count value.

    M8 Phase 4: replaces split_dataframe_by_column + extract_data_from.
    Casts at read (csv yields strings): Room_count -> int keys so
    segments sort numerically like the old int64 column, Price_in_eur
    -> int values so min/max/avg math stays numeric.

    Args:
        ad_rows: list of cleaned ad row dicts (cleaned-sorted-df.csv)

    Returns:
        dict: {room_count (int): [price (int), ...]}
    """
    stats_data = {}
    if not ad_rows:
        log.error('Loaded ad rows list is empty')
        return stats_data
    for row in ad_rows:
        room_count = int(row[ROOM_COUNT_COLUMN])
        stats_data.setdefault(room_count, []).append(int(row[PRICE_COLUMN]))
    # M7 P9: counts at INFO, full price lists only at DEBUG
    for key, value in stats_data.items():
        log.info(f'Extracted {len(value)} prices for {key} room segment')
        log.debug(f'Extracted price data for {key} '
                  f'room segment prices: {value}')
    return stats_data


def calculate_price_stats(price_data: dict) -> dict:
    """Calculates min, average, max, and price range for each room segment.

    Args:
        price_data (dict): A dictionary where keys are room segments and values
                          are lists of prices.

    Returns:
        dict: A dictionary containing calculated statistics for eachroom
              room segment.
              Keys are room segments, and values are lists containing:
              [ad_count, min_price, max_price, price_range, avg_price].
    """
    calculated_data = {}
    sorted_price_data = dict(sorted(price_data.items()))
    for room_vlaue, prices in sorted_price_data.items():
        data_values = []
        ad_count = str(len(prices))
        min_price = str(min(prices))
        max_price = str(max(prices))
        avg_price = str((min(prices) + max(prices)) / 2)
        price_range = str(max(prices) - min(prices))
        data_values.append(ad_count)
        data_values.append(min_price)
        data_values.append(max_price)
        data_values.append(price_range)
        data_values.append(avg_price)
        calculated_data[room_vlaue] = data_values
    for key, value in calculated_data.items():
        log.info(f'Calculated price data for {key} room segment data: {value}')
    return calculated_data


def format_price_stats_data(price_data: dict) -> list:
    """Format price data into a table format.

    Args:
        price_data (dict): A dictionary containing room segments as keys
                          and corresponding price statistics.

    Returns:
        list: A list representing the formatted table.

    This function takes a dictionary of price data, sorts it by room segments,
    and formats it into a table using the tabulate module. The resulting table
    includes columns for 'Room Segment', 'Ad count', 'Min Price', 'Max Price',
    'Price Range', and 'Avg Price'.
    """
    log.info('Formatting to table format price column data ...')
    ordered_data = dict(sorted(price_data.items()))
    table_data = [(key, *value) for key, value in ordered_data.items()]
    headers = ['Room Segment', 'Ad count', 'Min Price',
               'Max Price', 'Price Range', 'Avg Price']
    table = tabulate(table_data, headers=headers, tablefmt="pretty")
    return table


def write_report_to(file_name: str, report_data: list) -> None:
    """Writes formatted statistical data to file.

    Args:
        file_name (str): Name of the file to write the lines to.
        report_data (list): List of strings representing
                            the lines to be written.

    Returns:
        None
    """
    log.info(f'Writing stats report data to {file_name} file ...')
    with open(file_name, 'w') as file:
        file.write(report_data)


def file_exists(file_name) -> bool:
    """
    Check if the file exists.

    Parameters:
    - file_name (str): The name of the file to check.

    Returns:
    - bool: True if the file exists, False otherwise.
    """
    return os.path.exists(file_name)


if __name__ == "__main__":
    analytics_main()
