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
6.[x] extract to_removed_msg_data from db listed_ads table
      - based on to_remove_hashes
7.[x] Insert new_msg_data to listed_ads table
8.[x] Insert to_remove_msg_data to removed_ads table
9.[x] Delete db rows in listed table based on to_remove_msg_hashes
10.[x] Update listed table: still_listed_msg_hashed for check and update
       listed days count every run
11.[x] Check and update days listed in listed table rows based
       still_listed_msg_hashes
TODO:
12.[] Check if report day by last x days count and  generate report
13.[] Write tests for db_worker module
"""

import os
import sys
import logging
from logging import handlers
from logging.handlers import RotatingFileHandler
from datetime import datetime
import pandas as pd
import psycopg2
from app.wsmodules.config import config
from app.wsmodules.scrape_runs import record_counts
# from config import config  # for manual test runs FIXME


logger = logging.getLogger("db_worker")
logger.setLevel(logging.INFO)
log_format = logging.Formatter(
    "%(asctime)s [%(levelname)-5.5s]: %(funcName)s: %(lineno)d: %(message)s"
)
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(log_format)
logger.addHandler(ch)
fh = handlers.RotatingFileHandler("dbworker.log", maxBytes=(1048576 * 5), backupCount=7)
fh.setFormatter(log_format)
logger.addHandler(fh)


def db_worker_main() -> None:
    """db_worker.py module main function"""
    logger.info(" --- Satrting db_worker module ---")

    required_config_files = ["database.ini"]
    required_data_files = ["cleaned-sorted-df.csv"]
    check_config_files(required_config_files)
    check_data_files(required_data_files)

    # Ensure tables exist (fixes missing table on fresh DB volumes without backup restore)
    ensure_tables_exist()

    df = load_csv_to_df("cleaned-sorted-df.csv")

    # M7 P1: today's URL universe comes from the scraper's discovered-urls
    # file (ALL urls seen on the list pages); the data frame now contains
    # only newly fetched ads. Falls back to deriving the set from the df
    # when the file is absent/stale (cloud-file path, legacy runs).
    discovered_hashes = load_todays_discovered_hashes()

    if df is None or df.empty:
        if discovered_hashes is None:
            logger.warning("DataFrame is empty. Skipping processing.")
            return  # Exit gracefully instead of crashing
        logger.info(
            "No new ads in todays data frame; continuing diff with %s"
            " discovered hashes (still/removed detection)",
            len(discovered_hashes),
        )

    # Extract new and still listed message url hashes
    if discovered_hashes is not None:
        todays_url_hashes = discovered_hashes
    else:
        todays_url_hashes = extract_url_hashes_from_df(df)
    still_listed_table_url_hashes = extract_listed_url_hashes_from_db()
    # Sorting all hashes to 3 categories (new, still_listed, to_remove)
    hashe_categories = compare_df_to_db_hashes(
        todays_url_hashes, still_listed_table_url_hashes
    )
    new_msg_hashes = hashe_categories[0]
    still_listed_msg_hashes = hashe_categories[1]
    to_remove_msg_hashes = hashe_categories[2]
    # M6 monitoring Item 2: record diff counts on the current scrape run
    record_counts(
        new_ads=len(new_msg_hashes),
        still_listed_ads=len(still_listed_msg_hashes),
        removed_ads=len(to_remove_msg_hashes),
    )
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
    # Check and increment/update listed_ads all rows for listed days cnt value
    todays_date = datetime.now()
    update_dlv_in_db_table(to_increment_msg_data, todays_date)
    # M6 monitoring Item 2: record post-run table totals on the current
    # scrape run (replaces the scraped_and_removed.txt debug file)
    listed_rows, removed_rows = get_table_row_counts()
    record_counts(listed_table_rows=listed_rows, removed_table_rows=removed_rows)
    logger.info(" --- Ended db_worker module ---")


def get_table_row_counts() -> tuple:
    """Returns (listed_ads, removed_ads) table row counts via COUNT(*)."""
    conn = None
    try:
        params = config()
        conn = psycopg2.connect(**params)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM listed_ads")
        listed_rows = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM removed_ads")
        removed_rows = cur.fetchone()[0]
        cur.close()
        logger.info(f"LA TBL rows: {listed_rows} RA TBL rows: {removed_rows}")
        return listed_rows, removed_rows
    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(f"Failed to count table rows: {error}")
        raise
    finally:
        if conn is not None:
            conn.close()


def check_config_files(file_names: list) -> None:
    """If config file is not found creates empty file"""
    for file_name in file_names:
        if not os.path.exists(file_name):
            logger.warning(f"File '{file_name}' not found! Creating an empty file.")
            with open(file_name, "w") as f:
                pass  # Creates an empty file


def ensure_csv_exists(csv_file_name: str, headers: list) -> None:
    """
    Ensure that a CSV file exists and contains the specified headers.

    If the file does not exist or is empty, a new CSV file is created
    with the provided column headers.

    Args:
       csv_file_name (str): The name of the CSV file to check or create.
       headers (list of str): A list of column names to include in the CSV.

    Returns:
       None
    """
    if not os.path.exists(csv_file_name) or os.stat(csv_file_name).st_size == 0:
        logger.warning(
            f"File '{csv_file_name}' is missing or empty. Creating a new one."
        )
        pd.DataFrame(columns=headers).to_csv(csv_file_name, index=False)


def check_data_files(required_files: list) -> None:
    """
    Checks if requires source data file exists
    If file is not found creates file with empty columns
    """

    for file_name in required_files:
        if not os.path.exists(file_name):
            logger.warning(f"File '{file_name}' not found! Creating an empty file.")
            ensure_csv_exists(
                "cleaned-sorted-df.csv",
                headers=[
                    "URL",
                    "Room_count",
                    "Floor",
                    "Street",
                    "Pub_date",
                    "Size_sqm",
                    "Price_in_eur",
                    "SQ_meter_price",
                ],
            )


def load_todays_discovered_hashes(file_path: str = "discovered-urls.txt"):
    """M7 P1: read today's full discovered URL set written by web_scraper.

    Returns a list of url hashes, or None when the file is missing or
    stale (mtime not from today) — callers then fall back to deriving
    today's set from the scraped data frame (legacy behavior, e.g. the
    cloud-file path which does not run the local scraper).
    """
    if not os.path.exists(file_path):
        logger.info(f"No {file_path} found — using data frame hashes (legacy mode)")
        return None
    mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
    if mtime.date() != datetime.now().date():
        logger.warning(
            f"{file_path} is stale (modified {mtime:%Y-%m-%d}) — ignoring it"
        )
        return None
    with open(file_path) as fh:
        urls = [line.strip() for line in fh if line.strip()]
    hashes = [extract_hash(url) for url in urls]
    logger.info(f"Loaded {len(hashes)} discovered url hashes from {file_path}")
    return hashes


def load_csv_to_df(csv_file_name: str):
    """reads csv file and returns pandas data frame"""
    cwd = os.getcwd()
    logger.info(f"Loading {csv_file_name} from directory {cwd}")
    df = pd.read_csv(csv_file_name)
    logger.info(f"Loaded {csv_file_name} file to pandas data frame in memory")
    return df


def extract_url_hashes_from_df(df_name) -> list:
    """exctracts from df url column links from all rows and
    from each link extracts uniq url hash"""
    url_hashes = []
    urls = df_name["URL"].tolist()
    for full_url in urls:
        url_hash = extract_hash(full_url)
        url_hashes.append(url_hash)
    logger.info(f"Extracted {len(url_hashes)} url hashes from todays scraped data")
    logger.info(f"Extracted {url_hashes} url hashes from todays scraped data")
    return url_hashes


def extract_hash(full_url: str) -> str:
    """Exctracts 5 caracter hash from URL link and returns hash"""
    chunks = full_url.split("/", 9)
    last_chunk = chunks[9]
    split_chunk = last_chunk.split(".")
    url_hash = split_chunk[0]
    return url_hash


def extract_listed_url_hashes_from_db() -> list:
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
        logger.error(f"Failed to extract url hashes from listed_ads table: {error}")
        raise
    finally:
        if conn is not None:
            conn.close()
    clean_hashes = []
    for element in listed_db_hashes:
        str_element = "".join(element)
        clean_element = str_element.replace("'", "").replace(")", "")
        clean_hash = clean_element.replace("(", "").replace(",", "")
        clean_hashes.append(clean_hash)
    logger.info(f"Extracted {len(clean_hashes)} hashes from database listed_ads table")
    logger.info(f"Extracted clean hash count: {len(clean_hashes)}")
    logger.info(f"Extracted clean hash list: {clean_hashes}")
    return clean_hashes


def compare_df_to_db_hashes(df_hashes: list, db_hashes: list) -> list:
    """This should allow to conclude if hash is new, still seen, to_remove"""
    logger.info(
        f"Comparing {len(df_hashes)} todays scraped data hashes "
        f"with {len(db_hashes)} DB listed_ads table hashes"
    )
    # M7 P5: membership checks against sets (O(1)) instead of lists (O(N)),
    # keeping input order in the returned lists.
    df_hash_set = set(df_hashes)
    db_hash_set = set(db_hashes)
    new_ads = [h for h in df_hashes if h not in db_hash_set]
    existing_ads = [h for h in df_hashes if h in db_hash_set]
    removed_ads = [h for h in db_hashes if h not in df_hash_set]
    hash_categories = [new_ads, existing_ads, removed_ads]
    logger.info(
        f"Result {len(new_ads)} new, {len(existing_ads)} still_listed, "
        f"{len(removed_ads)} to_remove hashes "
    )
    logger.debug(f"New todays scraped hashes: {new_ads}")
    logger.debug(f"Hashes from DB listed_ads table: {existing_ads}")
    logger.debug(f"Hashes for DB removed_ads table: {removed_ads}")
    return hash_categories


def extract_new_msg_data(df, new_msg_hashes: list) -> dict:
    """Extract data from df and return as dict hash:
    (list column data for hash row)"""
    data_dict = {}
    logger.info(f"new_msg_hashes count {len(new_msg_hashes)}")
    logger.debug(f"new_msg_hashes: {new_msg_hashes}")
    logger.info("Starting extract new ads from todays scraped data farme in memory")
    # M7 P5: single pass over the data frame with a hash set lookup instead
    # of re-iterating the whole frame for every new hash (O(new × N)).
    new_hash_set = set(new_msg_hashes)
    for index, row in df.iterrows():
        url_hash = extract_hash(row["URL"])
        if url_hash not in new_hash_set:
            continue
        row_data = []
        row_data.append(row["Room_count"])
        apt_and_house_floor = row["Floor"]  # apt floor and housefloor: 3/4
        floor_list = apt_and_house_floor.split("/", 1)
        row_data.append(floor_list[1])
        row_data.append(floor_list[0])
        row_data.append(row["Price_in_eur"])
        row_data.append(row["Size_sqm"])
        row_data.append(row["SQ_meter_price"])
        row_data.append(row["Street"])
        pub_date = row["Pub_date"]
        rotated_pub_date = rotate_date(pub_date)
        row_data.append(rotated_pub_date)
        days_count = get_days_listed_count(pub_date)
        row_data.append(days_count)
        data_dict[url_hash] = row_data
    logger.info(f"Extrcted new ad count from todays data frame {len(data_dict)} ")
    for k, v in data_dict.items():
        logger.debug(f"{k} {v}")
    return data_dict


def get_days_listed_count(pub_date: str) -> int:
    """Caclulates messge days listed count based on todays date and pub_date"""
    today = datetime.now()
    listed = gen_listed_day_obj(pub_date)
    delta = str(today - listed)
    days_num = delta.split("days")[0]
    if len(days_num) > 5:  # should catch case when delta is less that 1 day
        return 0
    if len(days_num) < 5:  # assuming that listed day count will not exceed 999 days
        return int(days_num)


def rotate_date(date: str) -> str:
    """In 01.07.2021 -> out 2021.07.01"""
    yyyy = date[6:10]
    mm = date[3:5]
    dd = date[0:2]
    return yyyy + "." + mm + "." + dd


def gen_listed_day_obj(date: str):
    """converts date in string format to datetime object"""
    yyyy = int(date[6:10])
    mm = int(date[3:5])
    dd = int(date[0:2])
    return datetime(yyyy, mm, dd)


def gen_removed_date() -> str:
    """generates removed data value based on todays date
    example: 2021.07.25"""
    today = str(datetime.now())
    return today.split()[0].replace("-", ".")


def insert_data_to_listed_table(data: dict) -> None:
    """insert data to database table"""
    conn = None
    try:
        logger.info(f"Inserting {len(data)} messages to listed_ads table")
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
            cur.execute(
                """ INSERT INTO listed_ads
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
                (
                    url_hash,
                    room_count,
                    house_floors,
                    apt_floor,
                    price,
                    sqm,
                    sqm_price,
                    apt_address,
                    list_date,
                    days_listed,
                ),
            )
        conn.commit()
        cur.close()
        for k, v in data.items():
            logger.info(f"{k} {v}")
    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(f"DB operation failed: {error}")
        raise
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
        table_rows = cur.fetchall()
        # M7 P5: single pass over table rows with a set lookup instead of
        # nested O(hashes × rows) matching loops.
        delisted_hash_set = set(delisted_hashes)
        for table_row in table_rows:
            curr_row_hash = table_row[0]
            if curr_row_hash not in delisted_hash_set:
                continue
            room_count = table_row[1]
            house_floor_count = table_row[2]
            apt_floor = table_row[3]
            price = table_row[4]
            sqm = table_row[5]
            sqm_price = table_row[6]
            apt_address = table_row[7]
            list_date = table_row[8]
            removed_date = gen_removed_date()
            days_listed = table_row[9]
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
        logger.error(f"DB operation failed: {error}")
        raise
    finally:
        if conn is not None:
            conn.close()
    return delisted_mesages


