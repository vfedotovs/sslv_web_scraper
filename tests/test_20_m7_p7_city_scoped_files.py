"""Tests for M7 Problem 7: city-scoped intermediate filenames.

Every stage hand-off file (pandas_df.csv, cleaned-sorted-df.csv,
email body files, basic_price_stats.txt, discovered-urls.txt) must be
prefixed with the city slug so two city runs in one container cannot
overwrite each other mid-pipeline. Legacy (no-city) callers keep the
old un-prefixed names.
"""
import os
import sys
from datetime import datetime, timedelta

# container layout imports (app.wsmodules...)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "ws"))

from app.wsmodules import analytics, aws_mailer, data_format_changer, db_worker, df_cleaner, web_scraper
from app.wsmodules.file_paths import city_file
from tests.db_mocks import FakeConn


# --- naming rule -------------------------------------------------------------------

def test_city_file_prefixes_when_city_given():
    assert city_file("pandas_df.csv", "jurmala") == "jurmala-pandas_df.csv"


def test_city_file_legacy_name_without_city():
    assert city_file("pandas_df.csv") == "pandas_df.csv"
    assert city_file("pandas_df.csv", None) == "pandas_df.csv"


def test_all_modules_share_the_same_naming_rule():
    for module in (analytics, aws_mailer, data_format_changer, df_cleaner, web_scraper):
        assert module.city_file("x.txt", "riga") == "riga-x.txt"


def test_mailer_cleanup_list_is_city_scoped():
    files = aws_mailer.get_data_files_to_remove("jurmala")
    assert "jurmala-cleaned-sorted-df.csv" in files
    assert "jurmala-pandas_df.csv" in files
    assert "jurmala-basic_price_stats.txt" in files
    assert "jurmala-discovered-urls.txt" in files
    assert "cleaned-sorted-df.csv" not in files


# --- pipeline chain with city-scoped files -----------------------------------------

RAW_AD_TEMPLATE = """https://ss.lv/msg/lv/real-estate/flats/{city}/{hash}.html
Iela:><b>{street}
Istabas:>2
Platība:>50 m²
Stāvs:>3/5
Price:>{price} € (1 140 €/m²)
Date:>01.02.2022

"""


def write_raw_report(city: str, price: str, street: str, ad_hash: str):
    today = datetime.today().strftime("%Y-%m-%d")
    os.makedirs("data", exist_ok=True)
    path = f"data/{city}-raw-data-report-{today}.txt"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(RAW_AD_TEMPLATE.format(
            city=city, hash=ad_hash, street=street, price=price))
    return path


def run_format_and_clean_stages(city: str):
    data_format_changer.cloud_data_formater_main(city)
    df_cleaner.df_cleaner_main(city)
    analytics.analytics_main(city)


def test_full_chain_produces_only_city_scoped_files(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    write_raw_report("jurmala", "57 000", "Jomas 4", "aaaaa")

    run_format_and_clean_stages("jurmala")

    assert os.path.exists("jurmala-pandas_df.csv")
    assert os.path.exists("jurmala-cleaned-sorted-df.csv")
    assert os.path.exists("jurmala-email_body_txt_m4.txt")
    assert os.path.exists("jurmala-email_body_add_dates_table.txt")
    assert os.path.exists("jurmala-basic_price_stats.txt")
    # no un-prefixed hand-off files may appear
    for legacy in ("pandas_df.csv", "cleaned-sorted-df.csv",
                   "email_body_txt_m4.txt", "basic_price_stats.txt"):
        assert not os.path.exists(legacy)
    # dated copies land in data/ with the city prefix
    today = datetime.today().strftime("%Y-%m-%d")
    assert os.path.exists(f"data/jurmala-pandas_df_{today}.csv")
    assert os.path.exists(f"data/jurmala-cleaned-sorted-df-{today}.csv")


def test_two_cities_in_same_dir_do_not_collide(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    write_raw_report("jurmala", "57 000", "Jomas 4", "aaaaa")
    write_raw_report("ogre", "31 000", "Skolas 2", "bbbbb")

    run_format_and_clean_stages("jurmala")
    run_format_and_clean_stages("ogre")

    with open("jurmala-cleaned-sorted-df.csv", encoding="utf-8") as fh:
        jurmala_csv = fh.read()
    with open("ogre-cleaned-sorted-df.csv", encoding="utf-8") as fh:
        ogre_csv = fh.read()
    # each city's data survived the other city's run untouched
    assert "57000" in jurmala_csv and "aaaaa" in jurmala_csv
    assert "31000" in ogre_csv and "bbbbb" in ogre_csv
    assert "bbbbb" not in jurmala_csv
    assert "aaaaa" not in ogre_csv


def test_db_worker_reads_city_scoped_inputs(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    pub_date = (datetime.now() - timedelta(days=3)).strftime("%d.%m.%Y")
    csv_lines = [
        "URL,Room_count,Floor,Street,Pub_date,Size_sqm,Price_in_eur,SQ_meter_price",
        f"https://ss.lv/msg/lv/real-estate/flats/riga-region/riga/ccccc.html,"
        f"2,3/5,Ausekla 3,{pub_date},55,60000,1090",
    ]
    (tmp_path / "riga-cleaned-sorted-df.csv").write_text("\n".join(csv_lines) + "\n")
    (tmp_path / "riga-discovered-urls.txt").write_text(
        "https://ss.lv/msg/lv/real-estate/flats/riga-region/riga/ccccc.html\n"
    )

    conn = FakeConn([])
    monkeypatch.setattr(db_worker, "config", lambda: {})
    monkeypatch.setattr(db_worker.psycopg2, "connect", lambda **kw: conn)
    monkeypatch.setattr(db_worker, "record_counts", lambda **kw: None)

    db_worker.db_worker_main("riga")

    insert_calls = [
        c for c in conn.cur.executemany_calls if "INSERT INTO listed_ads" in c[0]
    ]
    assert len(insert_calls) == 1
    assert insert_calls[0][1][0][0] == "ccccc"
    # the un-prefixed legacy csv must not have been created as a side effect
    assert not os.path.exists("cleaned-sorted-df.csv")


def test_db_worker_legacy_call_still_uses_unprefixed_names(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cleaned-sorted-df.csv").write_text(
        "URL,Room_count,Floor,Street,Pub_date,Size_sqm,Price_in_eur,SQ_meter_price\n"
    )
    conn = FakeConn([])
    monkeypatch.setattr(db_worker, "config", lambda: {})
    monkeypatch.setattr(db_worker.psycopg2, "connect", lambda **kw: conn)
    monkeypatch.setattr(db_worker, "record_counts", lambda **kw: None)

    db_worker.db_worker_main()  # no city → legacy behavior, must not raise

    assert conn.closed
