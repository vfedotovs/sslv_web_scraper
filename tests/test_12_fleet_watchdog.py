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


# --- ntfy push (critical-monitoring P0) ---

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


def test_problem_fingerprint_ignores_changing_numbers():
    assert (watchdog.problem_fingerprint("last run is 27h old (> 26.0h)")
            == watchdog.problem_fingerprint("last run is 31h old (> 26.0h)"))


def test_ntfy_decision_healthy_fleet_nothing_to_send():
    assert watchdog.ntfy_decision({}, {}, 6, NOW) == (None, [])


def test_ntfy_decision_new_problem_is_alert():
    kind, _ = watchdog.ntfy_decision({"ogre": ["boom"]}, {}, 6, NOW)
    assert kind == "alert"


def test_ntfy_decision_unchanged_problem_is_silent_until_reminder():
    state = {"problems": {"ogre: last run is #h old": "ogre: last run is 27h old"},
             "last_sent": (NOW - timedelta(hours=1)).isoformat()}
    problems = {"ogre": ["last run is 28h old"]}
    assert watchdog.ntfy_decision(problems, state, 6, NOW) == (None, [])
    state["last_sent"] = (NOW - timedelta(hours=7)).isoformat()
    assert watchdog.ntfy_decision(problems, state, 6, NOW)[0] == "reminder"


def test_ntfy_decision_all_cleared_is_resolved():
    state = {"problems": {"ogre: boom": "ogre: boom"}, "last_sent": NOW.isoformat()}
    assert watchdog.ntfy_decision({}, state, 6, NOW) == ("resolved", ["ogre: boom"])


def test_ntfy_decision_partial_recovery_alerts_with_resolved_list():
    state = {"problems": {"ogre: boom": "ogre: boom", "sigulda: bang": "sigulda: bang"},
             "last_sent": NOW.isoformat()}
    kind, resolved = watchdog.ntfy_decision({"ogre": ["boom"]}, state, 6, NOW)
    assert kind == "alert" and resolved == ["sigulda: bang"]


def test_send_ntfy_posts_headers_and_body():
    response = MagicMock(status=200)
    response.__enter__.return_value = response
    with patch.object(watchdog.urllib.request, "urlopen", return_value=response) as urlopen:
        assert watchdog.send_ntfy("https://ntfy.sh/t", "Title", "body — ok",
                                  "urgent", ["rotating_light"], token="tk")
    request = urlopen.call_args[0][0]
    assert request.full_url == "https://ntfy.sh/t"
    assert request.data == "body — ok".encode("utf-8")
    assert request.get_header("Priority") == "urgent"
    assert request.get_header("Tags") == "rotating_light"
    assert request.get_header("Authorization") == "Bearer tk"


def test_send_ntfy_network_error_returns_false():
    with patch.object(watchdog.urllib.request, "urlopen", side_effect=OSError("down")):
        assert watchdog.send_ntfy("https://ntfy.sh/t", "T", "b") is False


def run_main_ntfy(city_problems, ntfy_mode, state_file, send_ok=True):
    """Run main() with checks + both channels mocked; returns the ntfy mock."""
    ntfy = MagicMock(return_value=send_ok)
    line = "ogre         OK  | run:success 5h ago | LA:61 RA:940 | bkp:3h | ctr:4/4"
    with patch.object(watchdog, "parse_cities", return_value=["ogre"]), \
         patch.object(watchdog, "check_city", return_value=(line, city_problems)), \
         patch.object(watchdog, "send_email", MagicMock(return_value=True)), \
         patch.object(watchdog, "send_ntfy", ntfy):
        watchdog.main(["--email-mode", "never", "--ntfy-mode", ntfy_mode,
                       "--ntfy-url", "https://ntfy.sh/t", "--env", "staging",
                       "--state-file", str(state_file)])
    return ntfy


def test_main_ntfy_alert_then_silent_then_resolved(tmp_path):
    state_file = tmp_path / "state.json"
    ntfy = run_main_ntfy(["newest backup is 30h old (> 26.0h): s3://b/k"], "problems", state_file)
    title, body, priority = ntfy.call_args[0][1:4]
    assert title == "[STAGING] SSLV ALERT: ogre"
    assert priority == "urgent"
    assert "newest backup is 30h old" in body

    ntfy = run_main_ntfy(["newest backup is 31h old (> 26.0h): s3://b/k"], "problems", state_file)
    ntfy.assert_not_called()

    ntfy = run_main_ntfy([], "problems", state_file)
    assert "RESOLVED" in ntfy.call_args[0][1]
    assert json.loads(state_file.read_text())["problems"] == {}


def test_main_ntfy_container_problem_is_high_priority(tmp_path):
    ntfy = run_main_ntfy(["container ogre-ts-1 is exited (expected healthy)"],
                         "problems", tmp_path / "s.json")
    assert ntfy.call_args[0][3] == "high"


def test_main_ntfy_failed_send_is_retried_next_run(tmp_path):
    state_file = tmp_path / "state.json"
    run_main_ntfy(["boom"], "problems", state_file, send_ok=False)
    assert not state_file.exists()
    ntfy = run_main_ntfy(["boom"], "problems", state_file)
    ntfy.assert_called_once()


def test_main_ntfy_always_mode_sends_low_priority_heartbeat(tmp_path):
    ntfy = run_main_ntfy([], "always", tmp_path / "s.json")
    title, _, priority = ntfy.call_args[0][1:4]
    assert "fleet OK" in title and priority == "low"


def test_main_ntfy_without_url_is_noop(tmp_path, monkeypatch):
    monkeypatch.delenv("NTFY_TOPIC_URL", raising=False)
    ntfy = MagicMock()
    with patch.object(watchdog, "parse_cities", return_value=["ogre"]), \
         patch.object(watchdog, "check_city", return_value=("line", ["boom"])), \
         patch.object(watchdog, "send_ntfy", ntfy):
        watchdog.main(["--email-mode", "never", "--state-file", str(tmp_path / "s.json")])
    ntfy.assert_not_called()
