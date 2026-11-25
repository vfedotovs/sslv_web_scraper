# from src.ws.app.wsmodules.df_cleaner import split_price_column
# import pandas as pd
#
#
# def test_split_price_column():
#     # Test with a dataframe that contains a price column with multiple values
#     df = pd.DataFrame(
#         {"Price": ["€ 1 000 (17.65)", "€ 2 000 (30.85)", "€ 3 000 (42.55)"]})
#     expected_output = pd.DataFrame({"SQ_M_EUR": ["17.65", "30.85", "42.55"],
#                                     "Price_in_eur": ["€ 1 000", "€ 2 000", "€ 3 000"]})
#     assert split_price_column(df).equals(expected_output)
#
#     # Test with a dataframe that contains a price column with a single value
#     df = pd.DataFrame({"Price": ["€ 1 000 (17.65)"]})
#     expected_output = pd.DataFrame({"SQ_M_EUR": ["17.65"],
#                                     "Price_in_eur": ["€ 1 000"]})
#     assert split_price_column(df).equals(expected_output)
#
#     # Test with a dataframe that contains a price column with empty values
#     df = pd.DataFrame({"Price": ["", "", ""]})
#     expected_output = pd.DataFrame({"SQ_M_EUR": ["", "", ""],
#                                     "Price_in_eur": ["", "", ""]})
#     assert split_price_column(df).equals(expected_output)

#     REMOVE THIS: line added to trigger CICD


# --- dev-1.7.9.23: price parsing and email segments (staging, 2026-10-02) ---
import os
import re
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "ws"))
from app.wsmodules import df_cleaner  # noqa: E402

REPAIR_SH = Path(__file__).parent.parent / "scripts" / "repair_truncated_prices.sh"


def raw_frame(rows):
    """rows: (rooms, price text) as the scraper writes them."""
    return pd.DataFrame({
        "URL": [f"https://ss.lv/msg/{i}.html" for i in range(len(rows))],
        "Room_count": [f"Istabas:>{rooms}" for rooms, _ in rows],
        "Size_sq_m": ["Platiba:>100 m²"] * len(rows),
        "Floor": ["Stavs:>1/5"] * len(rows),
        "Street": ["Iela:><b>Rīgas 90"] * len(rows),
        "Price": [f"Price:>{price}" for _, price in rows],
        "Pub_date": ["Date:>01.10.2026"] * len(rows),
    })


def cleaned(rows):
    df = df_cleaner.clean_data_frame(raw_frame(rows))
    return df_cleaner.clean_sqm_eur_col(
        df_cleaner.split_price_column(df_cleaner.clean_sqm_column(df)))


@pytest.mark.parametrize("text,expected", [
    ("59 000 € (1 255.32 €/m²)", 59000),
    ("145 000 € (3 295.45 €/m²)", 145000),
    ("1 130 000 € (7 483.44 €/m²)", 1130000),   # jurmala mlxbi, stored as 1130
    ("1 129 950 € (7 483.11 €/m²)", 1129950),
    ("12 500 000 € (9 000 €/m²)", 12500000),
])
def test_price_keeps_every_digit_group(text, expected):
    assert cleaned([(2, text)])["Price_in_eur"].tolist() == [expected]


def test_price_is_numeric_so_sorting_is_by_value():
    """The 2026-10-02 email listed 145000 before 59000 and 85000 after 490000."""
    df = cleaned([(2, "145 000 € (3 295.45 €/m²)"), (2, "59 000 € (1 255.32 €/m²)"),
                  (4, "85 000 € (977.01 €/m²)"), (4, "490 000 € (1 719.30 €/m²)")])
    assert df.sort_values(by="Price_in_eur")["Price_in_eur"].tolist() == [
        59000, 85000, 145000, 490000]


def test_unparseable_price_is_missing_not_garbage():
    assert cleaned([(2, "maiņai")])["Price_in_eur"].isna().all()


def email_body(tmp_path, rows):
    out = tmp_path / "email_body.txt"
    df = cleaned(rows).sort_values(by="Price_in_eur")
    csv = tmp_path / "cleaned.csv"
    df.to_csv(csv)                       # as df_cleaner_main does
    df_cleaner.create_email_body(pd.read_csv(csv, index_col=False), str(out))
    return out.read_text().splitlines()


def test_email_lists_5_and_6_room_ads(tmp_path):
    """range(4) dropped them: the 515000 5-room ad was in the analytics
    table but not the listing (25 such ads listed on staging today)."""
    lines = email_body(tmp_path, [(2, "59 000 € (1 255.32 €/m²)"),
                                  (5, "515 000 € (2 575 €/m²)"),
                                  (6, "1 000 000 € (2 268 €/m²)")])
    segments = [line for line in lines if line.endswith("room apartment segment:")]
    assert segments == [f"{n} room apartment segment:" for n in (1, 2, 3, 4, 5, 6)]
    body = "\n".join(lines)
    assert "515000" in body and "1000000" in body
    assert body.index("5 room apartment segment:") < body.index("515000") \
        < body.index("6 room apartment segment:") < body.index("1000000")


def test_email_segment_is_ordered_by_price(tmp_path):
    lines = email_body(tmp_path, [(2, "145 000 € (3 295.45 €/m²)"),
                                  (2, "59 000 € (1 255.32 €/m²)")])
    prices = [line.split()[3] for line in lines if line.startswith("  2 ")]
    assert prices == ["59000", "145000"]


def test_email_without_rows_still_has_segments_1_to_4(tmp_path):
    out = tmp_path / "email_body.txt"
    empty = pd.DataFrame(columns=["URL", "Room_count", "Floor", "Size_sqm",
                                  "Price_in_eur", "SQ_meter_price", "Street", "Pub_date"])
    df_cleaner.create_email_body(empty, str(out))
    assert [line for line in out.read_text().splitlines() if "segment" in line] == [
        f"{n} room apartment segment:" for n in (1, 2, 3, 4)]


# --- scripts/repair_truncated_prices.sh: which rows it would change ---

def repair_condition():
    text = REPAIR_SH.read_text()
    return " ".join(re.search(r'TRUNCATED="([^"]+)"', text).group(1).split())


def test_repair_matches_exactly_the_staging_rows():
    """The five jurmala rows from 2026-10-02, plus rows that must not change."""
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE ads (url_hash TEXT, price INT, sqm INT, sqm_price INT)")
    db.executemany("INSERT INTO ads VALUES (?, ?, ?, ?)", [
        ("mlxbi", 1130, 151, 7483), ("becfin", 1000, 441, 2268),
        ("gmenn", 1650, 436, 3784), ("bexoph", 1130, 151, 7483),
        ("ajkmi", 1800, 229, 7860),
        ("normal", 145000, 44, 3295),          # a correct price
        ("cheap", 9000, 30, 300),              # a real < 10000 price
        ("repaired", 1130000, 151, 7483),      # already fixed: idempotent
        ("nosqm", 1130, 0, 0),                 # nothing to confirm with
    ])
    matched = [row[0] for row in db.execute(
        f"SELECT url_hash FROM ads WHERE {repair_condition()} ORDER BY url_hash")]
    assert matched == ["ajkmi", "becfin", "bexoph", "gmenn", "mlxbi"]
