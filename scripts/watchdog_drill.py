#!/usr/bin/env python3
"""watchdog_drill.py — critical-monitoring P3: fire every fleet_watchdog alert
once, end to end, and confirm both the alert and the recovery push are sent.

Each drill runs the real watchdog (real docker/psql/S3/host checks, real ntfy
push) twice with its own throwaway state file:

  1. induced   — the condition is created, the alert push must contain it
  2. recovered — the condition is removed, the next push must list it under
                 "Resolved:"

How each condition is induced (only the container drill touches the host):

  memory     threshold override (--min-mem-available-mib huge)
  disk       threshold override (--disk-warn-free-pct 100); nothing is filled
  backup     threshold override (--min-backup-size-kb huge); S3 untouched
  oom        kernel OOM log faked in-process (a real OOM kill is not safe)
  stuck-run  /status faked in-process: one city 'running' for 4h
  collapse   /status faked in-process: every city discovered 0 URLs
  container  real: `docker stop <city>-ts-1`, then `docker start` + wait healthy
  heartbeat  --ntfy-mode always: the daily low-priority "fleet OK" push

The detection logic behind each threshold is unit-tested
(tests/test_12_fleet_watchdog.py); the drill proves collection, the alert
path and ntfy delivery on the real host. Push titles start with "[DRILL] ".

The missing-heartbeat check (#7) cannot be automated here: it means stopping
sslv-watchdog-heartbeat.timer for a day and noticing the silence (or the
dead-man's-switch alert). See docs/critical_monitoring_ntfy_plan.md.

Usage (on the EC2 host; `make watchdog-drill` pauses the watchdog timer):
  NTFY_TOPIC_URL=https://ntfy.sh/<topic> python3 scripts/watchdog_drill.py --env staging
  python3 scripts/watchdog_drill.py --env staging --only memory,container

Exit code: 0 when every drill sent its alert and recovery push, 1 otherwise.
"""

import argparse
import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from unittest import mock

WATCHDOG_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fleet_watchdog.py")
_spec = importlib.util.spec_from_file_location("fleet_watchdog", WATCHDOG_PY)
assert _spec is not None and _spec.loader is not None
watchdog = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(watchdog)

PRIORITY_RANK = {"min": 1, "low": 2, "default": 3, "high": 4, "urgent": 5}
# The ts container drill would skip a city's scrape or its verification if it
# overlapped the scheduler's trigger (00:40) or verify (01:40) time, UTC.
SCHEDULE_TIMES_UTC = ((0, 40), (1, 40))
SCHEDULE_GUARD_MIN = 20


class Drill:
    def __init__(self, name, what, marker, priority, extra_args=(),
                 patches=None, setup=None, teardown=None, mode="problems"):
        self.name = name
        self.what = what
        self.marker = marker          # substring of the expected problem line
        self.priority = priority      # minimum expected push priority
        self.extra_args = list(extra_args)
        self.patches = patches        # callable -> list of mock patchers
        self.setup = setup
        self.teardown = teardown
        self.mode = mode


class PushRecorder:
    """Wraps the real send_ntfy: the push is really sent, and recorded."""

    def __init__(self, real_send):
        self.real_send = real_send
        self.calls = []

    def __call__(self, url, title, message, priority="default", tags=None, token=None):
        ok = self.real_send(url, title, message, priority, tags, token)
        self.calls.append({"title": title, "body": message, "priority": priority, "ok": ok})
        return ok


def near_schedule(now, times=SCHEDULE_TIMES_UTC, guard_min=SCHEDULE_GUARD_MIN):
    """True when now (UTC) is within guard_min minutes of a scheduler time."""
    for hour, minute in times:
        for day_offset in (-1, 0, 1):
            at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            at += timedelta(days=day_offset)
            if abs((now - at).total_seconds()) <= guard_min * 60:
                return True
    return False


def resolved_section(body):
    """Text after the "Resolved:" header of a push body ("" if absent)."""
    _, sep, rest = body.partition("Resolved:")
    return rest if sep else ""


