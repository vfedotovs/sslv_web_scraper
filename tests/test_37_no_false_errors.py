"""A clean nightly run must log no ERROR lines (review item 7).

Every city logged three or four ERRORs each night that were not errors:
- aws_mailer.remove_tmp_files: "No such file or directory" for Mailer_report.txt,
  1_rooms_tmp.txt and mrv2.txt (no longer created), and for ogre's raw report,
  which the scraper names "Ogre-raw-data-report.txt" while the cleanup list had
  "ogre-raw-data-report.txt" (so ogre's report was never removed).
- analytics.split_dataframe_by_column: "Loaded DataFrame is empty" on any night
  without new ads.
They hid real errors in the log bundle's "Recent errors" and in alerting.
"""
import logging
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "ws"))
from app.wsmodules import analytics, aws_mailer  # noqa: E402

LEGACY = {"Mailer_report.txt", "1_rooms_tmp.txt", "mrv2.txt"}


def test_cleanup_list_has_only_files_the_pipeline_writes():
    for city in ("jurmala", "ogre", None):
        assert not LEGACY & set(aws_mailer.get_data_files_to_remove(city))


def test_cleanup_uses_the_scrapers_raw_report_name():
    assert "Ogre-raw-data-report.txt" in aws_mailer.get_data_files_to_remove("ogre")
    assert "ogre-raw-data-report.txt" not in aws_mailer.get_data_files_to_remove("ogre")
    assert "jurmala-raw-data-report.txt" in aws_mailer.get_data_files_to_remove("jurmala")


def test_missing_files_are_not_errors(tmp_path, monkeypatch, caplog):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "present.txt").write_text("x")
    with caplog.at_level(logging.DEBUG, logger="aws_mailer"):
        aws_mailer.remove_tmp_files(["present.txt", "already-gone.txt"])
    assert not (tmp_path / "present.txt").exists()
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert "Removed 1 of 2 temp files" in caplog.text


def test_a_real_removal_failure_is_still_an_error(tmp_path, monkeypatch, caplog):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a-directory").mkdir()          # os.remove() refuses directories
    with caplog.at_level(logging.INFO, logger="aws_mailer"):
        aws_mailer.remove_tmp_files(["a-directory"])
    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1 and errors[0].startswith("Could not remove a-directory")


def test_empty_frame_is_not_an_error(caplog):
    with caplog.at_level(logging.INFO, logger="analytics"):
        result = analytics.split_dataframe_by_column(pd.DataFrame(columns=["Room_count"]),
                                                     "Room_count")
    assert result is None
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert "no new ads" in caplog.text
