\c new_docker_db;

CREATE TABLE listed_ads(
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
);

CREATE TABLE removed_ads(
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
);
