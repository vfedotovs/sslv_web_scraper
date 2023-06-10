#!/bin/bash


echo "Listing locally ruinning postgress containers ..."
PG_CONTAINER_INFO=$(docker ps | grep db-1)
echo $PG_CONTAINER_INFO


PG_CONTAINER_NAME=$(docker ps | grep db-1 | awk '{print $NF }')
echo "Trying to connect postgres DB container ... "
echo "Describing datanase table information  psql and dt+ ...."
docker exec $PG_CONTAINER_NAME psql \
    -U new_docker_user \
    -d new_docker_db \
    -c '\dt+'


# For locally installed postgres DB
#psql -h localhost -U new_docker_user -d new_docker_db -c '\dt+'


# Listing all ads in currently listed table:
echo "Listing all ads in listed_ads table..."
docker exec $PG_CONTAINER_NAME psql \
    -U new_docker_user \
    -d new_docker_db \
    -c 'select * from listed_ads;' | head -n 5

echo "Listing last 10 ads in removed_ads table..."
docker exec $PG_CONTAINER_NAME psql \
    -U new_docker_user \
    -d new_docker_db \
    -c 'select * from removed_ads;' | head -n 5 


echo "Extracting uniq room_count values = 1 from in remmoved_ads table .."
docker exec $PG_CONTAINER_NAME psql \
    -U new_docker_user \
    -d new_docker_db \
    -c 'SELECT room_count, COUNT (room_count) FROM removed_ads GROUP BY room_count ORDER BY COUNT DESC;'


echo "Extracting uniq house floos values from in remmoved_ads table .."
docker exec $PG_CONTAINER_NAME psql \
    -U new_docker_user \
    -d new_docker_db \
    -c 'SELECT house_floors, COUNT (house_floors) FROM removed_ads GROUP BY house_floors ORDER BY COUNT DESC;'


echo "Extracting uniq apt_floor values from in remmoved_ads table .."
docker exec $PG_CONTAINER_NAME psql \
    -U new_docker_user \
    -d new_docker_db \
    -c 'SELECT apt_floor, COUNT (apt_floor) FROM removed_ads GROUP BY apt_floor ORDER BY COUNT DESC;'

echo "Extracting uniq days_listed  values from in remmoved_ads table .."
docker exec $PG_CONTAINER_NAME psql \
    -U new_docker_user \
    -d new_docker_db \
    -c 'SELECT days_listed , COUNT (days_listed ) FROM removed_ads GROUP BY days_listed ORDER BY COUNT DESC;' | head -n 10

echo "Extracting uniq sqm  values from in remmoved_ads table .."
docker exec $PG_CONTAINER_NAME psql \
    -U new_docker_user \
    -d new_docker_db \
    -c 'SELECT sqm , COUNT (sqm) FROM removed_ads GROUP BY sqm ORDER BY COUNT DESC;' | head -n 10


echo "Extracting average price from remmoved_ads table .. where listed_date matched 2022.01 - JAN"
docker exec $PG_CONTAINER_NAME psql \
    -U new_docker_user \
    -d new_docker_db \
    -c "SELECT AVG(price) from removed_ads WHERE listed_date LIKE '2022.01%' "

echo "Extracting average price from remmoved_ads table .. where listed_date matched 2022.03 - MAR"
docker exec $PG_CONTAINER_NAME psql \
    -U new_docker_user \
    -d new_docker_db \
    -c "SELECT AVG(price) from removed_ads WHERE listed_date LIKE '2022.03%' "

echo "extracting average price from remmoved_ads table .. where listed_date matched 2022.04 - apr"
docker exec $PG_CONTAINER_NAME psql \
    -U new_docker_user \
    -d new_docker_db \
    -c "SELECT AVG(price) from removed_ads WHERE listed_date LIKE '2022.04%' "

echo "extracting average price from remmoved_ads table .. where listed_date matched 2022.11 - NOV last month in DB"
docker exec $PG_CONTAINER_NAME psql \
    -U new_docker_user \
    -d new_docker_db \
    -c "SELECT AVG(price) from removed_ads WHERE listed_date LIKE '2022.11%' "


echo "Extracting average price from remmoved_ads table .. where listed_date matched 2021.08 - AUG first month of PROD "
docker exec $PG_CONTAINER_NAME psql \
    -U new_docker_user \
    -d new_docker_db \
    -c "SELECT AVG(price) from removed_ads WHERE listed_date LIKE '2021.08%' "


echo "Extracting average price from remmoved_ads table .. where listed_date matched year 2021 only 2 rooms"
docker exec $PG_CONTAINER_NAME psql \
    -U new_docker_user \
    -d new_docker_db \
    -c "SELECT AVG(price) from removed_ads WHERE listed_date LIKE '2021%' AND room_count = 2 "

echo "Extracting average price from remmoved_ads table .. where listed_date matched year 2022 only 2 rooms "
docker exec $PG_CONTAINER_NAME psql \
    -U new_docker_user \
    -d new_docker_db \
    -c "SELECT AVG(price) from removed_ads WHERE listed_date LIKE '2022%' AND room_count = 2 "










