"""Tests for scripts/fleet_watchdog.py (M6 monitoring Item 6)."""
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

WATCHDOG_PY = Path(__file__).parent.parent / "scripts" / "fleet_watchdog.py"
CITIES_YAML = Path(__file__).parent.parent / "config" / "cities.yaml"

spec = importlib.util.spec_from_file_location("fleet_watchdog", WATCHDOG_PY)
watchdog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watchdog)


def iso_hours_ago(hours):
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )


# --- parse_cities ---

def test_parse_cities_reads_repo_config():
    cities = watchdog.parse_cities(str(CITIES_YAML))
    assert cities == ["salaspils", "sigulda", "marupes_pag", "adazu_nov", "ogre", "jurmala"]


def test_parse_cities_missing_file_returns_empty():
    assert watchdog.parse_cities("/nonexistent/cities.yaml") == []


# --- container_state ---

def test_container_state_healthy():
    with patch.object(watchdog, "run_cmd", return_value=(0, "running|healthy", "")):
        assert watchdog.container_state("ogre-ws-1") == "healthy"


def test_container_state_no_healthcheck_uses_status():
    with patch.object(watchdog, "run_cmd", return_value=(0, "running|", "")):
        assert watchdog.container_state("ogre-backup-1") == "running"


def test_container_state_missing():
    with patch.object(watchdog, "run_cmd", return_value=(1, "", "No such object")):
        assert watchdog.container_state("ogre-ws-1") == "missing"


# --- check_last_run ---

def test_fresh_successful_run_no_problems():
    run = {"status": "success", "started_at": iso_hours_ago(5),
           "new_ads": 3, "removed_ads": 1}
    with patch.object(watchdog, "get_ws_status", return_value=run):
        summary, problems = watchdog.check_last_run("ogre", max_age_hours=26)
    assert problems == []
    assert "run:success" in summary


def test_failed_run_is_problem():
    run = {"status": "failed", "started_at": iso_hours_ago(5),
           "failed_stage": "db_worker", "error": "boom",
           "new_ads": None, "removed_ads": None}
    with patch.object(watchdog, "get_ws_status", return_value=run):
        _, problems = watchdog.check_last_run("ogre", max_age_hours=26)
    assert any("FAILED at stage db_worker" in p for p in problems)


def test_stale_run_is_problem():
    run = {"status": "success", "started_at": iso_hours_ago(50),
           "new_ads": 3, "removed_ads": 1}
    with patch.object(watchdog, "get_ws_status", return_value=run):
        _, problems = watchdog.check_last_run("ogre", max_age_hours=26)
    assert any("scheduler may be dead" in p for p in problems)


def test_unreachable_status_is_problem():
    with patch.object(watchdog, "get_ws_status", return_value=None):
        summary, problems = watchdog.check_last_run("ogre", max_age_hours=26)
    assert summary == "run:unknown"
    assert any("/status" in p for p in problems)


# --- get_db_row_counts ---

def test_db_row_counts_parses_psql_output():
    with patch.object(watchdog, "run_cmd", return_value=(0, "61|940", "")):
        assert watchdog.get_db_row_counts("ogre") == (61, 940)


def test_db_row_counts_error_returns_none():
    with patch.object(watchdog, "run_cmd", return_value=(1, "", "no container")):
        assert watchdog.get_db_row_counts("ogre") is None


# --- backup freshness ---

def test_backup_fresh_no_problem():
    newest = {"Key": "db-backups/x.sql.gz",
              "LastModified": iso_hours_ago(3) + "Z", "Size": 500 * 1024}
    with patch.object(watchdog, "run_cmd", return_value=(0, json.dumps(newest), "")):
        summary, problems = watchdog.check_backup("ogre", "prod", "eu-west-1", 26)
    assert problems == []
    assert summary.startswith("bkp:3h")


def test_backup_stale_is_problem():
    newest = {"Key": "db-backups/x.sql.gz",
              "LastModified": iso_hours_ago(50) + "Z", "Size": 500 * 1024}
    with patch.object(watchdog, "run_cmd", return_value=(0, json.dumps(newest), "")):
        _, problems = watchdog.check_backup("ogre", "prod", "eu-west-1", 26)
    assert any("50h old" in p for p in problems)


def test_backup_bucket_name_convention_for_underscore_city():
    with patch.object(watchdog, "run_cmd", return_value=(0, "null", "")) as mock_run:
        _, problems = watchdog.check_backup("marupes_pag", "prod", "eu-west-1", 26)
    bucket = mock_run.call_args[0][0][mock_run.call_args[0][0].index("--bucket") + 1]
    assert bucket == "sslv-prod-marupes-pag-db-backups"
    assert any("NO backups" in p for p in problems)


def test_backup_listing_error_is_problem():
    with patch.object(watchdog, "run_cmd", return_value=(1, "", "AccessDenied")):
        summary, problems = watchdog.check_backup("ogre", "prod", "eu-west-1", 26)
    assert summary == "bkp:unknown"
    assert any("could not list" in p for p in problems)


# --- main / email modes ---

def run_main(city_problems, email_mode):
    """Run main() with check_city + send_email mocked; returns (exit, email mock)."""
    email = MagicMock(return_value=True)
    line = "ogre         OK  | run:success 5h ago | LA:61 RA:940 | bkp:3h | ctr:4/4"
    with patch.object(watchdog, "parse_cities", return_value=["ogre"]), \
         patch.object(watchdog, "check_city", return_value=(line, city_problems)), \
         patch.object(watchdog, "send_email", email):
        exit_code = watchdog.main(["--email-mode", email_mode])
    return exit_code, email


def test_healthy_fleet_problems_mode_no_email_exit_zero():
    exit_code, email = run_main([], "problems")
    assert exit_code == 0
    email.assert_not_called()


def test_problem_fleet_problems_mode_sends_alert_exit_one():
    exit_code, email = run_main(["container ogre-ws-1 is missing"], "problems")
    assert exit_code == 1
    subject = email.call_args[0][0]
    assert "FLEET ALERT" in subject and "ogre" in subject
    assert "container ogre-ws-1 is missing" in email.call_args[0][1]


def test_healthy_fleet_always_mode_sends_digest():
    exit_code, email = run_main([], "always")
    assert exit_code == 0
    assert "all 1 cities OK" in email.call_args[0][0]


def test_problem_fleet_never_mode_no_email_exit_one():
    exit_code, email = run_main(["boom"], "never")
    assert exit_code == 1
    email.assert_not_called()
