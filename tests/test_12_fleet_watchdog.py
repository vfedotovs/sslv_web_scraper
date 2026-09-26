"""Tests for scripts/fleet_watchdog.py (M6 monitoring Item 6)."""
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

WATCHDOG_PY = Path(__file__).parent.parent / "scripts" / "fleet_watchdog.py"
CITIES_YAML = Path(__file__).parent.parent / "config" / "cities.yaml"

spec = importlib.util.spec_from_file_location("fleet_watchdog", WATCHDOG_PY)
watchdog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watchdog)
REAL_GET_LAST_SUCCESS_AGE_HOURS = watchdog.get_last_success_age_hours


@pytest.fixture(autouse=True)
def isolated_watchdog_state(tmp_path, monkeypatch):
    """Never touch the real state file, host checks or ntfy/heartbeat env."""
    monkeypatch.setenv("WATCHDOG_STATE_FILE", str(tmp_path / "default-state.json"))
    for var in ("NTFY_TOPIC_URL", "NTFY_TOKEN", "HEARTBEAT_PING_URL",
                "MIN_BACKUP_SIZE_KB", "BACKUP_MIN_BYTES_PER_ROW",
                "BACKUP_SHRINK_RATIO", "BACKUP_HISTORY_N", "S3_REGION", "AWS_REGION"):
        monkeypatch.delenv(var, raising=False)
    # check_last_run's psql lookup: default to a healthy recent success.
    monkeypatch.setattr(watchdog, "get_last_success_age_hours", lambda city: 5.0)


HOST_OK = ("host         OK  | mem:415/1843MiB avail swap:0/0MiB | oom:0 | disk:58% used | ctr:4/4", [])


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

def listing(*objects):
    """aws s3api output for check_backup: (hours_ago, size) pairs, oldest first."""
    return json.dumps([
        {"Key": f"db-backups/{i}.sql.gz", "LastModified": iso_hours_ago(hours) + "Z",
         "Size": size}
        for i, (hours, size) in enumerate(objects)
    ])


def test_backup_fresh_no_problem():
    with patch.object(watchdog, "run_cmd", return_value=(0, listing((3, 500 * 1024)), "")):
        summary, problems = watchdog.check_backup("ogre", "prod", "eu-west-1", 26)
    assert problems == []
    assert summary.startswith("bkp:3h")


def test_backup_stale_is_problem():
    with patch.object(watchdog, "run_cmd", return_value=(0, listing((50, 500 * 1024)), "")):
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
         patch.object(watchdog, "check_host", return_value=HOST_OK), \
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
         patch.object(watchdog, "check_host", return_value=HOST_OK), \
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
    assert "problems" not in json.loads(state_file.read_text())
    ntfy = run_main_ntfy(["boom"], "problems", state_file)
    ntfy.assert_called_once()


def test_main_ntfy_always_mode_sends_low_priority_heartbeat(tmp_path):
    ntfy = run_main_ntfy([], "always", tmp_path / "s.json")
    title, _, priority = ntfy.call_args[0][1:4]
    assert "fleet OK" in title and priority == "low"


def test_main_ntfy_without_url_is_noop(tmp_path):
    ntfy = MagicMock()
    with patch.object(watchdog, "parse_cities", return_value=["ogre"]), \
         patch.object(watchdog, "check_city", return_value=("line", ["boom"])), \
         patch.object(watchdog, "check_host", return_value=HOST_OK), \
         patch.object(watchdog, "send_ntfy", ntfy):
        watchdog.main(["--email-mode", "never", "--state-file", str(tmp_path / "s.json")])
    ntfy.assert_not_called()


# --- P1 host / fleet checks ---

MEMINFO = """MemTotal:        1887436 kB
MemFree:           91136 kB
MemAvailable:     {avail} kB
SwapTotal:        {swap} kB
SwapFree:         {swap} kB
"""


def write_meminfo(tmp_path, avail_kb, swap_kb=0):
    path = tmp_path / "meminfo"
    path.write_text(MEMINFO.format(avail=avail_kb, swap=swap_kb))
    return str(path)


def test_read_meminfo_parses_mib(tmp_path):
    info = watchdog.read_meminfo(write_meminfo(tmp_path, 424960))
    assert info == {"MemTotal": 1843, "MemAvailable": 415, "SwapTotal": 0, "SwapFree": 0}


