"""M8 Phase 3: df_cleaner runs on stdlib csv + row dicts, no pandas.

The byte-level output contract is enforced by the Phase 1 golden-chain
harness (test_22); these tests cover clean_ad_row and the module-level
specifics directly.
"""
import os
import sys

# container layout imports (app.wsmodules...)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "ws"))

from app.wsmodules import df_cleaner


def make_raw_row(**overrides):
    row = {
        "": "0",
        "URL": "https://ss.lv/msg/lv/real-estate/flats/ogre-and-reg/ogre/aaa03.html",
        "Room_count": "Istabas:>2",
        "Size_sq_m": "Platiba:>50 m²",
        "Floor": "Stavs:>3/9/lifts",
        "Street": "Iela:><b>Jaunatnes iela 4",
        "Price": "Price:>57 000 € (1 140 €/m²)",
        "Pub_date": "Date:>01.02.2026",
    }
    row.update(overrides)
    return row


def test_module_does_not_import_pandas():
    assert not hasattr(df_cleaner, "pd")
    with open(df_cleaner.__file__, encoding="utf-8") as fh:
        assert "import pandas" not in fh.read()


def test_clean_ad_row_all_fields():
    row = df_cleaner.clean_ad_row(make_raw_row())
    assert row["URL"].endswith("aaa03.html")
    assert row["Room_count"] == "2"
    assert row["Floor"] == "3/9"          # /lifts removed
    assert row["Street"] == "Jaunatnes iela 4"
    assert row["Pub_date"] == "01.02.2026"
    assert row["Size_sqm"] == "50"        # m² dropped
    assert row["Price_in_eur"] == "57000" # thousands separator collapsed
    assert row["SQ_meter_price"] == 1140.0
    assert row["_index"] == "0"


def test_clean_ad_row_decimal_sqm_price():
    row = df_cleaner.clean_ad_row(
        make_raw_row(Price="Price:>175 000 € (2 302.63 €/m²)")
    )
    assert row["Price_in_eur"] == "175000"
    assert row["SQ_meter_price"] == 2302.63


def test_clean_ad_row_floor_without_lift():
    row = df_cleaner.clean_ad_row(make_raw_row(Floor="Stavs:>5/5"))
    assert row["Floor"] == "5/5"


def test_write_cleaned_csv_keeps_presort_index(tmp_path):
    dest = str(tmp_path / "out.csv")
    rows = [
        df_cleaner.clean_ad_row(make_raw_row(**{"": "7"})),
        df_cleaner.clean_ad_row(
            make_raw_row(**{"": "2"}, Price="Price:>9 500 € (475 €/m²)")
        ),
    ]
    df_cleaner.write_cleaned_csv(rows, dest)
    with open(dest, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    assert lines[0] == ",URL,Room_count,Floor,Street,Pub_date,Size_sqm,Price_in_eur,SQ_meter_price"
    assert lines[1].startswith("7,")   # original row numbers survive
    assert lines[2].startswith("2,")
    assert lines[1].endswith("57000,1140.0")
    assert lines[2].endswith("9500,475.0")


def test_sort_stays_lexicographic_like_pandas(monkeypatch, tmp_path):
    """String sort on Price_in_eur is deliberate (goldens pin it):
    '100000' sorts before '9500'."""
    monkeypatch.chdir(tmp_path)
    header = ",URL,Room_count,Size_sq_m,Floor,Street,Price,Pub_date\n"
    raw = make_raw_row()
    line_cheap = '0,{URL},Istabas:>1,Platiba:>20 m²,Stavs:>1/5,Iela:><b>A,"Price:>9 500 € (475 €/m²)",Date:>15.03.2026\n'.format(**raw)
    line_expensive = '1,{URL},Istabas:>3,Platiba:>80 m²,Stavs:>2/2,Iela:><b>B,"Price:>100 000 € (1 250 €/m²)",Date:>20.04.2026\n'.format(**raw)
    (tmp_path / "pandas_df.csv").write_text(header + line_cheap + line_expensive,
                                            encoding="utf-8")
    df_cleaner.df_cleaner_main()
    with open(tmp_path / "cleaned-sorted-df.csv", encoding="utf-8") as fh:
        data_lines = fh.read().splitlines()[1:]
    assert "100000" in data_lines[0]
    assert "9500" in data_lines[1]
