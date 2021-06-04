#!/usr/bin/env python3
""" Module documantation line

Main module functionalities:
    1. As information input use clean_df.csv
    2. As information storage location use postgress database
    3. Read data to data frame and write to data base if database empty
    4. Daily read new info from csv file compare wit data in databse and
    update database with new information
"""
import pandas as pd
import time
import psycopg2
from config import config


def looped_main():
    """ this function is for testing porpuses only """
    data_frames = ['cleaned-sorted-df-d1.csv',
                   'cleaned-sorted-df-d2.csv',
                   'cleaned-sorted-df-d3.csv']
    looped_test(data_frames)


def db_worker_main() -> None:
    """ MVP TODO: db_worker.py module software functionality
    - function add days listed column to listed table for tracking
        how many days since added to listed_ads table
    - function insert delisted ads to delisted table
        - include days listed count : delist date
    - function increment / update data in listed table
        - days listed count + 1
    - create backup of both tables in data folder
    - Reporting weekly/mothly/3month/6M/ 1Y/ All
        database data reporting functionality """
    print("DEBUG: Satrting db_worker module ...")
    print("DEBUG: Loaded cleaned-sorted-df.csv to dataframe in memory ...")
    df_hashes = get_data_frame_hashes('cleaned-sorted-df-d1.csv')
    print("DEBUG: calculated hashes from data fame URLs ...")
    
    tuple_listed_hashes = get_hashes_from_table()
    string_listed_hashes = clean_db_hashes(tuple_listed_hashes)
    print("DEBUG: Extracted from table listed_ads URL hashes  ...")
    grouped_hashes = compare_df_to_db(df_hashes, string_listed_hashes)
    print("DEBUG: Compared hashes listed_ads table and data frame ...")
    new_hashes = grouped_hashes[0]
    still_listed_hashes = grouped_hashes[1]
    delisted_hashes = grouped_hashes[2]


    # dict {hash: [row of data from all dataframe clumns]}
    new_inserts = filter_df_by_hash('cleaned-sorted-df-d1.csv', new_hashes)
    still_listed = filter_df_by_hash('cleaned-sorted-df-d1.csv', still_listed_hashes)
    delisted_today = filter_df_by_hash('cleaned-sorted-df-d1.csv', delisted_hashes)
    print("DEBUG: Extracted dict:[list] from data frame ...")
    print("DEBUG: listing database content before inserting new data ...")
    list_data_in_table('some_table_name')
    insert_data_to_db('some_table_name', new_inserts)
    print("DEBUG: new ads dict data was in serted to table  with real sslv data frame...")
    print("DEBUG: listing database content after inserting new data ...")
    list_data_in_table('some_table_name')


def db_worker_test_tables(csv_files: list) -> None:
    """ function simulates n day (csv file count)  iterations to ensure
        to ensure that there is chance to test listed_ads and removed_ads table
        functionality:
            1. Load df frame to memory and iterate over df to extract hashes(new)
            2. Itreate over listed_ads table and extract hashes(existing)
            3. Compare new and existing hased allows to identify hashes (delisted)
                and allow to categorise hasshes [new, existing, delisted]
            4. Action data based on hashe category
                4.1 insert (new category) in listed_ads table
                4.2 increment listed_day_count value for (existing category) #TODO: implement this feature
                4.3 insert (delisted category) to removed_ads table
                4.4 delete (delisted category) from listed_ads table  #TODO: implement this feature
            """
    file_count = 1
    for csv_file in csv_files:
        print(f" -- {file_count} csv file(s) is getting processed or iteration in loop --")
        df_hashes = get_data_frame_hashes(csv_file)
        tuple_listed_hashes = get_hashes_from_table('sometable')
        string_listed_hashes = clean_db_hashes(tuple_listed_hashes)
        grouped_hashes = compare_df_to_db(df_hashes, string_listed_hashes)
        new_hashes = grouped_hashes[0]
        still_listed_hashes = grouped_hashes[1]
        delisted_hashes = grouped_hashes[2]
        print("")
        print("New hashe count or not seen in db table:", len(new_hashes))
        print("Existing hashes count in db table:", len(still_listed_hashes))
        print("Delisted hashe count:" , len(delisted_hashes))
        #Dict Data structure need to be inserted in DB listed table
        new_inserts = filter_df_by_hash(csv_file, new_hashes)
        # Inserting new data to db listed table
        #print("DEBUG: listing database content before inserting new data ...")
        #list_data_in_table('some_table_name')
        insert_data_to_db('some_table_name', new_inserts)
        #list_data_in_table('some_table_name')
        delisted_data = get_delisted_data(delisted_hashes)
        # insert_data_to_db('delisted_ads', data_for_removed_table)
        insert_data_to_removed(delisted_data)
        # TODO: implement function remove delisted data rows from listed_ads table
        file_count += 1
        print("")
        print("Sleepin 3 sec ...")
        time.sleep(3)