def test_read_meminfo_missing_returns_none():
    assert watchdog.read_meminfo("/nonexistent/meminfo") is None


def test_memory_uses_available_not_free(tmp_path):
    info = watchdog.read_meminfo(write_meminfo(tmp_path, 424960))  # 415 MiB
    with patch.object(watchdog, "read_meminfo", return_value=info):
        summary, problems = watchdog.check_memory(150)
    assert problems == [] and "mem:415/1843MiB" in summary


def test_memory_low_is_high_priority_problem(tmp_path):
    info = watchdog.read_meminfo(write_meminfo(tmp_path, 102400))  # 100 MiB
    with patch.object(watchdog, "read_meminfo", return_value=info):
        _, problems = watchdog.check_memory(150)
    assert problems[0].startswith("memory low: 100 MiB available")
    assert not problems[0].startswith(watchdog.URGENT_PROBLEM_PREFIXES)


def test_oom_kills_parsed_from_kernel_log():
    log = ("Out of memory: Killed process 4242 (python) total-vm:1000kB\n"
           "oom_reaper: reaped process 4242 (python)\n"
           "Out of memory: Killed process 777 (postgres) total-vm:1000kB\n")
    with patch.object(watchdog, "run_cmd", return_value=(0, log, "")):
        summary, problems = watchdog.check_oom(0)
    assert summary == "oom:2"
    assert problems == ["OOM kill: 2 process(es) killed by the kernel since last"
                        " check (postgres, python)"]
    assert problems[0].startswith(watchdog.URGENT_PROBLEM_PREFIXES)


def test_oom_unreadable_journal_is_not_a_problem():
    with patch.object(watchdog, "run_cmd", return_value=(1, "", "no journalctl")):
        assert watchdog.check_oom(0) == ("oom:?", [])


def test_oom_journal_without_permission_is_unknown():
    hint = ("Hint: You are currently not seeing messages from other users and the"
            " system.\n      Users in groups 'adm', 'systemd-journal', 'wheel' can"
            " see all messages.")
    with patch.object(watchdog, "run_cmd", return_value=(0, "", hint)):
        assert watchdog.check_oom(0) == ("oom:?", [])


def disk(total_gib, free_gib):
    return MagicMock(total=total_gib * 2**30, free=free_gib * 2**30)


def test_disk_thresholds():
    with patch.object(watchdog.shutil, "disk_usage", return_value=disk(16, 6.9)):
        assert watchdog.check_disk("/", 20, 10)[1] == []
    with patch.object(watchdog.shutil, "disk_usage", return_value=disk(16, 2.4)):
        assert watchdog.check_disk("/", 20, 10)[1][0].startswith("disk low: 15% free")
    with patch.object(watchdog.shutil, "disk_usage", return_value=disk(16, 1)):
        problem = watchdog.check_disk("/", 20, 10)[1][0]
    assert problem.startswith("disk critical: 6% free")
    assert problem.startswith(watchdog.URGENT_PROBLEM_PREFIXES)


def fake_docker(ps_out, inspect_out):
    def run_cmd(args, timeout=60):
        return (0, ps_out if args[1] == "ps" else inspect_out, "")
    return run_cmd


EXPECTED_OGRE = ["ogre-db-1", "ogre-ws-1", "ogre-ts-1", "ogre-backup-1"]


def test_fleet_containers_all_expected_running_first_run_sets_baseline():
    ps = "\n".join(f"{n}|running" for n in EXPECTED_OGRE)
    inspect = "\n".join(f"/{n}|id-{n}|0" for n in EXPECTED_OGRE)
    state = {}
    with patch.object(watchdog, "run_cmd", side_effect=fake_docker(ps, inspect)):
        summary, problems = watchdog.check_fleet_containers(["ogre"], state)
    assert summary == "ctr:4/4" and problems == []
    assert state["restart_counts"]["ogre-ws-1"] == ["id-ogre-ws-1", 0]


