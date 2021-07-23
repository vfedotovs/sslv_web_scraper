#!/usr/bin/env python3

"""
db_worker module is used to connect with postgres database and store data in
2 tables listed_ads and removed_ads for tracking currently listed ads,
tracking how many days they stay in listed state, move ads to delisted_ads
table after ads are removed from website and reporting capability.

Todo functionality:
    1.[x] Load daily csv data to data frame
    2.[x] Extract ad hashes from data frame
    3.[x] Extract ad hashes from database listed_ads table
    4.[x] Categorize hases in 3 categories
        - new hashes (for insert to listed_ads table)
        - seen hashes but not delisted yet (increment listed days value)
        - delisted hashes (for insert to removed_ads and remove from
        listed_ads table)
    5.[x] Extract data as dictionary from data frame
    6.[x] Extract data as dictionary from listed_ads table
    7.[x] Insert dictionary to listed_ads table
    8.[x] Insert dictionary to removed_ads table
    9.[ ] Increment listed days value in listed_ads table
    10.[x] Remove ads inserted in removed_ads table from listed_ads table
    11.[ ] Monthly activity (new ads inserted count, removed ads count,
    average days of listed state for removed ads)
"""
import sys
import logging
from logging.handlers import RotatingFileHandler
import pandas as pd
import psycopg2
from config import config

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
    try:
        file = open('cleaned-sorted-df.csv', 'r')
    except IOError:
        logger.error('There was an error opening the file cleaned-sorted-df.csv or file does not exist!')
        sys.exit()
    try:
        file = open('database.ini', 'r')
    except IOError:
        logger.error('There was an error opening the file database.ini or file does not exist!')
    df_hashes = get_data_frame_hashes('cleaned-sorted-df.csv')
    tuple_listed_hashes = get_hashes_from_table()
    string_listed_hashes = clean_db_hashes(tuple_listed_hashes)
    categorized_hashes = categorize_hashes('cleaned-sorted-df.csv')
    new_hashes = categorized_hashes[0]
    existing_hashes = categorized_hashes[1]
    removed_hashes = categorized_hashes[2]
    logger.info(f'Current state new: {len(new_hashes)}, existing: {len(existing_hashes)}, removed: {len(removed_hashes)} hashes')
    logger.info("Extracting data in dict fromat from pandas data frame")
    # data_for_db_inserts is list of 2 dicts:
    #   - first dict is for inserts to listed_ads table
    #   - second dict is for inserts to removed_ads table
    data_for_db_inserts = prepare_data(categorized_hashes,'cleaned-sorted-df.csv')
    new_data = data_for_db_inserts[0]
    # print(new_data)
    logger.info("Extracting data as dict from listed_ads database table based on removed_hashes")
    removed_data = data_for_db_inserts[1]
    # print(removed_data)
    # list_data_in_table()
    insert_data_to_db(new_data)
    # list_data_in_table()
    # list_data_in_rm_table()
    insert_data_to_removed(removed_data)
    # list_data_in_rm_table()
    # list_data_in_table()
    delete_db_table_rows(removed_hashes)
    # list_data_in_table()
    logger.info(' --- Finished db_worker module ---')


def get_data_frame_hashes(df_filename: str) -> list:
    """Read csv to pandas data frame and return URL uniq hashes as list"""
    df_hashes = []
    df = pd.read_csv(df_filename)
    logger.info(f'Loaded {df_filename} file to pandas data frame in memory')
    urls = df['URL'].tolist()
    for url in urls:
        url_hash = extract_hash(url)
        df_hashes.append(url_hash)
    logger.info(f'Extracted {len(df_hashes)} hashes from pandas data frame')
    return df_hashes


def extract_hash(full_url: str) -> str:
    """Exctracts 5 caracter hash from URL link and returns hash"""
    chunks = full_url.split("/", 9)
    last_chunk = chunks[9]
    split_chunk = last_chunk.split(".")
    url_hash = split_chunk[0]
    return url_hash


def get_hashes_from_table() -> None:
    """Iterate over all records listed_ads table and return list of hashes"""
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
    return listed_db_hashes


def clean_db_hashes(hash_list: list) -> list:
    """Removes unnecesary characters from hashe list and returns only
    string list with clean hashes"""
    clean_hashes = []
    for element in hash_list:
        str_element =  ''.join(element)
        clean_element = str_element.replace("'", "").replace(")", "")
        clean_hash = clean_element.replace("(", "").replace(",", "")
        clean_hashes.append(clean_hash)
    logger.info(f'Extracted {len(clean_hashes)} hashes from database listed_ads table')
    return clean_hashes


def categorize_hashes(df_file_name: str) -> list:
    """Loads df to memory extracts hashes and iterates over listed_ads table
    extracts hashed and capegorizes to 3 categories:
    1. new_hashes = grouped_hashes[0]
    2. existing_hashes = grouped_hashes[1]
    3. removed_hashes = grouped_hashes[2]
    """
    logger.info('Categorizing hashes based on listed_ads table hashes and new df hashes')
    df_hashes = get_data_frame_hashes(df_file_name)
    tuple_listed_hashes = get_hashes_from_table()
    string_listed_hashes = clean_db_hashes(tuple_listed_hashes)
    grouped_hashes = compare_df_to_db(df_hashes, string_listed_hashes)
    return grouped_hashes