def get_data_frame_hashes(df_filename: str) -> list:
    """ Read csv to pandas data frame and return URL uniq hashes as list """
    df_hashes = []
    df = pd.read_csv(df_filename)
    urls = df['URL'].tolist()
    for url in urls:
        url_hash = extract_hash(url)
        df_hashes.append(url_hash)
    return df_hashes


def extract_hash(full_url: str) -> str:
    """ Exctracts 5 caracter hash from URL link and returns hash"""
    chunks = full_url.split("/", 9)
    last_chunk = chunks[9]
    split_chunk = last_chunk.split(".")
    url_hash = split_chunk[0]
    return url_hash


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


def create_db_table() -> None:
    """ create table in the PostgreSQL database"""
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



def get_delisted_data(delisted_hashes: list) -> dict:
    """ filters data base table by delisted hashes column and
        returns dict hash:[delisted message elements] for using
        in to insert delisted_ads table"""
    delisted_mesages = {}
    conn = None
    try:
        params = config()
        conn = psycopg2.connect(**params)
        cur = conn.cursor()
        cur.execute("SELECT * FROM listed_ads")
        table_row_count = cur.rowcount
        #print(f"The number of ads in listed_ads table: {table_row_count}")
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


def compare_df_to_db(df_hashes: list, db_hashes: list) ->list:
    """ Compare to string lists and return list of lists with hashes all_ads

    new_ads = in df not in db -> new mesges -> to insert in db
    existing_ads = in df and in db -> mesges exist in db
                            -> to update day count in  db for message
    removed_ads = not df in db -> delete record from db listed table
                         -> inserd record to delisted table
    """
    all_ads = []
    new_ads = []
    existing_ads = []
    removed_ads = []
    # TODO: check if df_haches len > 0
    for df_hash in df_hashes:
        if df_hash in db_hashes:
            existing_ads.append(df_hash)
        if df_hash not in db_hashes:
            new_ads.append(df_hash)
    # TODO: check if db_haches len > 0
    for db_hash in db_hashes:
        if db_hash not in df_hashes:
            removed_ads.append(db_hash)
    all_ads.append(new_ads)
    all_ads.append(existing_ads)
    all_ads.append(removed_ads)
    return all_ads


def insert_data_to_db(table_name: str, data: dict) -> None:
    """ insert data to database table """
    conn = None
    try:
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


def delete_data_from_db(new_ads: list) -> None:
    """ ads need to be removed from listed table
    after data is moved to removed_ads table"""
    #TODO: implement this function required for db_worker model MVP  
    pass


def list_data_in_table() -> None:
    """ iterate over all records in listed_ads table and print them"""
    conn = None
    try:
        params = config()
        conn = psycopg2.connect(**params)
        cur = conn.cursor()
        cur.execute("SELECT * FROM listed_ads WHERE price < 30001 ORDER BY price")
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


def get_hashes_from_table() -> None:
    """ iterate over all records listed_ads table and return list of hashes"""
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
    clean_hashes = []
    for element in hash_list:
        str_element =  ''.join(element)
        x = str_element.replace("'", "")
        y = x.replace(")", "")
        z = y.replace("(", "")
        clean_hash = z.replace(",", "")
        clean_hashes.append(clean_hash)
    return clean_hashes


if __name__ == '__main__':
    #db_worker_main()
    db_worker_test_tables()
