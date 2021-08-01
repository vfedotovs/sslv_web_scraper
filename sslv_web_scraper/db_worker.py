#!/usr/bin/env python3
"""
db_worker module is used to connect with postgres database and store data in
2 tables listed_ads and removed_ads for tracking currently listed ads,
tracking how many days they stay in listed state, move ads to delisted_ads
table after ads are removed from website and reporting capability.
Todo functionality:
0.[x] Import modules and set up logging
1.[x] Load daily csv data to data frame
2.[x] Extract (todays_url_hashes) from data frame
3.[x] Extract (still_listed_table_hashes) from db listed_ads table
4.[x] Compared todays df with still listed table hashes, now hashes are sorted:
-- new_msg_hashes
-- still_listed_msg_hashes
-- to_remove_msg_hashes
Next step extract 2 data dicts from df and one from db
5.[x] extract new_msg_data from df - based on new_msg_hashes and df
6.[x] extract to_removed_msg_data  from db listed_ads table - based on to_remove_hashes
7.[x] Insert new_msg_data to listed_ads table
8.[x] Insert to_remove_msg_data to removed_ads table
9.[x] Delete db rows in listed table based on to_remove_msg_hashes

TODO:
10.[] Update listed table: still_listed_msg_hashed for check and update listed days count every run
11.[] Check and update days listed in listed table rows based still_listed_msg_hashes
12.[] Check if report day by last x days count and  generate report
13.[] Write tests for db_worker module
"""
import sys
import logging
from logging.handlers import RotatingFileHandler
import pandas as pd
import psycopg2
from config import config
from datetime import datetime


logger = logging.getLogger('db_worker')
logger.setLevel(logging.INFO)
fh = logging.handlers.RotatingFileHandler('dbworker.log', maxBytes=1000000, backupCount=10)
fh.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s: %(name)s: %(levelname)s: %(funcName)s: %(lineno)d: %(message)s')
fh.setFormatter(formatter)
logger.addHandler(fh)


def db_worker_main() -> None:
    """db_worker.py module main function"""
    logger.info(" --- Satrting db_worker module ---")
    requred_files = ['cleaned-sorted-df.csv','database.ini']
    check_files(requred_files)
    df = load_csv_to_df('cleaned-sorted-df.csv')
    # Extract new and still listed message url hashes
    todays_url_hashes = extract_url_hashes_from_df(df)
    still_listed_table_url_hashes = extract_listed_url_hashes_from_db()
    # Sorting all hashes to 3 categories (new, still_listed, to_remove)
    hashe_categories = compare_df_to_db_hashes(todays_url_hashes,still_listed_table_url_hashes)
    new_msg_hashes = hashe_categories[0]
    still_listed_msg_hashes = hashe_categories[1]
    to_remove_msg_hashes = hashe_categories[2]
    # Extract new msg data dict from df
    new_msg_data = extract_new_msg_data(df, new_msg_hashes)
    # Extract to_remove msg data dict from db listed_ads table
    to_removed_msg_data = extract_to_remove_msg_data(to_remove_msg_hashes)
    # Extract data for messages that need to increment listed days value in db
    to_increment_msg_data = extract_to_increment_msg_data(still_listed_msg_hashes)
    # Insert new msg data dict to listed_ads table
    insert_data_to_listed_table(new_msg_data)
    # Insert to_remove msg data dict to removed_ads table
    insert_data_to_removed_table(to_removed_msg_data)
    # Remove rows from listed_ads based on  to_remove hashes msg
    delete_db_listed_table_rows(to_remove_msg_hashes)
    # Check and increment/update listed_ads all rows for listed days count value 
    update_dlv_in_db_table(to_increment_msg_data, todays_date)
    logger.info(" --- Ended db_worker module ---")


def check_files(file_names: list) -> None:
    """Testing if file exists and can be opened"""
    for f in file_names:
        try:
            file = open(f, 'r')
        except IOError:
            logger.error(f'There was an error opening the file {f} or file does not exist!')
            sys.exit()


def load_csv_to_df(csv_file_name: str):
    """reads csv file and return pandas data frame"""
    df = pd.read_csv(csv_file_name)
    logger.info(f'Loaded {csv_file_name} file to pandas data frame in memory')
    return df


def extract_url_hashes_from_df(df_name) -> list:
    """exctracts from df url column links from all rows and
    from each link extracts uniq url hash"""
    url_hashes =[]
    urls = df_name['URL'].tolist()
    for full_url in urls:
        url_hash = extract_hash(full_url)
        url_hashes.append(url_hash)
    logger.info(f'Extracted {len(url_hashes)} url hashes from pandas data frame')
    return url_hashes