def test_fleet_containers_flags_leftover_city_and_restart():
    ps = "\n".join(f"{n}|running" for n in EXPECTED_OGRE) + "\nriga-ws-1|running"
    inspect = "\n".join(
        f"/{n}|id-{n}|{2 if n == 'ogre-ws-1' else 0}" for n in EXPECTED_OGRE)
    state = {"restart_counts": {n: [f"id-{n}", 0] for n in EXPECTED_OGRE}}
    with patch.object(watchdog, "run_cmd", side_effect=fake_docker(ps, inspect)):
        _, problems = watchdog.check_fleet_containers(["ogre"], state)
    assert "unexpected containers running (not in cities.yaml): riga-ws-1" in problems
    assert ("container ogre-ws-1 restarted 2 time(s) since last check (total 2)"
            in problems)


def test_fleet_containers_recreated_container_is_not_a_restart():
    ps = "\n".join(f"{n}|running" for n in EXPECTED_OGRE)
    inspect = "\n".join(f"/{n}|new-id|3" for n in EXPECTED_OGRE)
    state = {"restart_counts": {n: [f"old-id-{n}", 0] for n in EXPECTED_OGRE}}
    with patch.object(watchdog, "run_cmd", side_effect=fake_docker(ps, inspect)):
        _, problems = watchdog.check_fleet_containers(["ogre"], state)
    assert problems == []


def test_zero_urls_on_successful_run_is_city_problem():
    run = {"status": "success", "started_at": iso_hours_ago(5), "urls_discovered": 0}
    with patch.object(watchdog, "get_ws_status", return_value=run):
        _, problems = watchdog.check_last_run("ogre", max_age_hours=26)
    assert problems[0].startswith(watchdog.ZERO_URLS_PROBLEM)
    assert not problems[0].startswith(watchdog.URGENT_PROBLEM_PREFIXES)


def test_urls_not_recorded_is_not_a_problem():
    run = {"status": "success", "started_at": iso_hours_ago(5), "urls_discovered": None}
    with patch.object(watchdog, "get_ws_status", return_value=run):
        assert watchdog.check_last_run("ogre", max_age_hours=26)[1] == []


def test_scraper_collapse_needs_min_cities():
    zero = f"{watchdog.ZERO_URLS_PROBLEM} in last run"
    two = {"ogre": [zero], "sigulda": [zero], "jurmala": ["other"]}
    assert watchdog.check_scraper_collapse(two, ["ogre", "sigulda", "jurmala"], 3) == []
    three = dict(two, jurmala=[zero])
    problem = watchdog.check_scraper_collapse(three, ["ogre", "sigulda", "jurmala"], 3)[0]
    assert problem.startswith("scraper collapse: 3/3 cities discovered 0 URLs")
    assert problem.startswith(watchdog.URGENT_PROBLEM_PREFIXES)


def test_check_host_uses_last_check_as_oom_window():
    args = MagicMock(min_mem_available_mib=150, disk_warn_free_pct=20,
                     disk_crit_free_pct=10, first_run_lookback_min=15)
    with patch.object(watchdog, "check_memory", return_value=("mem", [])), \
         patch.object(watchdog, "check_oom", return_value=("oom:1", ["OOM kill: x"])) as oom, \
         patch.object(watchdog, "check_disk", return_value=("disk", [])), \
         patch.object(watchdog, "check_fleet_containers", return_value=("ctr", [])):
        line, problems = watchdog.check_host(["ogre"], args, {"last_check_epoch": 1000}, 5000)
        oom.assert_called_with(1000)
        watchdog.check_host(["ogre"], args, {}, 5000)
        oom.assert_called_with(5000 - 15 * 60)
    assert line.startswith("host         BAD") and problems == ["OOM kill: x"]


def run_main_full(city_problems, host, mode, state_file, extra=()):
    ntfy, ping = MagicMock(return_value=True), MagicMock(return_value=True)
    checks = {c: ("line", p) for c, p in city_problems.items()}
    with patch.object(watchdog, "parse_cities", return_value=list(city_problems)), \
         patch.object(watchdog, "check_city", side_effect=lambda c, a: checks[c]), \
         patch.object(watchdog, "check_host", return_value=host), \
         patch.object(watchdog, "send_ntfy", ntfy), \
         patch.object(watchdog, "ping_heartbeat", ping):
        code = watchdog.main(["--email-mode", "never", "--ntfy-mode", mode,
                              "--ntfy-url", "https://ntfy.sh/t",
                              "--state-file", str(state_file), *extra])
    return code, ntfy, ping


