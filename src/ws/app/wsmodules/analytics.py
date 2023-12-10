""" analitics.py module
This module  main functionality:
    1. Load pandas data frame from cleaned-sorted-df.csv file
    2. Split data frame to 4 data frames filtered by room count criteria
    3. Calculate basic price stats (min/max/average price for each cateogry)
       and save to file  basic_price_stats.txt
    4. basic_price_stats.txt later is used by pdf_cretor.py module to
       include in pdf file

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
import logging
from logging import handlers
from logging.handlers import RotatingFileHandler
import sys
import os
import pandas as pd
from tabulate import tabulate


log = logging.getLogger('analytics')
log.setLevel(logging.INFO)
fa_log_format = logging.Formatter(
    "%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]"
    " : %(funcName)s: %(lineno)d: %(message)s"
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


def analytics_main() -> None:
    """Main enrty point in module"""
    log.info(" --- Starting analitics module --- ")
    # REQUIRED_FILES = ['cleaned-sorted-df.csv']
    data_frame_file_exists = file_exists(DATA_FRAME_FILE)
    if data_frame_file_exists:
        log.info(f'Requred input file {DATA_FRAME_FILE} exists.')
        full_data_frame = pd.read_csv(DATA_FRAME_FILE, index_col=False)
        data_frame_segments = split_dataframe_by_column(
            full_data_frame, ROOM_COUNT_COLUMN)
        price_stats_by_room = extract_data_from(
            PRICE_COLUMN, data_frame_segments)
        calc_price_data = calculate_price_stats(price_stats_by_room)
        formatted_price_stats = format_price_stats_data(
            calc_price_data)
        write_report_to(TEMP_OUTPUT_FILE, formatted_price_stats)
    else:
        log.error(f'Requred input file {DATA_FRAME_FILE} DOES NOT exist.')
    log.info(" --- Ended analitics module --- ")


def extract_data_from(column_name: str, data_frame_segments) -> dict:
    """Extracts price data from specified column for different room
       count segments.

    Args:
        column_name (str): The name of the column from which to extract data.
        data_frame_segments (dict): A dictionary containing room count segments
            as keys and corresponding DataFrame segments as values.

    Returns:
        dict: A dictionary where keys are room count values, and values are
        lists containing the extracted price data for each room count segment.

    Note:
        Function expects that each DataFrame segment in `data_frame_segments`
        has the specified `column_name`.
    """
    stats_data = {}
    if data_frame_segments is not None:
        for room_count_value, add_data in data_frame_segments.items():
            curr_room_value_prices = add_data[column_name].tolist()
            stats_data[room_count_value] = curr_room_value_prices
    for key, value in stats_data.items():
        log.info(f'Extracted price data for {key} '
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


def split_dataframe_by_column(dataframe, column_name: str) -> dict:
    """
    Split DataFrame into multiple DataFrames based on unique values
    in the specified column.

    Parameters:
    - dataframe (pd.DataFrame): The input DataFrame.
    - column_name (str): The name of the column for which
      to split DataFrame.

    - Returns:
    - dict (vale: pd.DataFrame) or None: The dict of DataFrames
      if the DataFrame is not empty, otherwise returns None.
    """
    if not dataframe.empty:
        log.info('Loaded DataFrame is not empty')
        unique_values = dataframe[column_name].unique()
        log.info(
            f'Found these {unique_values} values '
            f'in DataFrame {column_name} column'
        )
        dataframes = {
            value: dataframe[dataframe[column_name] == value]
            for value in unique_values
        }
        return dataframes
    else:
        log.error('Loaded DataFrame is empty')
        return None


def get_column_dtype(dataframe, column_name: str) -> str:
    """
    Get the data type of a specific column in a DataFrame.

    Parameters:
    - dataframe (pd.DataFrame): The input DataFrame.
    - column_name (str): The name of the column for which
      to retrieve the data type.

    - Returns:
    - numpy.dtype (str) or None: The data type of the
      specified column if the DataFrame is not empty,
      otherwise returns None.
    """
    if not dataframe.empty:
        column_dtype = str(dataframe[column_name].dtype)
        log.info(f'DataFrame column: {column_name} dtype is : {column_dtype}')
        return column_dtype
    else:
        log.error('Loaded DataFrame is empty')
        return None


if __name__ == "__main__":
    analytics_main()
