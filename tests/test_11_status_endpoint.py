"""Tests for the ws /status endpoint (M6 monitoring Item 5)."""
import os
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

# main.py imports "app.wsmodules..." (container layout), so make src/ws
# importable the same way the ws container does.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "ws"))

from fastapi.testclient import TestClient

from app import main
from app.wsmodules import scrape_runs

client = TestClient(main.app, raise_server_exceptions=False)


def make_run(**overrides):
    run = {
        "run_id": 1, "city": "ogre", "status": "success",
        "started_at": datetime(2026, 7, 12, 0, 41, 0),
        "finished_at": datetime(2026, 7, 12, 0, 43, 30),
        "failed_stage": None, "error": None,
        "pages_fetched": 2, "urls_discovered": 63, "new_ads": 3,
        "still_listed_ads": 58, "removed_ads": 2,
        "listed_table_rows": 61, "removed_table_rows": 940,
    }
    run.update(overrides)
    return run


def test_status_returns_last_run_per_city():
    runs = [
        make_run(),
        make_run(run_id=2, city="sigulda", status="failed",
                 failed_stage="db_worker", error="conn refused",
                 finished_at=datetime(2026, 7, 12, 0, 42, 0)),
    ]
    with patch.object(main.scrape_runs, "ensure_scrape_runs_table"), \
         patch.object(main.scrape_runs, "get_last_run_per_city", return_value=runs):
        response = client.get("/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert set(data["cities"]) == {"ogre", "sigulda"}
    ogre = data["cities"]["ogre"]
    assert ogre["status"] == "success"
    assert ogre["started_at"] == "2026-07-12T00:41:00"
    assert ogre["duration_seconds"] == 150
    assert ogre["new_ads"] == 3
    sigulda = data["cities"]["sigulda"]
    assert sigulda["status"] == "failed"
    assert sigulda["failed_stage"] == "db_worker"
    assert sigulda["error"] == "conn refused"


def test_status_empty_table_returns_no_cities():
    with patch.object(main.scrape_runs, "ensure_scrape_runs_table"), \
         patch.object(main.scrape_runs, "get_last_run_per_city", return_value=[]):
        response = client.get("/status")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "cities": {}}


def test_status_running_run_has_null_duration():
    runs = [make_run(status="running", finished_at=None)]
    with patch.object(main.scrape_runs, "ensure_scrape_runs_table"), \
         patch.object(main.scrape_runs, "get_last_run_per_city", return_value=runs):
        response = client.get("/status")
    ogre = response.json()["cities"]["ogre"]
    assert ogre["status"] == "running"
    assert ogre["finished_at"] is None
    assert ogre["duration_seconds"] is None


def test_status_db_unavailable_returns_503():
    with patch.object(main.scrape_runs, "ensure_scrape_runs_table",
                      side_effect=Exception("connection refused")):
        response = client.get("/status")
    assert response.status_code == 503
    assert "scrape_runs table unavailable" in response.json()["detail"]


def test_get_last_run_per_city_uses_distinct_on():
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    conn = MagicMock()
    conn.cursor.return_value = cursor
    with patch.object(scrape_runs, "_connect", return_value=conn):
        assert scrape_runs.get_last_run_per_city() == []
    sql = cursor.execute.call_args[0][0]
    assert "DISTINCT ON (city)" in sql
    assert "ORDER BY city, started_at DESC" in sql