def extract_hash(full_url: str) -> str:
    """Exctracts 5 caracter hash from URL link and returns hash"""
    chunks = full_url.split("/", 9)
    last_chunk = chunks[9]
    split_chunk = last_chunk.split(".")
    url_hash = split_chunk[0]
    return url_hash


def extract_listed_url_hashes_from_db():
    """Iterate over all rows in  listed_ads table and
    extract each url hash column value and return as list of hashes"""
    conn = None
    listed_db_hashes = []
    try:
        params = config()
        conn = psycopg2.connect(**params)
        cur = conn.cursor()
        cur.execute("SELECT url_hash FROM listed_ads ORDER BY url_hash")
        row = cur.fetchone()
        while row is not None:
            listed_db_hashes.append(row)
            row = cur.fetchone()
        cur.close()
    except (Exception, psycopg2.DatabaseError) as error:
        print(error)
    finally:
        if conn is not None:
            conn.close()
    clean_hashes = []
    for element in listed_db_hashes:
        str_element =  ''.join(element)
        clean_element = str_element.replace("'", "").replace(")", "")
        clean_hash = clean_element.replace("(", "").replace(",", "")
        clean_hashes.append(clean_hash)
    logger.info(f'Extracted {len(clean_hashes)} hashes from database listed_ads table')
    return clean_hashes


def compare_df_to_db_hashes(df_hashes: list, db_hashes: list) -> list:
    """ This should allow to conclude if hash is new, still seen, to_remove"""
    hash_categories = []
    new_ads = []
    existing_ads = []
    removed_ads = []
    logger.info(f'Comparing {len(df_hashes)} data frame hashes with {len(db_hashes)} listed table hashes')
    for df_hash in df_hashes:
        if df_hash in db_hashes:
            existing_ads.append(df_hash)
        if df_hash not in db_hashes:
            new_ads.append(df_hash)
    for db_hash in db_hashes:
        if db_hash not in df_hashes:
            removed_ads.append(db_hash)
    hash_categories.append(new_ads)
    hash_categories.append(existing_ads)
    hash_categories.append(removed_ads)
    logger.info(f'Result {len(new_ads)} new, {len(existing_ads)} still_listed, {len(removed_ads)} to_remove hashes ')
    return hash_categories


def extract_new_msg_data(df, new_msg_hashes: list) -> dict:
    """ Extract data from df and return as dict hash: (list column data for hash row)"""
    data_dict = {}
    for hash_str in new_msg_hashes:
        for index, row in df.iterrows():
            url = row['URL']
            url_hash = extract_hash(url)
            row_data = []
            row_data.append(row['Room_count'])
            apt_and_house_floor = row['Floor']  # apt floor and housefloor: 3/4
            floor_list = apt_and_house_floor.split("/", 1)
            row_data.append(floor_list[1])
            row_data.append(floor_list[0])
            row_data.append(row['Price_in_eur'])
            row_data.append(row['Size_sqm'])
            row_data.append(row['SQ_meter_price'])
            row_data.append(row['Street'])
            pub_date = row['Pub_date']
            rotated_pub_date = rotate_date(pub_date)
            row_data.append(rotated_pub_date)
            days_count = get_days_listed_count(pub_date)
            row_data.append(days_count)
            if url_hash == hash_str:
                data_dict[url_hash] = row_data
    return data_dict


def get_days_listed_count(pub_date: str) -> int:
    """Caclulates messge days listed count based on todays date and pub_date"""
    today = datetime.now()
    listed = gen_listed_day_obj(pub_date)
    delta = str(today - listed)
    days_num = delta.split('days')[0]
    if len(days_num) > 5:  # should catch case when delta is less that 1 day 
        return 0
    if len(days_num) < 5:  # assuming that listed day count will not exceed 999 days 
        return  int(days_num)


def rotate_date(date: str) -> str:
    """In 01.07.2021 -> out 2021.07.01"""
    yyyy = date[6:10]
    mm = date[3:5]
    dd = date[0:2]
    return yyyy + "." + mm + "."+ dd


def gen_listed_day_obj(date: str):
    """converts date in string format to datetime object"""
    yyyy = int(date[6:10])
    mm = int(date[3:5])
    dd = int(date[0:2])
    return datetime(yyyy, mm, dd)