def evaluate(drill, induced, recovered):
    """Judge one drill from the pushes of its two runs.
    Returns (passed, alert_note, recovery_note)."""
    alert = next((c for c in induced if drill.marker in c["body"]), None)
    if drill.mode == "always":
        # Heartbeat: any successful push counts; healthy fleets send "low".
        push = induced[-1] if induced else None
        if push and push["ok"]:
            return True, f"sent ({push['priority']})", "n/a"
        return False, "NOT SENT" if not push else "send failed", "n/a"

    if alert is None:
        alert_note = "NOT SENT" if not induced else "sent, but problem missing"
    elif not alert["ok"]:
        alert_note = "send failed"
    elif PRIORITY_RANK[alert["priority"]] < PRIORITY_RANK[drill.priority]:
        alert_note = f"priority {alert['priority']} < {drill.priority}"
    else:
        alert_note = f"sent ({alert['priority']})"

    recovery = next((c for c in recovered if drill.marker in resolved_section(c["body"])), None)
    if recovery is None:
        recovery_note = "NOT SENT" if not recovered else "sent, but not listed as resolved"
    elif not recovery["ok"]:
        recovery_note = "send failed"
    else:
        recovery_note = "sent"
    passed = alert_note.startswith("sent (") and recovery_note == "sent"
    return passed, alert_note, recovery_note


def run_watchdog(args, state_file, recorder, mode="problems", extra_args=(), patches=()):
    """One real watchdog run; returns the pushes it made. Output is captured
    (and shown with --verbose)."""
    argv = [
        "--env", args.env, "--email-mode", "never", "--ntfy-mode", mode,
        "--ntfy-url", args.ntfy_url, "--ntfy-title-prefix", "[DRILL] ",
        "--state-file", state_file, "--heartbeat-ping-url", "",
    ] + list(extra_args)
    before = len(recorder.calls)
    out = io.StringIO()
    with contextlib.ExitStack() as stack:
        for patcher in patches:
            stack.enter_context(patcher)
        stack.enter_context(mock.patch.object(watchdog, "send_ntfy", recorder))
        stack.enter_context(contextlib.redirect_stdout(out))
        watchdog.main(argv)
    if args.verbose:
        print(out.getvalue())
    return recorder.calls[before:]


def docker(*cmd):
    return subprocess.run(["docker", *cmd], capture_output=True, text=True, timeout=120)


def wait_healthy(name, timeout_s=150):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if watchdog.container_state(name) == "healthy":
            return True
        time.sleep(5)
    return False


