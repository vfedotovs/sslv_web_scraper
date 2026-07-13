"""M8 Phase 4: analytics + db_worker run on stdlib csv, no pandas.

The byte-level output contract is enforced by the Phase 1 golden-chain
harness (test_22); these tests cover the module-level specifics.
"""
import os
import sys

# container layout imports (app.wsmodules...)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "ws"))

from app.wsmodules import analytics, db_worker


def test_modules_do_not_import_pandas():
    for module in (analytics, db_worker):
        assert not hasattr(module, "pd")
        with open(module.__file__, encoding="utf-8") as fh:
            assert "import pandas" not in fh.read()


# --- analytics ---------------------------------------------------------------------

def test_group_prices_by_room_casts_and_groups():
    rows = [
        {"Room_count": "2", "Price_in_eur": "57000"},
        {"Room_count": "2", "Price_in_eur": "38500"},
        {"Room_count": "1", "Price_in_eur": "9500"},
    ]
    grouped = analytics.group_prices_by_room(rows)
    assert grouped == {2: [57000, 38500], 1: [9500]}
    # keys are ints so segment ordering stays numeric, values are ints
    # so min/max/avg math stays numeric (not lexicographic)
    assert all(isinstance(k, int) for k in grouped)
    assert all(isinstance(p, int) for prices in grouped.values() for p in prices)


def test_group_prices_by_room_empty_rows():
    assert analytics.group_prices_by_room([]) == {}


def test_price_stats_math_survives_string_input():
    """'9500' vs '100000': numeric grouping must give min=9500."""
    rows = [
        {"Room_count": "1", "Price_in_eur": "100000"},
        {"Room_count": "1", "Price_in_eur": "9500"},
    ]
    stats = analytics.calculate_price_stats(analytics.group_prices_by_room(rows))
    ad_count, min_price, max_price, price_range, avg_price = stats[1]
    assert min_price == "9500"
    assert max_price == "100000"
    assert price_range == "90500"


# --- db_worker ---------------------------------------------------------------------

CSV_HEADER = ",URL,Room_count,Floor,Street,Pub_date,Size_sqm,Price_in_eur,SQ_meter_price"


def write_cleaned_csv(path, data_lines):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(CSV_HEADER + "\n")
        for line in data_lines:
            fh.write(line + "\n")


def test_load_csv_rows_returns_dicts(tmp_path):
    path = str(tmp_path / "cleaned.csv")
    write_cleaned_csv(path, [
        "0,https://ss.lv/msg/lv/real-estate/flats/riga-region/riga/aaaaa.html,"
        "2,3/9,Jaunatnes iela 4,01.02.2026,50,57000,1140.0",
    ])
    rows = db_worker.load_csv_rows(path)
    assert len(rows) == 1
    assert rows[0]["Price_in_eur"] == "57000"
    assert rows[0]["Room_count"] == "2"


def test_load_csv_rows_header_only_returns_empty(tmp_path):
    path = str(tmp_path / "cleaned.csv")
    write_cleaned_csv(path, [])
    assert db_worker.load_csv_rows(path) == []


def test_load_csv_rows_zero_byte_file_returns_empty(tmp_path):
    """pd.read_csv raised EmptyDataError here; DictReader is graceful."""
    path = str(tmp_path / "cleaned.csv")
    open(path, "w").close()
    assert db_worker.load_csv_rows(path) == []


def test_extract_new_msg_data_casts_numeric_fields():
    rows = [{
        "URL": "https://ss.lv/msg/lv/real-estate/flats/riga-region/riga/aaaaa.html",
        "Room_count": "2",
        "Floor": "3/9",
        "Street": "Jaunatnes iela 4",
        "Pub_date": "01.02.2026",
        "Size_sqm": "50",
        "Price_in_eur": "57000",
        "SQ_meter_price": "1140.0",
    }]
    data = db_worker.extract_new_msg_data(rows, ["aaaaa"])
    row = data["aaaaa"]
    assert row[0] == 2 and isinstance(row[0], int)        # Room_count
    assert row[1] == "9" and row[2] == "3"                # floors stay str
    assert row[3] == 57000 and isinstance(row[3], int)    # price
    assert row[4] == 50 and isinstance(row[4], int)       # sqm
    assert row[5] == 1140.0 and isinstance(row[5], float) # sqm price


def test_ensure_csv_exists_writes_plain_header(tmp_path):
    path = str(tmp_path / "placeholder.csv")
    db_worker.ensure_csv_exists(path, headers=["URL", "Room_count"])
    with open(path, encoding="utf-8") as fh:
        assert fh.read() == "URL,Room_count\n"