def gen_removed_date() -> str:
    today = str(datetime.now())
    return today.split()[0].replace("-",".")


def insert_data_to_listed_table(data: dict) -> None:
    """ insert data to database table """
    conn = None
    try:
        logger.info(f'Inserting {len(data)} messages to listed_ads table')
        params = config()
        conn = psycopg2.connect(**params)
        cur = conn.cursor()
        for k, v in data.items():
            url_hash = k
            room_count = v[0]
            house_floors = v[1]
            apt_floor = v[2]
            price = v[3]
            sqm = v[4]
            sqm_price = v[5]
            apt_address = v[6]
            list_date = v[7]
            days_listed = v[8]
            cur.execute(""" INSERT INTO listed_ads
                  (url_hash,
                  room_count,
                  house_floors,
                  apt_floor,
                  price,
                  sqm,
                  sqm_price,
                  apt_address,
                  list_date,
                  days_listed)
                  VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) """,
                  (url_hash,
                  room_count,
                  house_floors,
                  apt_floor,
                  price,
                  sqm,
                  sqm_price,
                  apt_address,
                  list_date,
                  days_listed))
        conn.commit()
        cur.close()
    except (Exception, psycopg2.DatabaseError) as error:
        print(error)
    finally:
        if conn is not None:
            conn.close()


def extract_to_remove_msg_data(delisted_hashes: list) -> dict:
    """Filters data base table by delisted hashes column and
        returns dict hash:[delisted message elements] for using
        in to insert to removed_ads table"""
    delisted_mesages = {}
    conn = None
    try:
        params = config()
        conn = psycopg2.connect(**params)
        cur = conn.cursor()
        cur.execute("SELECT * FROM listed_ads")
        table_row_count = cur.rowcount
        table_rows = cur.fetchall()
        for delisted_hash in delisted_hashes:
            for i in range(table_row_count):
                curr_row_hash = table_rows[i][0]
                if delisted_hash == curr_row_hash:
                    room_count = table_rows[i][1]
                    house_floor_count = table_rows[i][2]
                    apt_floor = table_rows[i][3]
                    price = table_rows[i][4]
                    sqm = table_rows[i][5]
                    sqm_price = table_rows[i][6]
                    apt_address = table_rows[i][7]
                    list_date = table_rows[i][8]
                    removed_date = gen_removed_date()
                    days_listed = table_rows[i][9]
                    data_values = []
                    data_values.append(room_count)
                    data_values.append(house_floor_count)
                    data_values.append(apt_floor)
                    data_values.append(price)
                    data_values.append(sqm)
                    data_values.append(sqm_price)
                    data_values.append(apt_address)
                    data_values.append(list_date)
                    data_values.append(removed_date)
                    data_values.append(days_listed)
                    delisted_mesages[curr_row_hash] = data_values
        cur.close()
    except (Exception, psycopg2.DatabaseError) as error:
        print(error)
    finally:
        if conn is not None:
            conn.close()
    return delisted_mesages


def extract_to_increment_msg_data(listed_url_hashes:list) -> list:
    """Connects to db listed_ads table and iterates over table based on hashe
    list (listed_url_hashes) and extracts data in list of dicts format.

    Args:
        listed_url_hashes: string list of hashes

    Returns:
        list: example data returned [{'gjhdx': ['2021.04.20', 108], 'cecek': ['2021.04.17', 101]}]
    """
    conn = None
    increment_msg_data = {}
    msg_data = []
    try:
        params = config()
        conn = psycopg2.connect(**params)
        cur = conn.cursor()
        cur.execute("SELECT * FROM listed_ads")
        table_row_count = cur.rowcount
        table_rows = cur.fetchall()
        for luh in listed_url_hashes:
            for i in range(table_row_count):
                curr_row_hash = table_rows[i][0]
                if luh == curr_row_hash:
                    pub_date = table_rows[i][8]
                    dlv = table_rows[i][9]
                    data_values = []
                    data_values.append(pub_date)
                    data_values.append(dlv)
                    increment_msg_data[curr_row_hash] = data_values
                    msg_data.append(increment_msg_data)
        cur.close()
    except (Exception, psycopg2.DatabaseError) as error:
        print(error)
    finally:
        if conn is not None:
            conn.close()
    logger.error(f'Extracted data from listed_ads table for increment days listed value for {len(msg_data)} messages')
    return msg_data