def build_drills(city):
    real_get_ws_status = watchdog.get_ws_status
    now_iso = lambda hours_ago=0: (  # noqa: E731
        datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%S")

    def zero_urls(c):
        run: dict = dict(real_get_ws_status(c) or {"started_at": now_iso(1)})
        run["status"] = "success"
        run["urls_discovered"] = 0
        return run

    def stuck(c):
        if c != city:
            return real_get_ws_status(c)
        return {"status": "running", "started_at": now_iso(4)}

    ts = f"{city}-ts-1"

    def stop_ts():
        result = docker("stop", ts)
        if result.returncode != 0:
            raise RuntimeError(f"docker stop {ts} failed: {result.stderr.strip()}")

    def start_ts():
        docker("start", ts)
        if not wait_healthy(ts):
            print(f"  WARNING: {ts} is not healthy yet — check `docker ps`")

    return [
        Drill("memory", "memory threshold raised above total RAM", "memory low", "high",
              ["--min-mem-available-mib", "10000000"]),
        Drill("disk", "disk warn threshold set to 100% (nothing is filled)", "disk low", "high",
              ["--disk-warn-free-pct", "100", "--disk-crit-free-pct", "0"]),
        Drill("backup", "min backup size raised above any real backup",
              "newest backup is only", "urgent", ["--min-backup-size-kb", "1000000000"]),
        Drill("oom", "kernel OOM log faked (1 killed process)", "OOM kill", "urgent",
              patches=lambda: [mock.patch.object(watchdog, "get_oom_kills",
                                                 return_value=["drill-process"])]),
        Drill("stuck-run", f"/status faked: {city} 'running' for 4h", "stuck in 'running'",
              "urgent", patches=lambda: [mock.patch.object(watchdog, "get_ws_status", stuck)]),
        Drill("collapse", "/status faked: every city discovered 0 URLs", "scraper collapse",
              "urgent", patches=lambda: [mock.patch.object(watchdog, "get_ws_status", zero_urls)]),
        Drill("container", f"real: docker stop {ts}", f"container {ts} is", "high",
              setup=stop_ts, teardown=start_ts),
        Drill("heartbeat", "--ntfy-mode always (daily heartbeat push)", "", "low",
              mode="always"),
    ]


def run_drill(args, drill, recorder):
    with tempfile.TemporaryDirectory(prefix="watchdog-drill-") as tmp:
        state_file = os.path.join(tmp, "state.json")
        patches = drill.patches() if drill.patches else []
        if drill.mode == "always":
            induced = run_watchdog(args, state_file, recorder, mode="always")
            return evaluate(drill, induced, [])
        try:
            if drill.setup:
                drill.setup()
            induced = run_watchdog(args, state_file, recorder,
                                   extra_args=drill.extra_args, patches=patches)
        finally:
            if drill.teardown:
                drill.teardown()
        recovered = run_watchdog(args, state_file, recorder)
        return evaluate(drill, induced, recovered)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fire each fleet_watchdog alert once (P3)")
    parser.add_argument("--env", default=os.getenv("ENV", "staging"))
    parser.add_argument("--ntfy-url", default=os.getenv("NTFY_TOPIC_URL"))
    parser.add_argument("--city", help="city for the stuck-run/container drills"
                                       " (default: first in cities.yaml)")
    parser.add_argument("--only", help="comma-separated drill names")
    parser.add_argument("--force", action="store_true",
                        help="run the container drill even near the scrape schedule")
    parser.add_argument("--verbose", action="store_true", help="show watchdog output")
    args = parser.parse_args(argv)

    if not args.ntfy_url:
        print("ERROR: set NTFY_TOPIC_URL or --ntfy-url")
        return 2
    cities = watchdog.parse_cities(watchdog.DEFAULT_CITIES_FILE)
    if not cities:
        print("ERROR: no cities in config/cities.yaml")
        return 2
    city = args.city or cities[0]

    drills = build_drills(city)
    if args.only:
        wanted = {name.strip() for name in args.only.split(",")}
        unknown = wanted - {d.name for d in drills}
        if unknown:
            print(f"ERROR: unknown drill(s): {', '.join(sorted(unknown))}")
            return 2
        drills = [d for d in drills if d.name in wanted]

    now = datetime.now(timezone.utc)
    if any(d.name == "container" for d in drills) and near_schedule(now) and not args.force:
        print(f"ERROR: {now:%H:%M} UTC is within {SCHEDULE_GUARD_MIN} min of the"
              " 00:40/01:40 scrape schedule; stopping a ts container now could skip"
              " a run. Retry later, drop the container drill, or pass --force.")
        return 2

    print(f"Watchdog drill: env={args.env}, topic={args.ntfy_url}, city={city},"
          f" {len(drills)} drill(s). Each run takes a while (all cities are checked).\n")
    recorder = PushRecorder(watchdog.send_ntfy)
    results = []
    for drill in drills:
        print(f"[{drill.name}] {drill.what} ...", flush=True)
        try:
            passed, alert_note, recovery_note = run_drill(args, drill, recorder)
        except Exception as e:  # a failed setup must not stop the other drills
            passed, alert_note, recovery_note = False, f"error: {e}", "-"
        results.append((drill.name, passed, alert_note, recovery_note))
        print(f"  alert: {alert_note} | recovery: {recovery_note}"
              f" -> {'PASS' if passed else 'FAIL'}", flush=True)
        time.sleep(2)  # stay far below ntfy.sh rate limits

    print("\nDrill        Result  Alert push                  Recovery push")
    for name, passed, alert_note, recovery_note in results:
        print(f"{name:<12} {'PASS' if passed else 'FAIL':<7} {alert_note:<27} {recovery_note}")
    sent = sum(1 for c in recorder.calls if c["ok"])
    print(f"\n{sent} push(es) sent. Confirm on your phone that {sent} '[DRILL]'"
          " notifications arrived — the script can only see that ntfy accepted them.")
    print("Still manual (#7): stop sslv-watchdog-heartbeat.timer for a day and"
          " confirm the missing heartbeat is noticed.")
    return 0 if all(r[1] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
