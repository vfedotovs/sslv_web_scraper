#!/usr/bin/env python3
"""
df_cleaner.py module functionality is to clean scraped ad data values.
(M8 Phase 3: pandas removed — stdlib csv + plain row dicts only; the
input/output file names and exact CSV format are unchanged.)

Module requires input files
    - {city}-pandas_df.csv

Module has following functins
    - clean_ad_row - pure-string cleanup of one raw csv row (keyword
      removal + sqm/price/eur-sqm splits, previously 4 pandas helpers)
    - write_cleaned_csv - writes cleaned rows in the exact legacy format
    - save_text_report_to_file - Writes email body text to file
    - create_email_body - generates and saves Milestone 4 legacy report content to file
    - df_cleaner_main - main entry point
    - create_file_copy - backups file with name-YYYY-MMDD format to /data folder
    - create_mb_file_copy - backups mail body file with name-YYYY-MMDD format to /data folder

Module creates output file:
    - {city}-cleaned-sorted-df.csv
    - {city}-email_body_txt_m4.txt
    - {city}-email_body_add_dates_table.txt

Modulel TODO tasks:
    - [ ] refactor create file backup function
"""
import csv
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
import os
import shutil
import sys

# M7 P7: city-scoped hand-off filenames; fall back for standalone runs.
try:
    from app.wsmodules.file_paths import city_file
except Exception:
    def city_file(base_name, city=None):
        return f"{city}-{base_name}" if city else base_name


log = logging.getLogger(__name__)
log.setLevel(logging.INFO)
LOG_FILE = "dataframe_sanitizer.log"
file_handler = RotatingFileHandler(LOG_FILE,
                                   maxBytes=1024 * 1024,
                                   backupCount=9)
file_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)-5.5s] : %(funcName)s: %(lineno)d: %(message)s")
file_handler.setFormatter(file_formatter)
log.addHandler(file_handler)
stdout_handler = logging.StreamHandler(sys.stdout)
stdout_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)-5.5s] : %(funcName)s: %(lineno)d: %(message)s")
stdout_handler.setFormatter(stdout_formatter)
log.addHandler(stdout_handler)


# M8 Phase 3: column order of the cleaned-sorted-df.csv hand-off file
# (identical to the old DataFrame output — the byte-level contract with
# db_worker, analytics, aws_mailer and the golden-chain tests).
CLEANED_COLUMNS = ["URL", "Room_count", "Floor", "Street", "Pub_date",
                   "Size_sqm", "Price_in_eur", "SQ_meter_price"]


def clean_ad_row(raw_row: dict) -> dict:
    """M8 Phase 3: pure-string cleanup of one raw pandas_df.csv row.

    Replaces the four pandas helpers (keyword regex removal, sqm split,
    price split, eur-sqm cleanup). Field examples in -> out:
        Room_count 'Istabas:>2'                 -> '2'
        Size_sq_m  'Platiba:>50 m²'             -> Size_sqm '50'
        Floor      'Stavs:>3/9/lifts'           -> '3/9'
        Street     'Iela:><b>Jaunatnes iela 4'  -> 'Jaunatnes iela 4'
        Price      'Price:>57 000 € (1 140 €/m²)'
                   -> Price_in_eur '57000', SQ_meter_price 1140.0
        Pub_date   'Date:>01.02.2026'           -> '01.02.2026'

    The '_index' key carries the source row's leading index-column value
    so the written csv keeps pre-sort row numbers exactly like pandas.
    """
    price_raw = raw_row["Price"].replace("Price:>", "")
    total_part, _, sqm_part = price_raw.partition("(")
    # Replicates the old pandas split(' ', n=2) + token0+token1 concat
    tokens = total_part.split(" ", 2)
    price_in_eur = tokens[0] + (tokens[1] if len(tokens) > 1 else "")
    sq_meter_price = float(sqm_part.split("€", 1)[0].replace(" ", ""))
    return {
        "URL": raw_row["URL"],
        "Room_count": raw_row["Room_count"].replace("Istabas:>", ""),
        "Floor": raw_row["Floor"].replace("Stavs:>", "").replace("/lifts", ""),
        "Street": raw_row["Street"].replace("Iela:><b>", ""),
        "Pub_date": raw_row["Pub_date"].replace("Date:>", ""),
        "Size_sqm": raw_row["Size_sq_m"].replace("Platiba:>", "").split(" ", 1)[0],
        "Price_in_eur": price_in_eur,
        "SQ_meter_price": sq_meter_price,
        "_index": raw_row.get("", ""),
    }


