#!/usr/bin/env python3

"""
db_worker module is used to connect with postgres database and store data in
2 tables listed_ads and delisted_ads for tracking currently listed ads,
tracking how many days they stay in listed state, move ads to delisted_ads
table after ads are removed from website and reporting capability.

Todo functionality:
    1.[x] Load daily csv data to data frame
    2.[x] Extract ad hashes from data frame
    3.[x] Extract ad hashes from database listed_ads table
    4.[x] Categorize hases in 3 categories
        - new hashes (for insert to listed_ads table)
        - seen hashes but not delisted yet (increment listed days value)
        - delisted hashes (for insert to delisted_ads and remove from
        listed_ads table)
    5.[] Extract data as dictionary from data frame
    6.[] Extract data as dictionary from listed_ads table
    7.[] Insert dictionary to listed_ads table
    8.[] Insert dictionary to delisted_ads table
    9.[] Increment listed days value in listed_ads table
    10.[] Remove delisted ads from listed_ads
    11.[] Monthly activity (new ads inserted count, removed ads count,
    average days of listed state for removed ads)
"""
import pandas as pd
import psycopg2
from config import config


def db_worker_main() -> None:
    """db_worker.py module main finction"""
    print("DEBUG: Satrting db_worker module ...")
    print("DEBUG: Loaded cleaned-sorted-df.csv to dataframe in memory ...")
    df_hashes = get_data_frame_hashes('cleaned-sorted-df.csv')
    print("DEBUG: calculated hashes from data fame URLs ...")
    tuple_listed_hashes = get_hashes_from_table()
    string_listed_hashes = clean_db_hashes(tuple_listed_hashes)
    print("DEBUG: Extracted from table listed_ads URL hashes  ...")
    print("Stage1: Get and categorize hashes to (new, existing, removed) categories")
    categorized_hashes = categorize_hashes('cleaned-sorted-df.csv')
    new_hashes = categorized_hashes[0]
    existing_hashes = categorized_hashes[1]
    removed_hashes = categorized_hashes[2]
    print("New hashe count or not seen in listed_ads table:", len(new_hashes))
    print("Existing hashe count in db listed_ads table:", len(existing_hashes))
    print("Delisted hashe count based on categorization:" , len(removed_hashes))


def get_data_frame_hashes(df_filename: str) -> list:
    """Read csv to pandas data frame and return URL uniq hashes as list"""
    df_hashes = []
    df = pd.read_csv(df_filename)
    urls = df['URL'].tolist()
    for url in urls:
        url_hash = extract_hash(url)
        df_hashes.append(url_hash)
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
    return clean_hashes


def categorize_hashes(df_file_name: str) -> list:
    """Loads df to memory extracts hashes and iterates over listed_ads table
    extracts hashed and capegorizes to 3 categories:
    1. new_hashes = grouped_hashes[0]
    2. existing_hashes = grouped_hashes[1]
    3. removed_hashes = grouped_hashes[2]
    """
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


db_worker_main()
