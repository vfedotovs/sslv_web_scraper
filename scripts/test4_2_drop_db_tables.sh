#!/bin/bash


psql -h localhost -U docker -d docker -c '\dt+'

# clear tables
psql -h localhost -U docker -d docker -c 'DROP TABLE listed_ads, removed_ads CASCADE;'

psql -h localhost -U docker -d docker -c '\dt+'


# init create empty tables

# restore backup from sql file

#psql -h localhost -U docker -d docker -c 'select * from listed_ads;'


