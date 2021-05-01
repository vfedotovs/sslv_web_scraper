""" analitics.py module
This module  main functionality:
    1. Load pandas data frame from cleaned-sorted-df.csv file
    2. Split data frame to 4 data frames filtered by room count criteria
    3. Calculate basic price statistics (min/max/average price for each cateogry)
    and save to file  basic_price_stats.txt
    4. basic_price_stats.txt later is used by pdf_cretor.py module to include in pdf file
"""
import pandas as pd


print("Debug info: Starting analitics module ... ")
# Load df from cleaned df csv file
all_ads_df = pd.read_csv("cleaned-sorted-df.csv", index_col=False)
# Split all apartment dataframe in 4 categories
# Create 4 dataFrames filtered by room count
only_1_rooms = all_ads_df[all_ads_df['Room_count'] == 1]
only_2_rooms = all_ads_df[all_ads_df['Room_count'] == 2]
only_3_rooms = all_ads_df[all_ads_df['Room_count'] == 3]
only_4_rooms = all_ads_df[all_ads_df['Room_count'] == 4]
cat_list = [only_1_rooms, only_2_rooms, only_3_rooms, only_4_rooms, all_ads_df]


def mini_report(df_name):
    """ Convert df column to list  and calculate basics stats """
    # extracts only EUR price column values and adds to list
    lines = []
    filter_col = 'Price_in_eur'
    price_list = df_name[filter_col].tolist()
    # print("Debug info: ", price_list)
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


def iterate_reports() -> None:
    """ Function iterates over cat_list objects and prints basic stats to STDOUT
    Example of printout:
    # print("Advertisement count: ",  len(price_list))
    # print(f'Average price: {avg_price} EUR')
    # print(f'Min price: {min_price} EUR')
    # print(f'Max price: {max_price} EUR')
    # print(f'Price range: {price_range} ')
    """
    stats_report_lines = []
    txt_reports = []
    for i, cat in enumerate(cat_list):
        cat_report = mini_report(cat)
        txt_reports.append(cat_report)
    for i, reports in enumerate(txt_reports):
        empty_line = ' '
        title_line = ("### " + str(i + 1) + " room apartment price analysis ###")
        stats_report_lines.append(empty_line)
        stats_report_lines.append(title_line)
        for line in reports:
            stats_report_lines.append(line)
    return stats_report_lines


def write_lines(text_lines: list, file_name: str) -> None:
    """ Function writes text lines to file"""
    with open(file_name, 'w') as filehandle:
        filehandle.writelines("%s\n" % line for line in text_lines)


txt_lines_for_save = iterate_reports()
write_lines(txt_lines_for_save, 'basic_price_stats.txt')
print("Debug info: Completed analitics  module ... ")


# Module functional requirements
# Category 1 - analysis by advert price:
# 2. I have interested in 1  and 2 rooms     - implemented
# 3. get count of apartments for sale        - implemented
# 4. get price range for each room category  - implemented
# 5. get min / max / average price           - implemented

# Next 3 most valuable features:
# Category 3 advert floor location analysis - improves filtering out not needed candidates
#    - complexity to implement easy
#    - need to detect first and last flor  1/x or  5/5 or x/9
#    - need exclude first and last floor and 9 floor houses

# This will be when database milestone will be implemented
# Category 5 listed date analysis - requires correct datapoint fix bug
# Category 6 advert view count analysis - requires correct datapoint fix bug


# Category 2 advert SQ meter analysis
# 6. get min / max / average sqm size
# 7. print chart price sqm

# Category 4 advert street location analysis
