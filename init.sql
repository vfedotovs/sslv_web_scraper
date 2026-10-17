
-- Create the postgres role if it doesn't exist
DO
$$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'postgres') THEN
        CREATE ROLE postgres LOGIN SUPERUSER PASSWORD 'postgres';
    END IF;
END
$$;


-- Check if the database exists, and create it if it does not
DO
$$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_database WHERE datname = 'postgres') THEN
        EXECUTE 'CREATE DATABASE postgres';
    END IF;
END
$$;


-- Set up the table

--
-- Name: removed_ads; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.removed_ads (
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


ALTER TABLE public.removed_ads OWNER TO postgres;



--
-- Name: listed_ads; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.listed_ads (
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


ALTER TABLE public.listed_ads OWNER TO postgres;
