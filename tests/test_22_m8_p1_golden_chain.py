"""M8 Phase 1: golden-file harness for the pandas-removal refactor.

Runs the real data_format_changer → df_cleaner → analytics chain on a
committed fixture raw report and asserts every hand-off file is
byte-identical to committed golden copies. Phases 2–4 replace pandas
module by module; these tests are the contract keeper — they must stay
green (or be *consciously* regenerated with a documented behavior
change) after every phase.

The fixture (tests/fixtures/m8/raw-data-report.txt, 10 ads) deliberately
covers the edge cases from the M8 plan §4:
- prices with thousands separators and decimal €/m² values
- floor values with the '/lifts' suffix
- Latvian diacritics in streets and raw keywords (Platība, Stāvs, €, m²)
- a >999-day-old pub date (ad aaa06)
- room count 5 (present in csv/analytics, excluded from the 1–4 room
  email body loop)
- the LAST ad (aaa10) has no Date line — data_format_changer's
  trim-to-min-length drops it from every output

Latent behaviors the goldens intentionally pin down (do NOT "fix" them
silently during the refactor — change goldens in a dedicated commit):
1. cleaned-sorted-df.csv is sorted by Price_in_eur as a STRING —
   lexicographic order (100000 < 21900 < 9500), not numeric.
2. The leading index column keeps the PRE-SORT row numbers.
3. (FIXED in M8 Phase 3) df_cleaner used to CRASH (KeyError: 0) on an
   empty pandas_df csv — the normal zero-new-ads day since M7 P1. It
   now writes a header-only cleaned csv + the empty email template.
"""
import os
import shutil
import sys
from datetime import datetime

import pytest

# container layout imports (app.wsmodules...)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "ws"))

from app.wsmodules import analytics, data_format_changer, df_cleaner

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "m8")
GOLDEN = os.path.join(FIXTURES, "golden")
CITY = "ogre"

OUTPUT_FILES = [
    "ogre-pandas_df.csv",
    "ogre-cleaned-sorted-df.csv",
    "ogre-basic_price_stats.txt",
    "ogre-email_body_txt_m4.txt",
    "ogre-email_body_add_dates_table.txt",
]


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def prepare_raw_report(tmp_path, source_name="raw-data-report.txt"):
    """Place the fixture as today's local raw report in tmp cwd layout."""
    os.makedirs(tmp_path / "data", exist_ok=True)
    os.makedirs(tmp_path / "local_lambda_raw_scraped_data", exist_ok=True)
    today = datetime.today().strftime("%Y-%m-%d")
    dest = tmp_path / "data" / f"{CITY}-raw-data-report-{today}.txt"
    shutil.copy(os.path.join(FIXTURES, source_name), dest)


@pytest.fixture
def chain_outputs(monkeypatch, tmp_path):
    """Run the full formatter → cleaner → analytics chain on the fixture."""
    monkeypatch.chdir(tmp_path)
    prepare_raw_report(tmp_path)
    data_format_changer.cloud_data_formater_main(CITY)
    df_cleaner.df_cleaner_main(CITY)
    analytics.analytics_main(CITY)
    return tmp_path


@pytest.mark.parametrize("output_file", OUTPUT_FILES)
def test_output_matches_golden(chain_outputs, output_file):
    produced = read(chain_outputs / output_file)
    golden = read(os.path.join(GOLDEN, output_file))
    assert produced == golden, (
        f"{output_file} drifted from its golden copy. If the change is"
        " intentional, regenerate tests/fixtures/m8/golden/ in a dedicated"
        " commit and document the behavior change."
    )


def test_missing_date_ad_is_trimmed_everywhere(chain_outputs):
    """Ad aaa10 has no Date line: list trimming drops it from all outputs."""
    for output_file in OUTPUT_FILES:
        assert "aaa10" not in read(chain_outputs / output_file)


def test_sort_is_lexicographic_not_numeric(chain_outputs):
    """Documents latent behavior #1: string sort on Price_in_eur.

    The cheapest ad (9500) sorts LAST and 100000 sorts FIRST. If Phase 3
    switches to a numeric sort, this test and the goldens must be
    updated together, deliberately.
    """
    lines = read(chain_outputs / "ogre-cleaned-sorted-df.csv").splitlines()
    data_rows = lines[1:]
    assert "aaa02" in data_rows[0]   # 100000 — lexicographically smallest
    assert "aaa01" in data_rows[-1]  # 9500  — lexicographically largest


def test_empty_raw_report_graceful_day(monkeypatch, tmp_path):
    """The zero-new-ads day (normal since M7 P1) must run the whole
    chain gracefully. Before M8 Phase 3, df_cleaner crashed here with
    KeyError inside the pandas column splits."""
    monkeypatch.chdir(tmp_path)
    os.makedirs(tmp_path / "data", exist_ok=True)
    os.makedirs(tmp_path / "local_lambda_raw_scraped_data", exist_ok=True)
    today = datetime.today().strftime("%Y-%m-%d")
    (tmp_path / "data" / f"{CITY}-raw-data-report-{today}.txt").write_text("")

    data_format_changer.cloud_data_formater_main(CITY)
    assert read(tmp_path / "ogre-pandas_df.csv") == (
        ",URL,Room_count,Size_sq_m,Floor,Street,Price,Pub_date\n"
    )

    df_cleaner.df_cleaner_main(CITY)
    assert read(tmp_path / "ogre-cleaned-sorted-df.csv") == (
        ",URL,Room_count,Floor,Street,Pub_date,Size_sqm,Price_in_eur,SQ_meter_price\n"
    )
    assert read(tmp_path / "ogre-email_body_txt_m4.txt") == (
        "No data was collected during last scraping job."
    )

    analytics.analytics_main(CITY)  # must also survive the empty csv