def extract_to_increment_msg_data(listed_url_hashes: list) -> list:
    """Connects to db listed_ads table and iterates over table based on hashe
    list (listed_url_hashes) and extracts data in list of dicts format.

    Args:
        listed_url_hashes: string list of hashes

    Returns:
        list: example data returned [{'gjhdx': ['2021.04.20', 108], 'cecek': ['2021.04.17', 101]}]
    """
    conn = None
    to_increment_msg_data = {}
    try:
        logger.info(f"Connecting to DB to fetch data from listed_ads table")
        params = config()
        conn = psycopg2.connect(**params)
        cur = conn.cursor()
        cur.execute("SELECT * FROM listed_ads")
        table_rows = cur.fetchall()  # list of rows as tuple Datastructure
        # need to handle case when table is empty - row count = 0 aka first run
        if len(table_rows) < 1:
            return None
        if len(listed_url_hashes) < 1:
            return None
        # M7 P5: single pass over table rows with a set lookup instead of
        # nested O(hashes × rows) matching loops.
        listed_hash_set = set(listed_url_hashes)
        for table_row in table_rows:
            curr_row_hash = table_row[0]
            if curr_row_hash not in listed_hash_set:
                continue
            pub_date = table_row[8]
            dlv = table_row[9]
            data_values = []
            data_values.append(pub_date)
            data_values.append(dlv)
            to_increment_msg_data[curr_row_hash] = data_values
        cur.close()
        logger.info(
            f"Extracted data from listed_ads table for {len(to_increment_msg_data)} messages"
        )
        for k, v in to_increment_msg_data.items():
            logger.debug(f"{k} {v}")
    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(f"DB operation failed: {error}")
        raise
    finally:
        if conn is not None:
            conn.close()
    return to_increment_msg_data


