#!/bin/bash



# describe table detailed info
psql -h localhost -U docker -d docker -c '\dt+'


# create empty tables
psql -h localhost -U docker -d docker -c 'CREATE TABLE listed_ads(
    url_hash TEXT,
    room_count INTEGER,
    house_floors INTEGER,
    apt_floor INTEGER,
    price INTEGER,
    sqm INTEGER,
    sqm_price INTEGER,
    apt_address TEXT,
    list_date TEXT,
    days_listed INTEGER,
    view_count INTEGER
);'


psql -h localhost -U docker -d docker -c 'CREATE TABLE removed_ads(
    url_hash TEXT,
    room_count INTEGER,
    house_floors INTEGER,
    apt_floor INTEGER,
    price INTEGER,
    sqm INTEGER,
    sqm_price INTEGER,
    apt_address TEXT,
    listed_date TEXT,
    removed_date TEXT,
    days_listed INTEGER,
    view_count INTEGER
);'

psql -h localhost -U docker -d docker -c '\dt+'
psql -h localhost -U docker -d docker -c 'SELECT * FROM listed_ads;'
psql -h localhost -U docker -d docker -c 'SELECT * FROM removed_ads;'


# TODO: restore backup from sql file



