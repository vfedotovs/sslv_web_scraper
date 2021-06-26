#!/usr/bin/env python3

"""
db_worker module is used to connect with postgres database and store data in
2 tables listed_ads and delisted_ads for tracking currently listed ads,
tracking how many days they stay in listed state, move ads to delisted_ads
table after ads are removed from website and reporting capability.

Todo functionality:
    1.[] Load daily csv data to data frame
    2.[] Extract ad hashes from data frame
    3.[] Extract ad hashes from database listed_ads table
    4.[] Categorize hases in 3 categories
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
    pass


db_worker_main()