def test_main_host_and_collapse_problems_are_pushed(tmp_path):
    zero = [f"{watchdog.ZERO_URLS_PROBLEM} in last run"]
    cities = {"ogre": zero, "sigulda": zero, "jurmala": zero}
    host = ("host BAD", ["disk critical: 5% free on /"])
    code, ntfy, _ = run_main_full(cities, host, "problems", tmp_path / "s.json")
    title, body, priority = ntfy.call_args[0][1:4]
    assert code == 1 and priority == "urgent"
    assert "fleet" in title and "host" in title
    assert "- fleet: scraper collapse: 3/3 cities" in body
    assert "- host: disk critical" in body


def test_main_persists_baseline_and_pings_heartbeat(tmp_path):
    state_file = tmp_path / "s.json"
    _, _, ping = run_main_full({"ogre": []}, HOST_OK, "problems", state_file,
                               ["--heartbeat-ping-url", "https://hc-ping.com/x"])
    assert "last_check_epoch" in json.loads(state_file.read_text())
    ping.assert_called_once_with("https://hc-ping.com/x")


def test_main_never_mode_is_read_only(tmp_path):
    state_file = tmp_path / "s.json"
    _, ntfy, ping = run_main_full({"ogre": []}, HOST_OK, "never", state_file,
                                  ["--heartbeat-ping-url", "https://hc-ping.com/x"])
    assert not state_file.exists()
    ntfy.assert_not_called()
    ping.assert_not_called()


# --- P2: stuck runs, last-success age, backup size ---

def test_last_success_age_parses_psql_and_filters_city():
    with patch.object(watchdog, "run_cmd", return_value=(0, "30.5\n", "")) as run:
        assert REAL_GET_LAST_SUCCESS_AGE_HOURS("marupes_pag") == 30.5
    sql = run.call_args[0][0][-1]
    assert "status = 'success'" in sql and "city = 'marupes_pag'" in sql
    assert run.call_args[0][0][2] == "marupes_pag-db-1"


def test_last_success_age_no_rows_and_errors():
    with patch.object(watchdog, "run_cmd", return_value=(0, "\n", "")):
        assert REAL_GET_LAST_SUCCESS_AGE_HOURS("ogre") == "none"
    with patch.object(watchdog, "run_cmd", return_value=(1, "", "no container")):
        assert REAL_GET_LAST_SUCCESS_AGE_HOURS("ogre") is None
    with patch.object(watchdog, "run_cmd") as run:
        assert REAL_GET_LAST_SUCCESS_AGE_HOURS("ogre'; DROP TABLE x;--") is None
    run.assert_not_called()


def test_stuck_running_run_is_urgent_problem():
    run = {"status": "running", "started_at": iso_hours_ago(4)}
    with patch.object(watchdog, "get_ws_status", return_value=run):
        _, problems = watchdog.check_last_run("ogre", max_age_hours=26, max_running_hours=3)
    assert problems == ["last run stuck in 'running' for 4h (> 3h) — ws likely died mid-pipeline"]
    assert problems[0].startswith(watchdog.URGENT_PROBLEM_PREFIXES)


def test_recent_running_run_is_not_a_problem():
    run = {"status": "running", "started_at": iso_hours_ago(1)}
    with patch.object(watchdog, "get_ws_status", return_value=run):
        assert watchdog.check_last_run("ogre", 26, 3)[1] == []


def test_failing_runs_with_old_success_alert_on_success_age(monkeypatch):
    monkeypatch.setattr(watchdog, "get_last_success_age_hours", lambda city: 50.0)
    run = {"status": "failed", "started_at": iso_hours_ago(2),
           "failed_stage": "web_scraper", "error": "403"}
    with patch.object(watchdog, "get_ws_status", return_value=run):
        summary, problems = watchdog.check_last_run("ogre", 26)
    assert "ok:50h ago" in summary
    assert "last successful run is 50h old (> 26h)" in problems
    assert problems[-1].startswith(watchdog.URGENT_PROBLEM_PREFIXES)


def test_stale_scheduler_does_not_double_report_success_age(monkeypatch):
    monkeypatch.setattr(watchdog, "get_last_success_age_hours", lambda city: 50.0)
    run = {"status": "success", "started_at": iso_hours_ago(50)}
    with patch.object(watchdog, "get_ws_status", return_value=run):
        _, problems = watchdog.check_last_run("ogre", 26)
    assert len(problems) == 1 and "scheduler may be dead" in problems[0]


