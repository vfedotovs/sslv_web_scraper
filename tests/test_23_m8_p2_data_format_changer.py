"""M8 Phase 2: data_format_changer runs on stdlib csv, no pandas.

The byte-level output contract is enforced by the Phase 1 golden-chain
harness (test_22); these tests cover the module-level specifics.
"""
import os
import sys

# container layout imports (app.wsmodules...)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "ws"))

from app.wsmodules import data_format_changer

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "m8",
                       "raw-data-report.txt")


def test_module_does_not_import_pandas():
    assert not hasattr(data_format_changer, "pd")
    with open(data_format_changer.__file__, encoding="utf-8") as fh:
        source = fh.read()
    assert "import pandas" not in source


def test_create_oneline_report_returns_row_dicts():
    rows = data_format_changer.create_oneline_report(FIXTURE)
    # 10 ads in fixture; the last one has no Date line and is trimmed
    assert len(rows) == 9
    assert list(rows[0].keys()) == data_format_changer.CSV_COLUMNS
    assert rows[0]["URL"].endswith("aaa01.html")
    assert rows[0]["Room_count"] == "Istabas:>1"
    assert rows[0]["Price"] == "Price:>9 500 € (475 €/m²)"


def test_write_rows_to_csv_matches_pandas_format(tmp_path):
    dest = str(tmp_path / "out.csv")
    rows = [
        {"URL": "u1", "Room_count": "r1", "Size_sq_m": "s1", "Floor": "f1",
         "Street": "st1", "Price": "p1", "Pub_date": "d1"},
        {"URL": "u2", "Room_count": "r2", "Size_sq_m": "s2", "Floor": "f2",
         "Street": "st2", "Price": "p2", "Pub_date": "d2"},
    ]
    data_format_changer.write_rows_to_csv(rows, dest)
    with open(dest, encoding="utf-8") as fh:
        content = fh.read()
    assert content == (
        ",URL,Room_count,Size_sq_m,Floor,Street,Price,Pub_date\n"
        "0,u1,r1,s1,f1,st1,p1,d1\n"
        "1,u2,r2,s2,f2,st2,p2,d2\n"
    )


def test_write_rows_to_csv_empty_writes_header_only(tmp_path):
    dest = str(tmp_path / "out.csv")
    data_format_changer.write_rows_to_csv([], dest)
    with open(dest, encoding="utf-8") as fh:
        assert fh.read() == ",URL,Room_count,Size_sq_m,Floor,Street,Price,Pub_date\n"