def write_cleaned_csv(rows: list, dest_file: str) -> None:
    """M8 Phase 3: write cleaned ad rows byte-identical to the old
    DataFrame.to_csv() output: leading index column with PRE-SORT row
    numbers, CLEANED_COLUMNS order, '\\n' line endings, utf-8. An empty
    rows list still writes the header line (zero-new-ads day)."""
    log.info("Writing %d cleaned ad rows to %s", len(rows), dest_file)
    with open(dest_file, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow([""] + CLEANED_COLUMNS)
        for row in rows:
            writer.writerow([row["_index"]] + [row[c] for c in CLEANED_COLUMNS])


def save_text_report_to_file(text_lines: list, file_name: str) -> None:
    """Writes oneline data text to mailer report file"""
    log.info(f"Saving text report to file : {file_name}")
    with open(file_name, 'a') as the_file:
        for text_line in text_lines:
            the_file.write(f"{text_line}\n")
    text_line_cnt = len(text_lines)
    log.info(
        f"Completed writing {text_line_cnt} lines to {file_name} file ")


def create_email_body(cleaned_rows: list, file_name: str) -> None:
    """Creates categorized by room count ad hash : data for email body.

    Requires:
        cleaned_rows: list of cleaned ad row dicts (M8 Phase 3)

    Creates:
        email_body_txt_m4.txt: text file"""
    log.info(f"Started creation of {file_name} file")
    email_body_txt = []
    for room_count in range(4):
        room_count_str = str(room_count + 1)
        section_line = str(room_count_str + " room apartment segment:")
        email_body_txt.append(section_line)
        colum_line = "[Rooms, Floor, Size, Price, SQM Price, Apartment Street, Pub_date,  URL]"
        email_body_txt.append(colum_line)
        for row in cleaned_rows:
            if str(row['Room_count']) != room_count_str:
                continue
            report_line = "  " + str(row['Room_count']) + "     " + \
                          str(row["Floor"]) + "    " + \
                          str(row["Size_sqm"]) + "   " + \
                          str(row["Price_in_eur"]) + "    " + \
                          str(row['SQ_meter_price']) + "   " + \
                          str(row['Street']) + "   " + \
                          str(row['Pub_date']) + " " + \
                          str(row["URL"])
            email_body_txt.append(report_line)
    log.info(f"Completed creation of {file_name} file")
    save_text_report_to_file(email_body_txt, file_name)


def extract_uniq_date_count(cleaned_rows: list) -> dict:
    """ Extracts dates from cleaned rows' Pub_date values
        and count uniq date occourences.
    """
    log.info("Started inserted add date extraction")
    add_date_list = [row['Pub_date'] for row in cleaned_rows]
    return {date: add_date_list.count(date) for date in set(add_date_list)}


def order_keys_by_month(data: dict) -> list:
    """
    Extracts unique month values from keys in the given
    dictionary and sorts them.

    Args:
        data (dict): A dictionary where keys are date strings
                     in the format 'DD.MM.YYYY' and values
                     represent some counts or data associated
                     with those dates.
    Returns:
        list: A sorted list of unique month values extractedfrom
              from the keys of the dictionary.
    Example:
        >>> data = {'01.12.2023': 5, '15.11.2023': 3, '20.12.2023': 7}
        >>> order_keys_by_month(data)
        ['11.2023', '12.2023']
    """
    log.info("Started ordered month value extraction")
    month_list = []
    for date_key, add_count in data.items():
        curr_month_value = '.'.join(date_key.split('.')[1:3])
        month_list.append(curr_month_value)
    unique_months = list(set(month_list))
    log.info(f"List of only uniq month values: {unique_months}")
    unique_months .sort()
    return unique_months


def split_pub_dates_by_month(data: dict, months: list) -> list:
    """TODO: add docstring"""
    list_of_dicts = []
    pub_date_report_lines = []
    for month in months:
        curr_dict = {}
        for key_date, add_count in data.items():
            curr_month = '.'.join(key_date.split('.')[1:3])
            if curr_month == month:
                curr_dict[key_date] = add_count
        list_of_dicts.append(curr_dict)
    for month_dict in list_of_dicts:
        month_line = "\n--- Month: ---"
        pub_date_report_lines.append(month_line)
        sorted_month_dict = dict(sorted(month_dict.items()))
        for k, v in sorted_month_dict.items():
            data_line = f"Pub_date: {k} ->  Listed add count: {v} "
            pub_date_report_lines.append(data_line)
    # M7 P9: the full per-date table goes to the report file; log it only
    # at DEBUG and keep a count at INFO
    log.info(f"Built pub-date report with {len(pub_date_report_lines)} lines")
    for line in pub_date_report_lines:
        log.debug(line)
    return pub_date_report_lines


def save_pub_dates_report_to(pubdates_out_file_name: str, month_data: list) -> None:
    """Writes oneline data text to pub report file"""
    log.info(f"Saving text report to file : {pubdates_out_file_name}")
    with open(pubdates_out_file_name, 'a') as the_file:
        for text_line in month_data:
            the_file.write(f"{text_line}\n")
    text_line_cnt = len(month_data)
    log.info(
        f"Completed writing {text_line_cnt} lines to {pubdates_out_file_name} file ")


def df_cleaner_main(city_name: str = None):
    """ Cleans ad rows, sorts by price in EUR, save to csv file.
    M7 P7: all hand-off filenames are city-scoped when city_name given.
    M8 Phase 3: stdlib csv + row dicts instead of pandas."""
    log.info(" --- Started df_cleaner module ---")
    RAW_DATA_FILE = city_file('pandas_df.csv', city_name)
    DEFAULT_DATA_FILE = 'pandas_df_default.csv'
    CLEANED_CSV_FILE = city_file('cleaned-sorted-df.csv', city_name)
    EMAIL_BODY_OUTPUT_FILE = city_file('email_body_txt_m4.txt', city_name)
    EMPTY_DF_MAIL_TEMPLATE = "No data was collected during last scraping job."
    try:
        log.info(f'Loading {RAW_DATA_FILE} file.')
        with open(RAW_DATA_FILE, 'r', encoding='utf-8', newline='') as file:
            raw_rows = list(csv.DictReader(file))
        cleaned_rows = []
        for idx, raw_row in enumerate(raw_rows):
            row = clean_ad_row(raw_row)
            if row["_index"] == "":
                row["_index"] = str(idx)
            cleaned_rows.append(row)
        # M8 Phase 3 NOTE: pandas sorted Price_in_eur as a STRING (the
        # column was built by string concat), i.e. LEXICOGRAPHIC order.
        # We keep the string sort deliberately so the golden files stay
        # byte-identical; switching to a numeric sort is a conscious
        # future change (update goldens + test_22 together).
        sorted_rows = sorted(cleaned_rows, key=lambda r: r["Price_in_eur"])
        write_cleaned_csv(sorted_rows, CLEANED_CSV_FILE)
        create_file_copy(CLEANED_CSV_FILE)
        if not sorted_rows:
            # M8 Phase 3: graceful zero-new-ads day. Previously this
            # crashed with KeyError inside the pandas column splits —
            # i.e. every day without new ads since M7 P1. Downstream
            # gets a header-only csv and the empty email template.
            with open(EMAIL_BODY_OUTPUT_FILE, 'w', encoding='utf-8') as out_file:
                out_file.write(EMPTY_DF_MAIL_TEMPLATE)
            log.info('No ads in %s — wrote header-only %s and empty email template.',
                     RAW_DATA_FILE, CLEANED_CSV_FILE)
            log.info(" --- Completed df_cleaner module ---")
            return
        create_email_body(sorted_rows, EMAIL_BODY_OUTPUT_FILE)
        create_mb_file_copy(EMAIL_BODY_OUTPUT_FILE)
        sorted_pub_dates = extract_uniq_date_count(sorted_rows)
        ordered_month_keys = order_keys_by_month(sorted_pub_dates)
        splited_dates = split_pub_dates_by_month(
            sorted_pub_dates, ordered_month_keys)
        save_pub_dates_report_to(
            city_file('email_body_add_dates_table.txt', city_name),
            splited_dates)

    except FileNotFoundError:
        log.error(f'File {RAW_DATA_FILE} not found')
        try:
            log.info(f'Loading {DEFAULT_DATA_FILE} file.')
            with open(DEFAULT_DATA_FILE, 'r') as file:
                content = file.read()
                with open(EMAIL_BODY_OUTPUT_FILE, 'w') as out_file:
                    # Write the entire string to the file
                    out_file.write(EMPTY_DF_MAIL_TEMPLATE)
                log.info(
                    f'Completed write empty email template to {EMAIL_BODY_OUTPUT_FILE} file.')
        except FileNotFoundError:
            log.error(f'{DEFAULT_DATA_FILE} does not exist.')
            raise
        except Exception as e:
            log.error(f"An error occurred: {e}")
            raise
    log.info(" --- Completed df_cleaner module ---")


def _copy_to_data_folder(source_file: str, dest_file: str) -> None:
    """Copies a hand-off file into data/ (M7 P7: shutil, not os.system cp)."""
    if not os.path.exists('data'):
        os.makedirs('data')
    try:
        shutil.copy2(source_file, os.path.join('data', dest_file))
        log.info(f"Completed creating file copy of {dest_file}")
    except OSError as e:
        log.error(f"Failed to copy {source_file} to data/{dest_file}: {e}")


def create_file_copy(source_file: str = 'cleaned-sorted-df.csv') -> None:
    """Creates dated csv copy in data folder"""
    log.info(
        "Started copy of %s (dated) in data folder", source_file)
    todays_date = datetime.today().strftime('%Y-%m-%d')
    base_name = source_file[:-len('.csv')] if source_file.endswith('.csv') else source_file
    dest_file = base_name + '-' + todays_date + '.csv'
    _copy_to_data_folder(source_file, dest_file)


def create_mb_file_copy(source_file: str = 'email_body_txt_m4.txt') -> None:
    """Creates dated mail-body copy in data folder"""
    log.info(
        "Started copy of %s (dated) in data folder", source_file)
    todays_date = datetime.today().strftime('%Y-%m-%d')
    base_name = source_file[:-len('.txt')] if source_file.endswith('.txt') else source_file
    dest_file = base_name + '-' + todays_date + '.txt'
    _copy_to_data_folder(source_file, dest_file)


if __name__ == "__main__":
    df_cleaner_main()