def test_no_success_ever_is_problem(monkeypatch):
    monkeypatch.setattr(watchdog, "get_last_success_age_hours", lambda city: "none")
    run = {"status": "failed", "started_at": iso_hours_ago(2)}
    with patch.object(watchdog, "get_ws_status", return_value=run):
        summary, problems = watchdog.check_last_run("ogre", 26)
    assert "ok:never" in summary
    assert "last successful run: none recorded in scrape_runs" in problems


def test_unreadable_success_age_is_not_extra_problem(monkeypatch):
    monkeypatch.setattr(watchdog, "get_last_success_age_hours", lambda city: None)
    run = {"status": "success", "started_at": iso_hours_ago(5)}
    with patch.object(watchdog, "get_ws_status", return_value=run):
        assert watchdog.check_last_run("ogre", 26)[1] == []


def test_backup_below_hard_floor_is_urgent_problem():
    with patch.object(watchdog, "run_cmd", return_value=(0, listing((3, 600)), "")):
        _, problems = watchdog.check_backup("ogre", "prod", "eu-west-1", 26, rows=(0, 0))
    assert len(problems) == 1  # not also "does not contain the data"
    assert problems[0].startswith("newest backup is only 0.6 KB (< 1 KB hard floor)")
    assert problems[0].startswith(watchdog.URGENT_PROBLEM_PREFIXES)


def test_backup_history_query_asks_for_newest_plus_previous():
    with patch.object(watchdog, "run_cmd", return_value=(0, listing((3, 3000)), "")) as mock_run:
        watchdog.check_backup("ogre", "prod", "eu-west-1", 26, history=7)
    cmd = mock_run.call_args[0][0]
    assert cmd[cmd.index("--query") + 1].startswith("sort_by(Contents, &LastModified)[-8:]")


def test_small_db_small_dump_is_ok():
    """The 2026-09-26 staging fleet: 58 rows in 2.9 KB, 334 rows in 8 KB."""
    for rows, size in [((49, 9), 2956), ((318, 16), 8 * 1024)]:
        history = listing((74, size - 200), (50, size - 150), (26, size - 70), (2, size))
        with patch.object(watchdog, "run_cmd", return_value=(0, history, "")):
            _, problems = watchdog.check_backup("ogre", "staging", "eu-west-1", 26, rows=rows)
        assert problems == []


def test_large_db_small_dump_does_not_contain_the_data():
    """2026-09-21: a 2.6 KB staging dump landed in a bucket for a DB with
    thousands of rows."""
    with patch.object(watchdog, "run_cmd", return_value=(0, listing((3, 2640)), "")):
        _, problems = watchdog.check_backup("ogre", "prod", "eu-west-1", 26, rows=(900, 4100))
    assert len(problems) == 1
    assert problems[0].startswith("newest backup is 2.6 KB for 5000 DB rows"
                                  " (expected >= 25.4 KB at 5 B/row)")
    assert "does not contain the data" in problems[0]


def test_unknown_row_count_skips_the_expected_size_check():
    with patch.object(watchdog, "run_cmd", return_value=(0, listing((3, 2640)), "")):
        assert watchdog.check_backup("ogre", "prod", "eu-west-1", 26, rows=None)[1] == []


def test_backup_shrink_against_median_is_problem():
    history = listing((98, 90 * 1024), (74, 100 * 1024), (50, 95 * 1024), (26, 400 * 1024),
                      (2, 30 * 1024))
    with patch.object(watchdog, "run_cmd", return_value=(0, history, "")):
        _, problems = watchdog.check_backup("ogre", "prod", "eu-west-1", 26)
    assert problems == ["newest backup shrank to 30.0 KB from a median of 97.5 KB over the"
                        " previous 4 backups (< 50%): s3://sslv-prod-ogre-db-backups/"
                        "db-backups/4.sql.gz"]


def test_backup_shrink_needs_three_previous_backups():
    history = listing((50, 100 * 1024), (26, 100 * 1024), (2, 30 * 1024))
    with patch.object(watchdog, "run_cmd", return_value=(0, history, "")):
        assert watchdog.check_backup("ogre", "prod", "eu-west-1", 26)[1] == []


