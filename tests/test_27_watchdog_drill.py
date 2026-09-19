"""Tests for scripts/watchdog_drill.py (critical-monitoring P3)."""
import argparse
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

DRILL_PY = Path(__file__).parent.parent / "scripts" / "watchdog_drill.py"

spec = importlib.util.spec_from_file_location("watchdog_drill", DRILL_PY)
drill_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drill_mod)
watchdog = drill_mod.watchdog

HEALTHY_MEM = {"MemTotal": 1843, "MemAvailable": 415, "SwapTotal": 0, "SwapFree": 0}


def push(body, priority="high", ok=True):
    return {"title": "t", "body": body, "priority": priority, "ok": ok}


def drill(marker="memory low", priority="high", mode="problems"):
    return drill_mod.Drill("x", "what", marker, priority, mode=mode)


# --- evaluate ---

def test_evaluate_alert_and_recovery_pass():
    induced = [push("Problems:\n- host: memory low: 415 MiB")]
    recovered = [push("Resolved:\n- host: memory low: 415 MiB", "default")]
    assert drill_mod.evaluate(drill(), induced, recovered) == (True, "sent (high)", "sent")


def test_evaluate_higher_priority_than_expected_still_passes():
    induced = [push("Problems:\n- host: memory low", "urgent")]
    recovered = [push("Resolved:\n- host: memory low")]
    assert drill_mod.evaluate(drill(), induced, recovered)[0] is True


def test_evaluate_lower_priority_fails():
    induced = [push("Problems:\n- ogre: newest backup is only 4 KB", "high")]
    recovered = [push("Resolved:\n- ogre: newest backup is only 4 KB")]
    passed, alert_note, _ = drill_mod.evaluate(
        drill("newest backup is only", "urgent"), induced, recovered)
    assert not passed and alert_note == "priority high < urgent"


def test_evaluate_missing_alert_and_unresolved_recovery_fail():
    passed, alert_note, recovery_note = drill_mod.evaluate(drill(), [], [])
    assert (passed, alert_note, recovery_note) == (False, "NOT SENT", "NOT SENT")
    # Problem still listed under Problems (not Resolved) in the recovery push.
    recovered = [push("Problems:\n- host: memory low")]
    assert drill_mod.evaluate(drill(), [push("memory low")], recovered)[2] == \
        "sent, but not listed as resolved"


def test_evaluate_failed_send_fails():
    induced = [push("memory low", ok=False)]
    assert drill_mod.evaluate(drill(), induced, [])[1] == "send failed"


def test_evaluate_heartbeat_needs_one_successful_push():
    hb = drill("", "low", mode="always")
    assert drill_mod.evaluate(hb, [push("ok", "low")], []) == (True, "sent (low)", "n/a")
    assert drill_mod.evaluate(hb, [], [])[0] is False


# --- schedule guard ---

def at(hour, minute):
    return datetime(2026, 9, 19, hour, minute, tzinfo=timezone.utc)


def test_near_schedule_guards_scrape_and_verify_times():
    assert drill_mod.near_schedule(at(0, 30))
    assert drill_mod.near_schedule(at(1, 55))
    assert drill_mod.near_schedule(at(0, 21))
    assert not drill_mod.near_schedule(at(0, 15))
    assert not drill_mod.near_schedule(at(14, 0))


def test_near_schedule_wraps_midnight():
    guard = drill_mod.near_schedule
    assert guard(at(23, 50), times=((0, 5),), guard_min=20)


# --- end to end with checks and ntfy faked ---

def run_one(name):
    args = argparse.Namespace(env="staging", ntfy_url="https://ntfy.sh/t", verbose=False)
    sent = MagicMock(return_value=True)
    recorder = drill_mod.PushRecorder(sent)
    target = next(d for d in drill_mod.build_drills("ogre") if d.name == name)
    with patch.object(watchdog, "parse_cities", return_value=["ogre"]), \
         patch.object(watchdog, "check_city", return_value=("ogre OK", [])), \
         patch.object(watchdog, "read_meminfo", return_value=HEALTHY_MEM), \
         patch.object(watchdog, "get_oom_kills", return_value=[]), \
         patch.object(watchdog.shutil, "disk_usage",
                      return_value=MagicMock(total=16 * 2**30, free=7 * 2**30)), \
         patch.object(watchdog, "check_fleet_containers", return_value=("ctr:4/4", [])):
        result = drill_mod.run_drill(args, target, recorder)
    return result, sent


def test_memory_drill_end_to_end():
    (passed, alert_note, recovery_note), sent = run_one("memory")
    assert passed, (alert_note, recovery_note)
    titles = [c.args[1] for c in sent.call_args_list]
    assert titles == ["[DRILL] [STAGING] SSLV ALERT: host",
                      "[DRILL] [STAGING] SSLV RESOLVED: all 1 cities OK"]


def test_oom_drill_end_to_end():
    (passed, alert_note, _), _ = run_one("oom")
    assert passed and alert_note == "sent (urgent)"


def test_heartbeat_drill_end_to_end():
    (passed, alert_note, _), sent = run_one("heartbeat")
    assert passed and alert_note == "sent (low)"
    assert "fleet OK" in sent.call_args.args[1]


def test_teardown_runs_even_when_induced_run_fails():
    args = argparse.Namespace(env="staging", ntfy_url="https://ntfy.sh/t", verbose=False)
    teardown = MagicMock()
    target = drill_mod.Drill("x", "what", "m", "high", setup=MagicMock(), teardown=teardown)
    with patch.object(drill_mod, "run_watchdog", side_effect=RuntimeError("boom")):
        try:
            drill_mod.run_drill(args, target, drill_mod.PushRecorder(MagicMock()))
        except RuntimeError:
            pass
    teardown.assert_called_once()


def test_main_rejects_unknown_drill_and_missing_url(monkeypatch):
    monkeypatch.delenv("NTFY_TOPIC_URL", raising=False)
    assert drill_mod.main(["--only", "memory"]) == 2
    assert drill_mod.main(["--ntfy-url", "https://ntfy.sh/t", "--only", "nope"]) == 2


def test_main_container_drill_refused_near_schedule(monkeypatch):
    monkeypatch.setattr(drill_mod, "near_schedule", lambda now: True)
    with patch.object(drill_mod, "run_drill") as run:
        code = drill_mod.main(["--ntfy-url", "https://ntfy.sh/t", "--only", "container"])
    assert code == 2
    run.assert_not_called()