def compare_df_to_db(df_hashes: list, db_hashes: list) -> list:
    """Compare to string lists and return list of lists with hashes all_ads
    new_ads = in df not in db -> new mesges -> for insert in db listed_ads
    existing_ads = in df and in db -> to update day count in listed_ads table
    removed_ads = not df in db
        -> delete record from db listed table
        -> inserd record to delisted table
    """
    all_ads = []
    new_ads = []
    existing_ads = []
    removed_ads = []
    for df_hash in df_hashes:
        if df_hash in db_hashes:
            existing_ads.append(df_hash)
        if df_hash not in db_hashes:
            new_ads.append(df_hash)
    for db_hash in db_hashes:
        if db_hash not in df_hashes:
            removed_ads.append(db_hash)
    all_ads.append(new_ads)
    all_ads.append(existing_ads)
    all_ads.append(removed_ads)
    return all_ads


def filter_df_by_hash(df_filename: str, hashes: list) -> dict:
    """ Extract data from df and return as dict hash: (list column data for hash row)"""
    df = pd.read_csv(df_filename)
    data_dict = {}
    for hash_str in hashes:
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
            row_data.append(row['Pub_date'])
            if url_hash == hash_str:
                data_dict[url_hash] = row_data
    return data_dict


def prepare_data(categorized_hashes: list, df_file_name: str) -> list:
    """Funtion takes as input list of lists categorized_hashes
    and returns df hash:data dict, removed_ads hash:data dict)
    function returns list of 2 dicts"""
    data_for_db_inserts = []
    new_hashes = categorized_hashes[0]
    removed_hashes = categorized_hashes[2]
    df_data = filter_df_by_hash(df_file_name, new_hashes)
    removed_data = get_delisted_data(removed_hashes)
    data_for_db_inserts.append(df_data)
    data_for_db_inserts.append(removed_data)
    logger.info('Prepared dict for new listed_ads and dict for removed_ads table')
    return data_for_db_inserts


def get_delisted_data(delisted_hashes: list) -> dict:
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
                    removed_date = '31.05.2021' # FIXME placeholder for now
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
                    delisted_mesages[curr_row_hash] = data_values
        cur.close()
    except (Exception, psycopg2.DatabaseError) as error:
        print(error)
    finally:
        if conn is not None:
            conn.close()
    return delisted_mesages


def list_data_in_table() -> None:
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

def insert_data_to_db(data: dict) -> None:
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
            cur.execute(""" INSERT INTO listed_ads
                  (url_hash,
                  room_count,
                  house_floors,
                  apt_floor,
                  price,
                  sqm,
                  sqm_price,
                  apt_address,
                  list_date)
                  VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) """,
                 (url_hash,
                  room_count,
                  house_floors,
                  apt_floor,
                  price,
                  sqm,
                  sqm_price,
                  apt_address,
                  list_date))
        conn.commit()
        cur.close()
    except (Exception, psycopg2.DatabaseError) as error:
        print(error)
    finally:
        if conn is not None:
            conn.close()


def insert_data_to_removed(data: dict) -> None:
    """ insert data to database removed_ads table """
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
            list_date = value[7]
            cur.execute(""" INSERT INTO removed_ads
                  (url_hash,
                  room_count,
                  house_floors,
                  apt_floor,
                  price,
                  sqm,
                  sqm_price,
                  apt_address)
                  VALUES (%s, %s, %s, %s, %s, %s, %s, %s) """,
                 (url_hash,
                  room_count,
                  house_floors,
                  apt_floor,
                  price,
                  sqm,
                  sqm_price,
                  apt_address))
        conn.commit()
        cur.close()
    except (Exception, psycopg2.DatabaseError) as error:
        print(error)
    finally:
        if conn is not None:
            conn.close()


def create_db_table() -> None:
    """Creates listed_ads table in the PostgreSQL database"""
    command = (""" CREATE TABLE listed_ads
                   (url_hash TEXT,
                    room_count INTEGER,
                    house_floors INTEGER,
                    apt_floor INTEGER,
                    price INTEGER,
                    sqm INTEGER,
                    sqm_price INTEGER,
                    apt_address TEXT,
                    list_date TEXT )""")
    conn = None
    try:
        params = config()                 # read the connection parameters
        conn = psycopg2.connect(**params) # connect to the PostgreSQL server
        cur = conn.cursor()
        cur.execute(command)               # execute data base command statements
        print("listed_ads TABLE was created with success ")
        cur.close()                        # close communication with the PostgreSQL database server
        conn.commit()                      # commit the changes
    except (Exception, psycopg2.DatabaseError) as error:
        print(error)
    finally:
        if conn is not None:
            conn.close()


def list_data_in_rm_table() -> None:
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


def delete_db_table_rows(delisted_hashes: list) -> None:
    """Deletes rows from listed_ads table based on removed ads hashes"""
    conn = None
    try:
        logger.info(f'Deleting {len(delisted_hashes)} removed messages from listed_ads table')
        params = config()
        conn = psycopg2.connect(**params)
        cur = conn.cursor()
        cur.execute("SELECT * FROM listed_ads")
        for delisted_hash in delisted_hashes:
            print(delisted_hash)
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


db_worker_main()