def test_check_city_passes_db_rows_to_backup_check():
    healthy = dict(watchdog.CITY_SERVICES)
    with patch.object(watchdog, "check_containers", return_value=(healthy, [])), \
         patch.object(watchdog, "check_last_run", return_value=("run:success", [])), \
         patch.object(watchdog, "get_db_row_counts", return_value=(49, 9)), \
         patch.object(watchdog, "check_backup", return_value=("bkp:3h", [])) as backup:
        watchdog.check_city("ogre", city_args(backup_min_bytes_per_row=7))
    assert backup.call_args.kwargs["rows"] == (49, 9)
    assert backup.call_args.kwargs["min_bytes_per_row"] == 7


def test_report_header_names_env_and_thresholds(capsys):
    with patch.object(watchdog, "parse_cities", return_value=["ogre"]), \
         patch.object(watchdog, "check_city", return_value=("line", [])), \
         patch.object(watchdog, "check_host", return_value=HOST_OK):
        watchdog.main(["--env", "staging", "--email-mode", "never", "--ntfy-mode", "never"])
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("SSLV fleet status [staging] — ")
    assert out[1] == ("thresholds: run/backup age 26h/26h, backup floor 1 KB + 5 B/row,"
                      " shrink < 50% of median")


def test_backup_thresholds_default_from_env(monkeypatch):
    monkeypatch.setenv("BACKUP_MIN_BYTES_PER_ROW", "9")
    monkeypatch.setenv("BACKUP_SHRINK_RATIO", "0.3")
    monkeypatch.setenv("BACKUP_HISTORY_N", "4")
    seen = {}
    with patch.object(watchdog, "parse_cities", return_value=["ogre"]), \
         patch.object(watchdog, "check_city",
                      side_effect=lambda c, a: seen.update(vars(a)) or ("l", [])), \
         patch.object(watchdog, "check_host", return_value=HOST_OK):
        watchdog.main(["--email-mode", "never", "--ntfy-mode", "never"])
    assert (seen["backup_min_bytes_per_row"], seen["backup_shrink_ratio"],
            seen["backup_history"]) == (9, 0.3, 4)
    assert seen["min_backup_size_kb"] == 1


def test_min_backup_size_defaults_from_env(monkeypatch):
    monkeypatch.setenv("MIN_BACKUP_SIZE_KB", "1")
    seen = {}
    with patch.object(watchdog, "parse_cities", return_value=["ogre"]), \
         patch.object(watchdog, "check_city",
                      side_effect=lambda c, a: seen.update(kb=a.min_backup_size_kb) or ("l", [])), \
         patch.object(watchdog, "check_host", return_value=HOST_OK):
        watchdog.main(["--email-mode", "never", "--ntfy-mode", "never"])
    assert seen["kb"] == 1


# --- /status: "never ran" is not "unreachable" ---

def test_get_ws_status_returns_sentinel_when_city_has_no_row():
    body = json.dumps({"status": "ok", "cities": {}})
    with patch.object(watchdog, "run_cmd", return_value=(0, body, "")):
        assert watchdog.get_ws_status("ogre") is watchdog.NO_RUN_RECORDED


def test_get_ws_status_returns_run_for_known_city():
    run = {"status": "success", "started_at": iso_hours_ago(2)}
    body = json.dumps({"status": "ok", "cities": {"ogre": run}})
    with patch.object(watchdog, "run_cmd", return_value=(0, body, "")):
        assert watchdog.get_ws_status("ogre") == run


@pytest.mark.parametrize("result", [
    (1, "", "Error: No such container: ogre-ws-1"),  # exec/ws failure
    (0, "<html>503</html>", ""),                     # unparseable body
    (0, json.dumps({"detail": "boom"}), ""),         # no cities key
])
def test_get_ws_status_unreadable_returns_none(result):
    with patch.object(watchdog, "run_cmd", return_value=result):
        assert watchdog.get_ws_status("ogre") is None


def test_never_ran_city_is_not_blamed_on_the_endpoint(monkeypatch):
    monkeypatch.setattr(watchdog, "get_last_success_age_hours", lambda city: "none")
    with patch.object(watchdog, "get_ws_status", return_value=watchdog.NO_RUN_RECORDED):
        summary, problems = watchdog.check_last_run("ogre", max_age_hours=26)
    assert summary.startswith("run:none")
    assert "ok:never" in summary
    assert len(problems) == 1  # not also "last successful run: none recorded"
    assert "no run recorded for ogre" in problems[0]
    assert not any("/status" in p for p in problems)


