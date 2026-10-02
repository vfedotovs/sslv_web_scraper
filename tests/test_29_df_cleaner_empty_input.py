"""df_cleaner must survive a scrape that found nothing.

Regression tests for 2026-09-21: ogre and adazu_nov failed with
"FAILED at stage df_cleaner: 0" while the other four cities succeeded.
pandas' str.split(expand=True) returns a frame with NO columns for an empty
series, so df[0] raised KeyError(0) - and str(KeyError(0)) is "0", the whole
error text the pipeline recorded.
"""
import importlib.util
import os
from pathlib import Path

import pandas as pd
import pytest

MODULE_PATH = (Path(__file__).parent.parent / "src" / "ws" / "app"
               / "wsmodules" / "df_cleaner.py")
spec = importlib.util.spec_from_file_location("df_cleaner", MODULE_PATH)
assert spec is not None and spec.loader is not None
df_cleaner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(df_cleaner)

# Columns of pandas_df.csv, as data_format_changer writes them.
RAW_COLUMNS = ["Room_count", "Size_sq_m", "Floor", "Price", "Street",
               "Pub_date", "URL", "Ad_id"]
ONE_AD = {
    "Room_count": "2", "Size_sq_m": "54 m2", "Floor": "3/5",
    "Price": "175 000 € (3 241 €/m²)", "Street": "Brivibas 1",
    "Pub_date": "2026-09-20", "URL": "https://ss.lv/ad-1", "Ad_id": "abc123",
}


def raw_frame(rows):
    return pd.DataFrame(rows, columns=RAW_COLUMNS)


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """df_cleaner writes every hand-off file relative to the cwd."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


# --- the split helper ---

def test_split_into_columns_on_empty_series_keeps_columns():
    empty = pd.Series(dtype=str)
    split = df_cleaner.split_into_columns(empty, " ", 1, 2)
    assert list(split.columns) == [0, 1]
    assert split.empty


def test_split_into_columns_fills_missing_separator_with_nan():
    # "175 000 €" has no "(" - the sqm-price half is simply absent.
    prices = pd.Series(["175 000 €"])
    split = df_cleaner.split_into_columns(prices, "(", 1, 2)
    assert list(split.columns) == [0, 1]
    assert split[0].iloc[0] == "175 000 €"
    assert pd.isna(split[1].iloc[0])


def test_split_into_columns_normal_case_unchanged():
    split = df_cleaner.split_into_columns(pd.Series(["54 m2"]), " ", 1, 2)
    assert split[0].iloc[0] == "54" and split[1].iloc[0] == "m2"


# --- the three cleaning steps that used to raise KeyError: 0 ---

def test_clean_sqm_column_on_empty_frame():
    out = df_cleaner.clean_sqm_column(raw_frame([]))
    assert "Size_sqm" in out.columns and out.empty


def test_split_price_column_on_empty_frame():
    out = df_cleaner.split_price_column(df_cleaner.clean_sqm_column(raw_frame([])))
    assert {"Price_in_eur", "SQ_M_EUR"} <= set(out.columns)
    assert out.empty


def test_clean_sqm_eur_col_on_empty_frame():
    frame = df_cleaner.split_price_column(df_cleaner.clean_sqm_column(raw_frame([])))
    out = df_cleaner.clean_sqm_eur_col(frame)
    assert "SQ_meter_price" in out.columns and out.empty


def test_cleaning_chain_still_works_on_a_real_ad():
    frame = df_cleaner.clean_sqm_column(raw_frame([ONE_AD]))
    frame = df_cleaner.split_price_column(frame)
    frame = df_cleaner.clean_sqm_eur_col(frame)
    row = frame.iloc[0]
    assert row["Size_sqm"] == "54"
    assert row["Price_in_eur"] == 175000  # a number since dev-1.7.9.23, not "175000"
    assert row["SQ_meter_price"] == pytest.approx(3241.0)


# --- df_cleaner_main end to end ---

@pytest.mark.usefixtures("workdir")
def test_main_on_header_only_csv_does_not_raise():
    """The exact failure: pandas_df.csv exists but holds no ads."""
    raw_frame([]).to_csv("ogre-pandas_df.csv", index=False)

    df_cleaner.df_cleaner_main("ogre")

    cleaned = pd.read_csv("ogre-cleaned-sorted-df.csv")
    assert cleaned.empty
    assert "Price_in_eur" in cleaned.columns
    assert os.path.exists("ogre-email_body_txt_m4.txt")
    assert os.path.exists("ogre-email_body_add_dates_table.txt")


@pytest.mark.usefixtures("workdir")
def test_main_with_one_ad_writes_its_row():
    raw_frame([ONE_AD]).to_csv("ogre-pandas_df.csv", index=False)

    df_cleaner.df_cleaner_main("ogre")

    cleaned = pd.read_csv("ogre-cleaned-sorted-df.csv")
    assert len(cleaned) == 1
    assert cleaned.iloc[0]["Price_in_eur"] == 175000
    assert "https://ss.lv/ad-1" in Path("ogre-email_body_txt_m4.txt").read_text()


@pytest.mark.usefixtures("workdir")
def test_main_missing_file_still_uses_the_default_template():
    """Unchanged behaviour: no input file at all is a different path."""
    Path("pandas_df_default.csv").write_text("x\n")

    df_cleaner.df_cleaner_main("ogre")

    assert "No data was collected" in Path("ogre-email_body_txt_m4.txt").read_text()