def insert_data_to_removed_table(data: dict) -> None:
    """function takes as input to_remove_msg_data dict and inserts
    to database removed_ads table """
    conn = None
    try:
        logger.info(f'Inserting {len(data)} messages to removed_ads table')
        params = config()
        conn = psycopg2.connect(**params)
        cur = conn.cursor()
        for key, value in data.items():
            url_hash = key
            room_count = value[0]
            house_floors = value[1]
            apt_floor = value[2]
            price = value[3]
            sqm = value[4]
            sqm_price = value[5]
            apt_address = value[6]
            listed_date = value[7]
            removed_date = value[8]
            days_listed = value[9]
            cur.execute(""" INSERT INTO removed_ads
                  (url_hash,
                  room_count,
                  house_floors,
                  apt_floor,
                  price,
                  sqm,
                  sqm_price,
                  apt_address,
                  listed_date,
                  removed_date,
                  days_listed)
                  VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) """,
                 (url_hash,
                  room_count,
                  house_floors,
                  apt_floor,
                  price,
                  sqm,
                  sqm_price,
                  apt_address,
                  listed_date,
                  removed_date,
                  days_listed))
        conn.commit()
        cur.close()
    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(error)
        print(error)
    finally:
        if conn is not None:
            conn.close()


def delete_db_listed_table_rows(delisted_hashes: list) -> None:
    """Deletes rows from listed_ads table based on removed ads hashes"""
    conn = None
    try:
        logger.info(f'Deleting {len(delisted_hashes)} removed messages from listed_ads table')
        params = config()
        conn = psycopg2.connect(**params)
        cur = conn.cursor()
        cur.execute("SELECT * FROM listed_ads")
        for delisted_hash in delisted_hashes:
            del_row = "DELETE FROM listed_ads WHERE url_hash = "
            full_cmd = del_row + "'" + delisted_hash + "'"
            cur.execute(full_cmd)
        conn.commit()
        cur.close()
    except (Exception, psycopg2.DatabaseError) as error:
        print(error)
    finally:
        if conn is not None:
            conn.close()


def update_dlv_in_db_table(data: list, todays_date: datetime) -> None:
    """Iterate over list of dicts and calculate correct dlv (days_listed value)
    and check if dlv is correct in context of todays_date. If dlv in dict is not
    correct call function update_single_column_value in listed_ads db table""" 
    dlv_count = 0
    for row in data:
        for key, value in row.items():
            pub_date, days_listed = value[0], value[1]
            print(pub_date)
            pub_date = gen_listed_day_obj_new(pub_date)
            print(pub_date)
            correct_dlv = calc_valid_dlv(pub_date, todays_date)
            print("FROM DB table: pub_date, dlv Correct: dlv")
            print("------------->", value[0], str(value[1]), "----->", correct_dlv)
            if int(correct_dlv) >  days_listed:
                print(f'CONDITION: {correct_dlv} != {days_listed} -> Action update DB')
                update_single_column_value("listed_ads", correct_dlv, key, days_listed)
                print("-------------")
                dlv_count += 1
            if int(correct_dlv) == days_listed:
                print(f'CONDITION: {correct_dlv} = {days_listed} -> Do nothing')
                print("-------------")
    logger.info(f'Updated days_listed value for {dlv_count} messages in listed_ads table')


def list_rows_in_listed_table() -> None:
    """ iterate over all records in listed_ads table and print them"""
    conn = None
    try:
        params = config()
        conn = psycopg2.connect(**params)
        cur = conn.cursor()
        cur.execute("SELECT * FROM listed_ads WHERE price < 150000 ORDER BY price")
        print("The number of ads in listed_ads table: ", cur.rowcount)
        row = cur.fetchone()
        while row is not None:
            print(row)
            row = cur.fetchone()
        cur.close()
    except (Exception, psycopg2.DatabaseError) as error:
        print(error)
    finally:
        if conn is not None:
            conn.close()


def list_rows_in_removed_table() -> None:
    """Iterates over all records in delisted_ads table and print them"""
    conn = None
    try:
        params = config()
        conn = psycopg2.connect(**params)
        cur = conn.cursor()
        cur.execute("SELECT * FROM removed_ads WHERE price < 150000 ORDER BY price")
        print("The number of ads in delisted_ads table: ", cur.rowcount)
        row = cur.fetchone()
        while row is not None:
            print(row)
            row = cur.fetchone()
        cur.close()
    except (Exception, psycopg2.DatabaseError) as error:
        print(error)
    finally:
        if conn is not None:
            conn.close()


db_worker_main()



