""" analitics.py module
This module  main functionality:
    1. Load pandas data frame from cleaned-sorted-df.csv file
    2. Split data frame to 4 data frames filtered by room count criteria
    3. Calculate basic price statistics (min/max/average price for each cateogry)
    and save to file  basic_price_stats.txt
    4. basic_price_stats.txt later is used by pdf_cretor.py module to include in pdf file
"""
import logging
from logging import handlers
from logging.handlers import RotatingFileHandler
import sys
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


def analytics_main() -> None:
    """Main enrty point in module"""
    log.info(" --- Starting analitics module --- ")
    REQUIRED_FILES = ['cleaned-sorted-df.csv']
    check_files(REQUIRED_FILES)
    # df = load_csv_to_df('cleaned-sorted-df.csv')
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

    # Category 2 - analysis by advert square meter price - FIXME: need to implemet
    # 6. get min / max / average sqm size
    # 7. print chart price sqm

    # Next 3 most valuable features: - FIXME: need to implemet
    # Category 2 - filter adverts by floor location analysis
    #    - improves filtering out not needed candidates
    #    - complexity to implement easy
    #    - need to detect first and last flor  1/x or  5/5 or x/9
    #    - need exclude first and last floor and 9 floor houses

    # This will be when database milestone will be implemented - FIXME: need to implemet
    # Category 5 listed date analysis - requires correct datapoint fix bug
    # Category 6 advert view count analysis - requires correct datapoint fix bug
    # Category 4 advert street location analysis


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


def categorize_data() -> list:
    """Load all apartment data to df and Split in 4 categories based on room count"""
    log.info('Categorizing all apartment data in categories based on room count ')
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
    log.info(f'Calculating stats_by_price for data frame')
    lines = []
    filter_col = 'Price_in_eur'
    price_list = df_name[filter_column].tolist()
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


def create_multi_category_stats(data_frames: list) -> list:
    """Create elemenntary price type report from all data frames

    Example of printout:
    # Title line
    # print("Advertisement count: ",  len(price_list))
    # print(f'Average price: {avg_price} EUR')
    # print(f'Min price: {min_price} EUR')
    # print(f'Max price: {max_price} EUR')
    # print(f'Price range: {price_range} ')

    Returns: list of 4 lists that is used for writing in file and creting pdf file"""
    log.info('Creating stats_by_price report for each for apartment type category')

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
