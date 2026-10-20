-- Table creation for listed_ads and removed_ads
-- Run automatically by postgres docker image on fresh volume (no prior data)

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
);

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
);

-- Optional: grant to the app user (new_docker_user)
-- The image runs init as postgres, but tables will be accessible.