def test_never_ran_city_still_checks_last_success(monkeypatch):
    """A row in scrape_runs that /status does not return under this key means
    the keys disagree — worth seeing, so the success check must still run."""
    monkeypatch.setattr(watchdog, "get_last_success_age_hours", lambda city: 50.0)
    with patch.object(watchdog, "get_ws_status", return_value=watchdog.NO_RUN_RECORDED):
        summary, problems = watchdog.check_last_run("ogre", max_age_hours=26)
    assert "ok:50h ago" in summary
    assert any("no run recorded for ogre" in p for p in problems)
    assert any("last successful run is 50h old" in p for p in problems)


# --- backup listing: say why the listing failed ---

@pytest.mark.parametrize("stderr,expected", [
    ("An error occurred (NoSuchBucket) when calling the ListObjectsV2 "
     "operation: The specified bucket does not exist",
     "NoSuchBucket: bucket does not exist"),
    ("An error occurred (AccessDenied) when calling the ListObjectsV2 "
     "operation: Access Denied",
     "AccessDenied: IAM denies s3:ListBucket"),
    ("An error occurred (PermanentRedirect) when calling the ListObjectsV2 "
     "operation: The bucket is in this region: eu-north-1",
     "PermanentRedirect: bucket is in another region"),
    ("An error occurred (SomethingNew) when calling the ListObjectsV2 operation",
     "SomethingNew"),
    ("/bin/sh: aws: command not found", "aws CLI not available"),
])
def test_backup_listing_error_names_the_cause(stderr, expected):
    with patch.object(watchdog, "run_cmd", return_value=(1, "", stderr)):
        summary, problems = watchdog.check_backup("ogre", "staging", "eu-west-1", 26)
    assert summary == "bkp:unknown"
    assert len(problems) == 1
    assert problems[0].startswith("could not list s3://sslv-staging-ogre-db-backups")
    assert "eu-west-1" in problems[0]  # which region was tried
    assert expected in problems[0]


def test_backup_listing_error_without_stderr_still_reports():
    with patch.object(watchdog, "run_cmd", return_value=(1, "", "")):
        _, problems = watchdog.check_backup("ogre", "prod", "eu-west-1", 26)
    assert "could not list" in problems[0] and "unknown error" in problems[0]


# --- S3 region is configurable, SES region is not ---

def city_args(**overrides):
    args = MagicMock(env="staging", aws_region="eu-west-1", s3_region=None,
                     max_run_age_hours=26, max_running_hours=3,
                     max_backup_age_hours=26, min_backup_size_kb=1,
                     backup_min_bytes_per_row=5, backup_shrink_ratio=0.5,
                     backup_history=7)
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def backup_region_seen_by_check_city(args):
    healthy = dict(watchdog.CITY_SERVICES)
    with patch.object(watchdog, "check_containers", return_value=(healthy, [])), \
         patch.object(watchdog, "check_last_run", return_value=("run:success", [])), \
         patch.object(watchdog, "get_db_row_counts", return_value=(1, 2)), \
         patch.object(watchdog, "check_backup", return_value=("bkp:3h", [])) as backup:
        watchdog.check_city("ogre", args)
    return backup.call_args[0][2]


def test_backup_listing_uses_s3_region_when_set():
    assert backup_region_seen_by_check_city(
        city_args(s3_region="eu-north-1")) == "eu-north-1"


def test_backup_listing_falls_back_to_aws_region():
    assert backup_region_seen_by_check_city(city_args()) == "eu-west-1"


@pytest.mark.parametrize("env_var", ["S3_REGION", "AWS_REGION"])
def test_s3_region_defaults_from_env(monkeypatch, env_var):
    monkeypatch.delenv("S3_REGION", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.setenv(env_var, "eu-north-1")
    seen = {}
    with patch.object(watchdog, "parse_cities", return_value=["ogre"]), \
         patch.object(watchdog, "check_city",
                      side_effect=lambda c, a: seen.update(
                          s3=a.s3_region, ses=a.aws_region) or ("l", [])), \
         patch.object(watchdog, "check_host", return_value=HOST_OK):
        watchdog.main(["--email-mode", "never", "--ntfy-mode", "never"])
    assert seen["s3"] == "eu-north-1"
    assert seen["ses"] == "eu-west-1"  # SES identity is verified in one region
