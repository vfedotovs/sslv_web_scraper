#!/usr/bin/env python3

import psycopg2
from config import config


def drop_two_tables() -> None:
    """ create table in the PostgreSQL database"""
    print("Attempting to delete tables removed_ads and listed_ads ...")
    command = (""" DROP TABLE removed_ads""");
    command2 = (""" DROP TABLE listed_ads""");

    conn = None
    try:
        params = config()                 # read the connection parameters
        conn = psycopg2.connect(**params) # connect to the PostgreSQL server
        cur = conn.cursor()
        cur.execute(command)               # execute data base command statements
        cur.execute(command2)               # execute data base command statements
        print("2 TABLES where dropped with success ... ")
        cur.close()                        # close communication with the PostgreSQL database server
        conn.commit()                      # commit the changes
    except (Exception, psycopg2.DatabaseError) as error:
        print(error)
    finally:
        if conn is not None:
            conn.close()


def create_db_listed_table() -> None:
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
                    list_date TEXT )""");
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


def create_removed_db_table() -> None:
    """ create table in the PostgreSQL database"""
    command = (""" CREATE TABLE removed_ads
                  (url_hash TEXT,
                   room_count INTEGER,
                   house_floors INTEGER,
                   apt_floor INTEGER,
                   price INTEGER,
                   sqm INTEGER,
                   sqm_price INTEGER,
                   apt_address TEXT,
                   removed_date TEXT,
                   days_listed INTEGER)""");
    conn = None
    try:
        params = config()                 # read the connection parameters
        conn = psycopg2.connect(**params) # connect to the PostgreSQL server
        cur = conn.cursor()
        cur.execute(command)               # execute data base command statements
        print("removed_ads TABLE was created with success ... ")
        cur.close()                        # close communication with the PostgreSQL database server
        conn.commit()                      # commit the changes
    except (Exception, psycopg2.DatabaseError) as error:
        print(error)
    finally:
        if conn is not None:
            conn.close()


drop_two_tables()
create_db_listed_table()
create_removed_db_table()

