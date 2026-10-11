"""Behaviour that the release-2.0.0 merge of main into the multi-city chain combined.

main's single-city fixes were carried into multi-city code; these tests pin the
combinations that neither side's own tests cover:
- email subject: per-city EMAIL_CITY_TITLE + RELEASE_VERSION + APP_ENV
  (the chain hard-coded "1.6.0" and repeated the title; main hard-coded "Ogre")
- report header: date, environment and total, titled per city (main: "Ogre")
- pipeline stages: gc + memory log after every stage (main's OOM fix), also
  when a stage fails
"""
import os
import sys
from datetime import datetime

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "ws"))
from app import main  # noqa: E402
from app.wsmodules import aws_mailer, df_cleaner  # noqa: E402

COLUMNS = ["URL", "Room_count", "Floor", "Size_sqm", "Price_in_eur",
           "SQ_meter_price", "Street", "Pub_date"]


# --- email subject ---

def test_subject_uses_city_title_once_with_release_and_env(monkeypatch):
    monkeypatch.setattr(aws_mailer, "EMAIL_CITY_TITLE", "Jūrmala Apartments for sale")
    monkeypatch.setenv("RELEASE_VERSION", "v2.0.0")
    monkeypatch.setenv("APP_ENV", "staging")
    subject = aws_mailer.gen_subject_title()
    assert subject.startswith("Jūrmala Apartments for sale from ss.lv web_scraper_v2.0.0_")
    assert subject.endswith(" [staging]")
    assert subject.count("Apartments for sale") == 1
    assert "1.6.0" not in subject


def test_subject_without_version_env_says_unknown(monkeypatch):
    monkeypatch.setattr(aws_mailer, "EMAIL_CITY_TITLE", "Ogre City Apartments for sale")
    monkeypatch.delenv("RELEASE_VERSION", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    assert "web_scraper_unknown_" in aws_mailer.gen_subject_title()
    assert aws_mailer.gen_subject_title().endswith(" [local]")


# --- report header ---

def report_lines(tmp_path, df, city=None):
    out = tmp_path / "email_body.txt"
    df_cleaner.create_email_body(df, str(out), city)
    return out.read_text().splitlines()


def test_report_header_is_titled_per_city(tmp_path, monkeypatch):
    monkeypatch.setenv("EMAIL_CITY_TITLE", "Mārupes pagasts Apartments for sale")
    monkeypatch.setenv("APP_ENV", "staging")
    today = datetime.today().strftime("%d.%m.%Y")
    row = ["https://ss.lv/a.html", 2, "2/5", 50.0, 100000, 2000.0, "Liepu iela 1", "01.10.2026"]
    lines = report_lines(tmp_path, pd.DataFrame([row], columns=COLUMNS), "marupes_pag")
    assert lines[0] == f"=== Mārupes pagasts Apartments for sale — {today} [staging] ==="
    assert lines[1] == "Total active listings: 1"
    assert "Ogre" not in lines[0]


def test_report_header_falls_back_to_city_name(tmp_path, monkeypatch):
    monkeypatch.delenv("EMAIL_CITY_TITLE", raising=False)
    lines = report_lines(tmp_path, pd.DataFrame(columns=COLUMNS), "jurmala")
    assert lines[0].startswith("=== ")
    assert "Apartment Report" in lines[0] and "Ogre" not in lines[0]
    assert lines[1] == "Total active listings: 0"


def test_listing_rows_carry_eur_labels_and_new_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("EMAIL_CITY_TITLE", "Ogre City Apartments for sale")
    today = datetime.today().strftime("%d.%m.%Y")
    rows = [["https://ss.lv/new.html", 1, "1/5", 30.0, 40000, 1333.0, "Rīgas iela 1", today],
            ["https://ss.lv/old.html", 1, "2/5", 31.0, 41000, 1322.0, "Rīgas iela 2", "01.01.2026"]]
    body = "\n".join(report_lines(tmp_path, pd.DataFrame(rows, columns=COLUMNS), "ogre"))
    assert "40000 EUR" in body and "1333.0 EUR" in body
    assert "https://ss.lv/new.html [NEW]" in body
    assert "https://ss.lv/old.html [NEW]" not in body


def test_street_abbreviations_are_expanded():
    assert df_cleaner.normalise_street("Brīvības pr. 12") == "Brīvības prospekts 12"
    assert df_cleaner.normalise_street("Skolas iel. 3") == "Skolas iela 3"
    assert df_cleaner.normalise_street(None) is None


# --- pipeline stages ---

def test_every_stage_is_followed_by_gc_and_memory_log(monkeypatch):
    events = []
    monkeypatch.setattr(main.gc, "collect", lambda: events.append("gc"))
    monkeypatch.setattr(main, "log_memory_usage", lambda: events.append("mem"))
    main.run_pipeline_stages([("a", lambda: events.append("a")),
                              ("b", lambda: events.append("b"))])
    assert events == ["a", "gc", "mem", "b", "gc", "mem"]


def test_failed_stage_still_frees_memory_then_raises(monkeypatch):
    events = []
    monkeypatch.setattr(main.gc, "collect", lambda: events.append("gc"))
    monkeypatch.setattr(main, "log_memory_usage", lambda: events.append("mem"))

    def boom():
        raise RuntimeError("scrape failed")

    with pytest.raises(main.PipelineStageError) as err:
        main.run_pipeline_stages([("web_scraper", boom), ("never", lambda: events.append("x"))])
    assert err.value.stage == "web_scraper"
    assert events == ["gc", "mem"]
