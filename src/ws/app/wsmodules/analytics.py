""" analitics.py module
This module  main functionality:
    1. Load pandas data frame from cleaned-sorted-df.csv file
    2. Split data frame to 4 data frames filtered by room count criteria
    3. Calculate basic price stats (min/max/average price for each cateogry)
    and save to file  basic_price_stats.txt
    4. basic_price_stats.txt later is used by pdf_cretor.py module to include in pdf file
    
"""
import logging
from logging import handlers
from logging.handlers import RotatingFileHandler
import sys
import os
import pandas as pd


log = logging.getLogger('analytics')
log.setLevel(logging.INFO)
fa_log_format = logging.Formatter(
    "%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s] : %(funcName)s: %(lineno)d: %(message)s")
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


def analytics_main() -> None:
    """Main enrty point in module"""
    log.info(" --- Starting analitics module --- ")
    REQUIRED_FILES = ['cleaned-sorted-df.csv']
    data_frame_file_exists = file_exists(DATA_FRAME_FILE)
    if data_frame_file_exists:
        log.info(f'Requred input file {DATA_FRAME_FILE} exists.')
        full_data_frame = pd.read_csv(DATA_FRAME_FILE, index_col=False)
        col_dtype = get_column_dtype(full_data_frame, ROOM_COUNT_COLUMN)
        if col_dtype == 'object':
            data_frame_segments = split_dataframe_by_column(
                full_data_frame, ROOM_COUNT_COLUMN)
            # print(data_frame_segments)i

    check_files(REQUIRED_FILES)
    categorized_dfs = categorize_data()  # list of 4 data frames

    # Module functional requirements
    # Category 1 - analysis by advert price:
    # 1. I have interested in 1  and 2 rooms     - implemented
    # 2. get count of apartments for sale        - implemented
    # 3. get price range for each room category  - implemented
    # 4. get min / max / average price           - implemented
    price_data = create_multi_category_stats(categorized_dfs)
    write_lines(price_data, 'basic_price_stats.txt')
    log.info(" --- Ended analitics module --- ")

    # - FIXME: need to implement
    # Category 2 - analysis by advert square meter price
    # 6. get min / max / average sqm size
    # 7. print chart price sqm

    # Next 3 most valuable features:
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


def file_exists(file_name) -> bool:
    """
    Check if the file exists.

    Parameters:
    - file_name (str): The name of the file to check.

    Returns:
    - bool: True if the file exists, False otherwise.
    """
    return os.path.exists(file_name)


def check_files(file_names: list) -> None:
    """Verifying if required module files exist before executing module code"""
    log.info('Verifying if all required module exist')
    for file in file_names:
        try:
            file_handle = open(file, 'r')
        except IOError:
            log.error(
                f'There was an error opening the file {file} or it does not exist!')
            sys.exit()


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


def categorize_data() -> list:
    """Load all apartment data to df and split
    in 4 categories based on room count"""
    log.info(
        'Categorizing all apartment data in categories based on room count ')
    all_ads_df = pd.read_csv("cleaned-sorted-df.csv", index_col=False)
    only_1_rooms = all_ads_df[all_ads_df['Room_count'] == 1]
    only_2_rooms = all_ads_df[all_ads_df['Room_count'] == 2]
    only_3_rooms = all_ads_df[all_ads_df['Room_count'] == 3]
    only_4_rooms = all_ads_df[all_ads_df['Room_count'] == 4]
    cat_list = [only_1_rooms, only_2_rooms,
                only_3_rooms, only_4_rooms, all_ads_df]
    return cat_list


def calculate_stats_by_price(df_name, filter_column: str) -> list:
    """Extracts only EUR price column values, calculates elementary stats:
        1. Total ad count
        2. Min/Max price
        3. Average price
        4. Price range

        Returns these values as list"""
    log.info(f'Calculating stats_by_price basd on column: {filter_column} ')
    lines = []
    price_list = df_name[filter_column].tolist()
    if len(price_list) > 0:
        avg_price = sum(price_list) / len(price_list)
        avg_price = str(round(avg_price, 2))
        min_price = min(price_list)
        max_price = max(price_list)
        price_range = max_price - min_price
        str_ac = "Advertisement count: " + str(len(price_list))
        str_avp = "Average price: " + str(avg_price) + " EUR"
        str_minp = "Min price: " + str(min_price) + " EUR"
        str_maxp = "Max price: " + str(max_price) + " EUR"
        str_pr = "Price range: " + str(price_range)
        lines.append(str_ac)
        lines.append(str_avp)
        lines.append(str_minp)
        lines.append(str_maxp)
        lines.append(str_pr)
        return lines
    else:
        log.error(f'Column {filter_column} has 0 prices')
        str_ac = "Advertisement count: 0"
        str_avp = "Average price: 0 EUR"
        str_minp = "Min price: 0 EUR"
        str_maxp = "Max price: 0 EUR"
        str_pr = "Price range: 0"
        lines.append(str_ac)
        lines.append(str_avp)
        lines.append(str_minp)
        lines.append(str_maxp)
        lines.append(str_pr)
        return lines


def create_multi_category_stats(data_frames: list) -> list:
    """
    Create a statistical report for different apartment
    categories based on price.

    This function generates a summary report containing information
    such as the number of advertisements, average price, minimum price,
    maximum price, and price range for each apartment category.

    Example of printout:
    # Title line
    # print("Advertisement count: ", len(price_list))
    # print(f'Average price: {avg_price} EUR')
    # print(f'Min price: {min_price} EUR')
    # print(f'Max price: {max_price} EUR')
    # print(f'Price range: {price_range} ')

    Parameters:
    - data_frames (list): A list of pandas DataFrames representing
      different apartment categories.

    Returns:
    - list: A list of strings containing the statistical report for
      each apartment category.
      This can be used for writing to a file or creating a PDF report.
    """
    log.info(
        'Creating price column stats report for each apartment type category')
    # TODO - refactor this function
    stats_report_lines = []
    txt_reports = []
    for i, current_df in enumerate(data_frames):
        df_report = calculate_stats_by_price(current_df, 'Price_in_eur')
        txt_reports.append(df_report)
    for i, reports in enumerate(txt_reports):
        empty_line = ' '
        title_line = ("### " + str(i + 1) +
                      " room apartment price analysis ###")
        stats_report_lines.append(empty_line)
        stats_report_lines.append(title_line)
        for line in reports:
            stats_report_lines.append(line)
    return stats_report_lines


def write_lines(text_lines: list, file_name: str) -> None:
    """Function writes text lines to file"""
    log.info(f'Saving analysis_by_price to {file_name} file')
    with open(file_name, 'w') as filehandle:
        filehandle.writelines("%s\n" % line for line in text_lines)


if __name__ == "__main__":
    analytics_main()