def insert_data_to_removed_table(data: dict) -> None:
    """function takes as input to_remove_msg_data dict and inserts
    to database removed_ads table"""
    conn = None
    try:
        logger.info(f"Inserting {len(data)} messages to removed_ads table")
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
            cur.execute(
                """ INSERT INTO removed_ads
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
                (
                    url_hash,
                    room_count,
                    house_floors,
                    apt_floor,
                    price,
                    sqm,
                    sqm_price,
                    apt_address,
                    listed_date,
                    removed_date,
                    days_listed,
                ),
            )
        conn.commit()
        cur.close()
        for k, v in data.items():
            logger.info(f"{k} {v}")
    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(f"Failed to insert data to removed_ads table: {error}")
        raise
    finally:
        if conn is not None:
            conn.close()


def delete_db_listed_table_rows(delisted_hashes: list) -> None:
    """Deletes rows from listed_ads table based on removed ads hashes"""
    conn = None
    try:
        logger.info(
            f"Deleting {len(delisted_hashes)} removed messages from listed_ads table"
        )
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
        logger.info(f"Deleted ads with hashes: {delisted_hashes} from listed_ads table")
    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(f"DB operation failed: {error}")
        raise
    finally:
        if conn is not None:
            conn.close()


def update_dlv_in_db_table(data: dict, todays_date: datetime) -> None:
    """Validates if dlv(days_listed value) is not correct then updates

    Iterate over list of dicts and calculate correct dlv
    and check if dlv is correct in context of todays_date.
    If dlv in dict is not correct call function
    update_single_column_value in listed_ads db table"""
    # TODO: refactor data needs better name like ad_hash_data_attrs
    # function docstring needs to be better
    # no need to pass todays_date can be initialized here
    dlv_count = 0
    if data is not None:
        for ad_hash, ad_data in data.items():
            pub_date, days_listed = ad_data[0], ad_data[1]
            correct_dlv = calc_valid_dlv(pub_date, todays_date)
            if correct_dlv > days_listed:
                update_single_column_value("listed_ads", correct_dlv, ad_hash)
                dlv_count += 1
                logger.info(f"Updated dlv value for {ad_hash} {ad_data} item")
            if correct_dlv == days_listed:
                pass
    logger.info(f"Updated days_listed value for {dlv_count} ads in listed_ads table")

    if data is None:
        logger.error(
            "Failed to update dlv values:"
            " possibly listed_ads table is empty"
            " or DB was not imported"
        )


def calc_valid_dlv(pub_date: str, todays_date: datetime) -> int:
    """calculates days_listed value based on pub_date and
    todays_date and returns days count value"""
    listed = gen_listed_day_obj_new(pub_date)
    delta = str(todays_date - listed)
    days_count = delta.split()[0]
    if len(days_count) > 3:
        return 0
    return int(days_count)


def gen_listed_day_obj_new(date: str):
    """converts date in string 2021.03.21 > format to datetime object"""
    yyyy = int(date[0:4])
    mm = int(date[5:7])
    dd = int(date[8:10])
    return datetime(yyyy, mm, dd)


def update_single_column_value(table_name: str, dlv: int, url_hash: str) -> None:
    """connect to db and update value for listed_ads column only for
    row that matched url_hash"""
    conn = None
    try:
        params = config()
        conn = psycopg2.connect(**params)
        cur = conn.cursor()
        sql = (
            f"UPDATE {table_name} "
            f"SET days_listed = {dlv} "
            f"WHERE url_hash = '{url_hash}' ;"
        )
        cur.execute(sql)
        conn.commit()
        cur.close()
    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(f"DB operation failed: {error}")
        raise
    finally:
        if conn is not None:
            conn.close()


def list_rows_in_listed_table() -> None:
    """iterate over all records in listed_ads table and print them"""
    conn = None
    try:
        params = config()
        conn = psycopg2.connect(**params)
        cur = conn.cursor()
        cur.execute("SELECT * FROM listed_ads WHERE price < 500000 ORDER BY price")
        print("The number of ads in listed_ads table: ", cur.rowcount)
        row = cur.fetchone()
        while row is not None:
            print(row)
            row = cur.fetchone()
        cur.close()
    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(f"DB operation failed: {error}")
        raise
    finally:
        if conn is not None:
            conn.close()


def list_rows_in_removed_table() -> int:
    """Iterates over all records in delisted_ads table and print them"""
    conn = None
    # add_count = 0
    try:
        params = config()
        conn = psycopg2.connect(**params)
        cur = conn.cursor()
        cur.execute("SELECT * FROM removed_ads WHERE price < 500000 ORDER BY price")
        logger.info(f"The number of ads in delisted_ads table: {cur.rowcount}")
        # add_count = int(cur.rowcount)
        # row = cur.fetchone()
        # while row is not None:
        #     print(row)
        #     row = cur.fetchone()
        cur.close()
    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(f"DB operation failed: {error}")
        raise
    finally:
        if conn is not None:
            conn.close()
    return int(cur.rowcount)


def ensure_tables_exist() -> None:
    """Create listed_ads and removed_ads tables if they do not exist.
    This fixes the 'relation does not exist' error on fresh DB volumes
    (e.g. new multi-city deploy without prior backup restore).
    """
    conn = None
    try:
        params = config()
        conn = psycopg2.connect(**params)
        cur = conn.cursor()

        # listed_ads (active listings)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS listed_ads (
                url_hash text,
                room_count integer,
                house_floors integer,
                apt_floor integer,
                price integer,
                sqm integer,
                sqm_price integer,
                apt_address text,
                list_date text,
                days_listed integer,
                view_count integer
            )
        """)

        # removed_ads (historical)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS removed_ads (
                url_hash text,
                room_count integer,
                house_floors integer,
                apt_floor integer,
                price integer,
                sqm integer,
                sqm_price integer,
                apt_address text,
                listed_date text,
                removed_date text,
                days_listed integer,
                view_count integer
            )
        """)

        conn.commit()
        cur.close()
        logger.info("Ensured listed_ads and removed_ads tables exist (CREATE IF NOT EXISTS)")
    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(f"Error ensuring tables exist: {error}")
        raise
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    db_worker_main()
