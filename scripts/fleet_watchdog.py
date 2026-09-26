#!/usr/bin/env python3
"""fleet_watchdog.py — M6 monitoring Item 6: host-level fleet watchdog + digest.

Runs on the EC2 host (host cron, not inside a container) and checks, for
every city in config/cities.yaml:

  1. Container health   — docker inspect of {city}-db-1/ws-1/ts-1/backup-1
  2. Last pipeline run  — ws /status endpoint (M6 Item 5), queried via
                          docker exec so port 8000 need not be exposed
  3. DB table state     — live listed_ads / removed_ads row counts via psql
  4. Backup freshness   — newest object age + size in the city's
                          sslv-{env}-{city}-db-backups bucket (aws s3api)

Host-level checks (critical-monitoring P1): available memory + swap, kernel
OOM kills since the last run (journalctl -k), disk free on /, running
compose containers vs the expected 4 per city (flags leftovers), container
restarts since the last run, and cross-city scraper collapse (>= N cities
discovering 0 URLs on their last run = ss.lv blocking or a site change).

Then prints a one-line-per-city report and sends ONE consolidated email
via AWS SES (aws CLI): by default only when something is wrong
(--email-mode problems); use --email-mode always for a daily digest, or
never for terminal-only use (e.g. `make fleet-status`).

ntfy push (critical-monitoring P0, docs/critical_monitoring_ntfy_plan.md):
--ntfy-mode problems pushes to NTFY_TOPIC_URL only when the set of problems
changes (new alert, partial recovery, all resolved) plus a reminder every
--ntfy-reminder-hours while still failing, so a frequent timer does not spam.
State is kept in --state-file, which also holds the restart-count and
last-check baselines; --ntfy-mode never (e.g. `make fleet-status`) is
read-only, so manual runs do not consume restart/OOM events. --ntfy-mode always pushes every run (daily
heartbeat: a missing heartbeat means the watchdog itself is broken).

Dependencies on the host: python3 (stdlib only), docker CLI, aws CLI.

Cron examples (EC2 host):
  # Quiet problems-only check every morning at 06:30 UTC
  30 6 * * * cd /home/ec2-user/sslv_web_scraper && /usr/bin/python3 scripts/fleet_watchdog.py >> /var/log/sslv-fleet-watchdog.log 2>&1
  # Or an always-on daily digest
  30 6 * * * cd /home/ec2-user/sslv_web_scraper && /usr/bin/python3 scripts/fleet_watchdog.py --email-mode always >> /var/log/sslv-fleet-watchdog.log 2>&1

Exit code: 0 when the fleet is healthy, 1 when any problem was detected
(also useful in shell pipelines and CI-style checks).
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import time
import sys
import urllib.request
from datetime import datetime, timezone


DEFAULT_CITIES_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "config", "cities.yaml"
)
# db/ws/ts have compose healthchecks; the backup container has none, so
# "running" is its healthy state.
CITY_SERVICES = {"db": "healthy", "ws": "healthy", "ts": "healthy", "backup": "running"}

DEFAULT_STATE_FILE = os.path.join(
    os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
    "sslv-watchdog", "state.json",
)
# Problems that mean the product is down or data is at risk push at "urgent";
# everything else (container state, unreadable status/DB) at "high".
URGENT_PROBLEM_PREFIXES = (
    "last run", "last successful run", "newest backup", "NO backups",
    "OOM kill", "disk critical", "scraper collapse",
)
ZERO_URLS_PROBLEM = "zero URLs discovered"
# get_ws_status: /status answered, but this city has no scrape_runs row yet
# (fresh deploy). Empty so it stays falsy for callers that do `status or {}`.
NO_RUN_RECORDED = {}
# aws CLI failures worth translating: the code alone does not say what to fix.
AWS_ERROR_HINTS = {
    "NoSuchBucket": "bucket does not exist",
    "AccessDenied": "IAM denies s3:ListBucket",
    "PermanentRedirect": "bucket is in another region — set --s3-region",
    "AuthorizationHeaderMalformed": "wrong region — set --s3-region",
    "InvalidAccessKeyId": "bad AWS credentials",
    "ExpiredToken": "AWS credentials expired",
}
# Pseudo-city keys for problems that are not tied to one city.
HOST_KEY = "host"
FLEET_KEY = "fleet"
NTFY_MAX_BODY_BYTES = 3800  # ntfy.sh message limit is 4096 bytes


def run_cmd(args, timeout=60):
    """Run a command; returns (returncode, stdout, stderr). Never raises."""
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


def parse_cities(yaml_path):
    """Extract city keys from config/cities.yaml (top-level entries under
    'cities:'). Minimal parser: host python has no pyyaml dependency."""
    cities = []
    try:
        with open(yaml_path, "r", encoding="utf-8") as fh:
            in_cities = False
            for line in fh:
                if re.match(r"^cities:\s*$", line):
                    in_cities = True
                    continue
                if in_cities:
                    match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
                    if match:
                        cities.append(match.group(1))
                    elif re.match(r"^\S", line):
                        break  # left the cities: block
    except OSError as e:
        print(f"ERROR: cannot read cities file {yaml_path}: {e}")
    return cities


def container_state(name):
    """Return 'healthy' / 'unhealthy' / 'starting' / 'running' / 'exited' /
    'missing' for a container."""
    rc, out, _ = run_cmd([
        "docker", "inspect", "--format",
        "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}",
        name,
    ])
    if rc != 0:
        return "missing"
    status, _, health = out.partition("|")
    return health or status


def check_containers(city):
    """Check all four city containers; returns (states dict, problems list)."""
    states = {}
    problems = []
    for service, expected in CITY_SERVICES.items():
        name = f"{city}-{service}-1"
        state = container_state(name)
        states[service] = state
        if state != expected:
            problems.append(f"container {name} is {state} (expected {expected})")
    return states, problems


def get_ws_status(city):
    """Fetch this city's entry from the ws /status endpoint via docker exec
    (ws port 8000 is not exposed to the host).

    Returns the run dict, NO_RUN_RECORDED when /status answered but has no
    row for this city, or None when /status could not be read at all
    (ws down, HTTP 503/404, unparseable body). The two are different
    problems: "never ran" is not "unreachable"."""
    rc, out, err = run_cmd([
        "docker", "exec", f"{city}-ws-1", "python", "-c",
        "import urllib.request;"
        "print(urllib.request.urlopen('http://localhost:8000/status', timeout=15)"
        ".read().decode())",
    ], timeout=30)
    if rc != 0:
        return None
    try:
        data = json.loads(out)
    except ValueError:
        return None
    cities = data.get("cities") if isinstance(data, dict) else None
    if not isinstance(cities, dict):
        return None
    run = cities.get(city)
    return NO_RUN_RECORDED if run is None else run


def get_last_success_age_hours(city):
    """Hours since this city's newest successful scrape_runs row, via psql in
    the db container. /status only returns the newest run of any status, so
    it cannot say how long the city has gone without a success.
    Returns a float, "none" when no success is recorded, or None on error."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", city):  # interpolated into SQL
        return None
    # started_at is a TIMESTAMP written with now(); comparing against
    # now()::timestamp keeps both sides in the server's timezone.
    rc, out, _ = run_cmd([
        "docker", "exec", f"{city}-db-1",
        "psql", "-U", "new_docker_user", "-d", "new_docker_db", "-t", "-A",
        "-c",
        "SELECT extract(epoch FROM now()::timestamp - max(started_at)) / 3600"
        f" FROM scrape_runs WHERE status = 'success' AND city = '{city}'",
    ], timeout=30)
    if rc != 0:
        return None
    value = out.strip()
    if not value:
        return "none"
    try:
        return float(value)
    except ValueError:
        return None


def check_last_run(city, max_age_hours, max_running_hours=3):
    """Evaluate the last scrape run from /status plus the age of the last
    successful run; returns (summary, problems)."""
    problems = []
    run = get_ws_status(city)
    if run is None:
        return "run:unknown", [f"could not read /status from {city}-ws-1"]

    # /status answered but knows nothing about this city: a fresh deploy that
    # has never run. Reporting that as "could not read /status" blamed the
    # endpoint and skipped the last-success check below.
    never_ran = run is NO_RUN_RECORDED
    status = None
    run_is_stale = False
    if never_ran:
        summary = "run:none"
        problems.append(
            f"no run recorded for {city} in scrape_runs — the pipeline has"
            " never run here (or runs under a different city key)"
        )
    else:
        status = run.get("status")
        started_at = run.get("started_at")
        if started_at:
            try:
                started = datetime.fromisoformat(started_at)
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                age_hours = (
                    datetime.now(timezone.utc) - started
                ).total_seconds() / 3600
            except ValueError:
                pass

        age_str = f"{age_hours:.0f}h ago" if age_hours is not None else "age unknown"
        summary = (
            f"run:{status} {age_str}"
            f" new:{run.get('new_ads')} rm:{run.get('removed_ads')}"
        )
        if status == "failed":
            problems.append(
                f"last run FAILED at stage {run.get('failed_stage')}:"
                f" {run.get('error')}"
            )
        run_is_stale = age_hours is not None and age_hours > max_age_hours
        if run_is_stale:
            problems.append(
                f"last run is {age_hours:.0f}h old (> {max_age_hours}h) —"
                " scheduler may be dead"
            )
        # A ws killed mid-pipeline (e.g. OOM) leaves its row "running" forever,
        # and ts.py's 01:40 verification does not treat "running" as a failure.
        elif (status == "running" and age_hours is not None
              and age_hours > max_running_hours):
            problems.append(
                f"last run stuck in 'running' for {age_hours:.0f}h"
                f" (> {max_running_hours}h) — ws likely died mid-pipeline"
            )

    # Runs can keep happening (and failing) while nothing succeeds, so the
    # product-level question is the age of the last success.
    success_age = get_last_success_age_hours(city)
    if success_age == "none":
        summary += " ok:never"
        if not never_ran:  # the "no run recorded" problem above already says it
            problems.append("last successful run: none recorded in scrape_runs")
    elif success_age is not None:
        summary += f" ok:{success_age:.0f}h ago"
        if success_age > max_age_hours and not run_is_stale:
            problems.append(
                f"last successful run is {success_age:.0f}h old"
                f" (> {max_age_hours}h)"
            )
    # None = run did not scrape (e.g. used cloud data); only 0 is a failure.
    if not never_ran and status == "success" and run.get("urls_discovered") == 0:
        problems.append(
            f"{ZERO_URLS_PROBLEM} in last run — list page parser broken"
            " or ss.lv is blocking the scraper"
        )
    return summary, problems


def get_db_row_counts(city):
    """Live listed_ads/removed_ads row counts via psql in the db container.
    Returns (listed, removed) or None."""
    rc, out, _ = run_cmd([
        "docker", "exec", f"{city}-db-1",
        "psql", "-U", "new_docker_user", "-d", "new_docker_db", "-t", "-A",
        "-c",
        "SELECT (SELECT COUNT(*) FROM listed_ads) || '|' ||"
        " (SELECT COUNT(*) FROM removed_ads)",
    ], timeout=30)
    if rc != 0 or "|" not in out:
        return None
    listed, _, removed = out.strip().partition("|")
    try:
        return int(listed), int(removed)
    except ValueError:
        return None


def aws_error_reason(stderr, fallback="unknown error"):
    """Turn aws CLI stderr into one actionable clause for an alert line.
    "NoSuchBucket", "AccessDenied" and "PermanentRedirect" all used to arrive
    as the same opaque failure, and they need three different fixes."""
    stderr = (stderr or "").strip()
    if not stderr:
        return fallback
    match = re.search(r"An error occurred \(([^)]+)\)", stderr)
    if match:
        code = match.group(1)
        hint = AWS_ERROR_HINTS.get(code)
        return f"{code}: {hint}" if hint else code
    if "command not found" in stderr or "No such file or directory" in stderr:
        return "aws CLI not available"
    return stderr.splitlines()[-1][:160]


def get_backup_history(bucket, region, count):
    """The newest `count` objects under db-backups/ via aws s3api, oldest
    first. Returns ("ok", [(key, age_hours, size_bytes), ...]),
    ("empty", None) or ("error", why)."""
    rc, out, err = run_cmd([
        "aws", "s3api", "list-objects-v2",
        "--bucket", bucket, "--prefix", "db-backups/",
        "--query", f"sort_by(Contents, &LastModified)[-{count}:]"
                   ".{Key: Key, LastModified: LastModified, Size: Size}",
        "--output", "json", "--region", region,
    ], timeout=60)
    if rc != 0:
        return "error", aws_error_reason(err)
    try:
        objects = json.loads(out)
    except ValueError:
        return "error", "unparseable aws s3api output"
    if not objects:
        return "empty", None
    now = datetime.now(timezone.utc)
    history = []
    for obj in objects:
        last_modified = datetime.fromisoformat(obj["LastModified"].replace("Z", "+00:00"))
        history.append((obj["Key"], (now - last_modified).total_seconds() / 3600, obj["Size"]))
    return "ok", history


def format_size(size_bytes):
    """Backups here are a few KB, so whole KB (2 KB vs 2.9 KB) hides the trend."""
    return f"{size_bytes / 1024:.1f} KB"


def check_backup(city, env, region, max_age_hours, min_size_kb=1, rows=None,
                 min_bytes_per_row=5, shrink_ratio=0.5, history=7):
    """Evaluate S3 backup freshness and size; returns (summary, problems).
    Size is checked here, from outside the backup container, because a dump
    of an empty or unreachable DB still uploads "successfully".

    A fixed floor cannot tell a small DB from a lost one: the staging DBs
    (30-330 rows) dump to 2-8 KB, the same size as an empty prod DB. So the
    floor only catches a broken dump, and two data-aware checks catch a dump
    that is missing the data:
      - expected size from the live row count (`rows` = (listed, removed);
        skipped when unknown). Staging measures ~19 B/row gzip'd, so the
        5 B/row default only fires when most of the data is gone.
      - shrink against the median of the previous backups (needs 3)."""
    bucket = f"sslv-{env}-{city.replace('_', '-')}-db-backups"
    outcome, detail = get_backup_history(bucket, region, history + 1)
    if outcome == "error":
        return "bkp:unknown", [
            f"could not list s3://{bucket} in {region} ({detail})"
        ]
    if outcome == "empty":
        return "bkp:none", [f"NO backups in s3://{bucket}"]
    key, age_hours, size = detail[-1]
    location = f"s3://{bucket}/{key}"
    summary = f"bkp:{age_hours:.0f}h {size // 1024}KB"
    problems = []
    if age_hours > max_age_hours:
        problems.append(
            f"newest backup is {age_hours:.0f}h old (> {max_age_hours}h): {location}"
        )

    floor = min_size_kb * 1024
    if size < floor:
        problems.append(
            f"newest backup is only {format_size(size)} (< {min_size_kb} KB"
            f" hard floor), the dump is truncated or failed: {location}"
        )
    elif rows is not None:
        row_count = sum(rows)
        expected = floor + row_count * min_bytes_per_row
        if size < expected:
            problems.append(
                f"newest backup is {format_size(size)} for {row_count} DB rows"
                f" (expected >= {format_size(expected)} at {min_bytes_per_row}"
                f" B/row), it likely does not contain the data: {location}"
            )

    previous = sorted(obj[2] for obj in detail[:-1])
    if len(previous) >= 3:
        middle = len(previous) // 2
        median = (previous[middle] if len(previous) % 2
                  else (previous[middle - 1] + previous[middle]) / 2)
        if size < median * shrink_ratio:
            problems.append(
                f"newest backup shrank to {format_size(size)} from a median of"
                f" {format_size(median)} over the previous {len(previous)}"
                f" backups (< {shrink_ratio:.0%}): {location}"
            )
    return summary, problems


def read_meminfo(path="/proc/meminfo"):
    """MemTotal/MemAvailable/SwapTotal/SwapFree in MiB, or None if unreadable."""
    wanted = ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree")
    info = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                key, _, value = line.partition(":")
                if key in wanted:
                    info[key] = int(value.split()[0]) // 1024  # kB -> MiB
    except (OSError, ValueError, IndexError):
        return None
    return info if len(info) == len(wanted) else None


def check_memory(min_available_mib):
    """Available (not free) memory: page cache is reclaimable, so MemAvailable
    is the real headroom. With no swap, running out means an instant OOM kill."""
    info = read_meminfo()
    if info is None:
        return "mem:?", []
    avail = info["MemAvailable"]
    swap_used = info["SwapTotal"] - info["SwapFree"]
    summary = f"mem:{avail}/{info['MemTotal']}MiB avail swap:{swap_used}/{info['SwapTotal']}MiB"
    problems = []
    if avail < min_available_mib:
        problems.append(
            f"memory low: {avail} MiB available (< {min_available_mib} MiB),"
            f" swap used {swap_used}/{info['SwapTotal']} MiB"
        )
    return summary, problems


def get_oom_kills(since_epoch):
    """Process names the kernel OOM-killed since since_epoch, or None when the
    kernel log is unreadable (journalctl missing or no journal access)."""
    # No -q: it would hide the warning that tells us the journal is not
    # readable, and an unreadable journal must show as "oom:?", not "oom:0".
    rc, out, err = run_cmd([
        "journalctl", "-k", "--no-pager", "-o", "cat",
        "--since", f"@{int(since_epoch)}",
    ], timeout=30)
    if rc != 0 or "insufficient permissions" in err or "not seeing messages" in err:
        return None
    return re.findall(r"Killed process \d+ \(([^)]+)\)", out)


def check_oom(since_epoch):
    kills = get_oom_kills(since_epoch)
    if kills is None:
        return "oom:?", []
    problems = []
    if kills:
        problems.append(
            f"OOM kill: {len(kills)} process(es) killed by the kernel since last"
            f" check ({', '.join(sorted(set(kills)))})"
        )
    return f"oom:{len(kills)}", problems


def check_disk(path, warn_free_pct, crit_free_pct):
    """A full disk stops Postgres writes for every city at once."""
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return "disk:?", []
    free_pct = usage.free * 100 / usage.total
    free_gib = usage.free / 2**30
    summary = f"disk:{100 - free_pct:.0f}% used ({free_gib:.1f}G free)"
    problems = []
    if free_pct < crit_free_pct:
        problems.append(
            f"disk critical: {free_pct:.0f}% free on {path}"
            f" ({free_gib:.1f} GiB, < {crit_free_pct}%)"
        )
    elif free_pct < warn_free_pct:
        problems.append(
            f"disk low: {free_pct:.0f}% free on {path}"
            f" ({free_gib:.1f} GiB, < {warn_free_pct}%)"
        )
    return summary, problems


def check_fleet_containers(cities, state):
    """Running compose containers vs the expected set, plus restarts since the
    last run. Updates state["restart_counts"]; returns (summary, problems)."""
    expected = {f"{city}-{svc}-1" for city in cities for svc in CITY_SERVICES}
    rc, out, _ = run_cmd([
        "docker", "ps", "-a", "--filter", "label=com.docker.compose.project",
        "--format", "{{.Names}}|{{.State}}",
    ])
    if rc != 0:
        return "ctr:?", []
    present, running = set(), set()
    for line in out.splitlines():
        name, _, container_state_ = line.partition("|")
        present.add(name)
        if container_state_ == "running":
            running.add(name)

    problems = []
    unexpected = sorted(running - expected)
    if unexpected:
        problems.append(
            "unexpected containers running (not in cities.yaml):"
            f" {', '.join(unexpected)}"
        )

    # Restart deltas. A container recreated by a deploy gets a new Id, which
    # resets its baseline instead of being reported as a restart.
    names = sorted(expected & present)
    counts = {}
    if names:
        rc, out, _ = run_cmd([
            "docker", "inspect", "--format", "{{.Name}}|{{.Id}}|{{.RestartCount}}",
        ] + names)
        for line in out.splitlines():
            parts = line.split("|")
            if len(parts) == 3 and parts[2].isdigit():
                counts[parts[0].lstrip("/")] = [parts[1], int(parts[2])]
    previous = state.get("restart_counts", {})
    for name, (cid, count) in sorted(counts.items()):
        prev = previous.get(name)
        if prev and prev[0] == cid and count > prev[1]:
            problems.append(
                f"container {name} restarted {count - prev[1]} time(s)"
                f" since last check (total {count})"
            )
    state["restart_counts"] = counts
    return f"ctr:{len(running & expected)}/{len(expected)}", problems


def check_host(cities, args, state, now_epoch):
    """All host-level checks; returns (report line, problems list)."""
    since = state.get("last_check_epoch") or now_epoch - args.first_run_lookback_min * 60
    summaries, problems = [], []
    for summary, host_problems in (
        check_memory(args.min_mem_available_mib),
        check_oom(since),
        check_disk("/", args.disk_warn_free_pct, args.disk_crit_free_pct),
        check_fleet_containers(cities, state),
    ):
        summaries.append(summary)
        problems.extend(host_problems)
    verdict = "OK " if not problems else "BAD"
    return f"{HOST_KEY:<12} {verdict} | {' | '.join(summaries)}", problems


def check_scraper_collapse(all_problems, cities, min_cities):
    """Cross-city view of zero-URL runs. All cities share one egress IP, so
    several collapsing together means blocking or a site-wide change, not
    one city's config. Returns a problem list for the fleet key."""
    zero = sorted(
        city for city, problems in all_problems.items()
        if any(p.startswith(ZERO_URLS_PROBLEM) for p in problems)
    )
    if len(zero) < min_cities:
        return []
    return [
        f"scraper collapse: {len(zero)}/{len(cities)} cities discovered 0 URLs"
        f" ({', '.join(zero)}) — likely ss.lv blocking or a site-wide change"
    ]


def ping_heartbeat(url):
    """GET a dead-man's-switch URL (e.g. healthchecks.io) to prove the
    watchdog itself still runs. Returns True on success."""
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return 200 <= response.status < 300
    except Exception as e:
        print(f"ERROR: heartbeat ping failed: {e}")
        return False


def check_city(city, args):
    """All checks for one city; returns (report line, problems list)."""
    problems = []

    states, container_problems = check_containers(city)
    problems.extend(container_problems)
    ok_containers = sum(
        1 for svc, expected in CITY_SERVICES.items() if states[svc] == expected
    )
    ctr_summary = f"ctr:{ok_containers}/{len(CITY_SERVICES)}"

    run_summary, run_problems = check_last_run(
        city, args.max_run_age_hours, args.max_running_hours
    )
    problems.extend(run_problems)

    rows = get_db_row_counts(city)
    if rows is None:
        rows_summary = "LA:? RA:?"
        problems.append("could not read table row counts from db container")
    else:
        rows_summary = f"LA:{rows[0]} RA:{rows[1]}"

    backup_summary, backup_problems = check_backup(
        city, args.env, args.s3_region or args.aws_region,
        args.max_backup_age_hours, args.min_backup_size_kb, rows=rows,
        min_bytes_per_row=args.backup_min_bytes_per_row,
        shrink_ratio=args.backup_shrink_ratio,
        history=args.backup_history,
    )
    problems.extend(backup_problems)

    verdict = "OK " if not problems else "BAD"
    line = (
        f"{city:<12} {verdict} | {run_summary} | {rows_summary}"
        f" | {backup_summary} | {ctr_summary}"
    )
    return line, problems


def send_email(subject, body, src, dest, region):
    """Send the digest via `aws ses send-email`. Returns True on success."""
    message = {
        "Source": src,
        "Destination": {"ToAddresses": [dest]},
        "Message": {
            "Subject": {"Charset": "UTF-8", "Data": subject},
            "Body": {"Text": {"Charset": "UTF-8", "Data": body}},
        },
    }
    rc, _, err = run_cmd([
        "aws", "ses", "send-email", "--region", region,
        "--cli-input-json", json.dumps(message),
    ], timeout=60)
    if rc != 0:
        print(f"ERROR: failed to send digest email: {err}")
        return False
    print(f"Digest email sent: {subject}")
    return True


def problem_fingerprint(problem):
    """Stable identity for a problem: digits masked, so "last run is 27h old"
    and "... 28h old" are the same ongoing problem, not a new alert."""
    return re.sub(r"\d+", "#", problem)


def load_state(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_state(path, state):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        print(f"ERROR: cannot write state file {path}: {e}")


def send_ntfy(url, title, message, priority="default", tags=None, token=None):
    """POST one notification to an ntfy topic URL. Returns True on success.
    Title must be ASCII (HTTP header); the message body may be UTF-8."""
    body = message.encode("utf-8")
    if len(body) > NTFY_MAX_BODY_BYTES:
        body = body[:NTFY_MAX_BODY_BYTES].decode("utf-8", "ignore").encode("utf-8") + b"\n..."
    headers = {"Title": title, "Priority": priority}
    if tags:
        headers["Tags"] = ",".join(tags)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            ok = 200 <= response.status < 300
    except Exception as e:
        print(f"ERROR: failed to send ntfy notification: {e}")
        return False
    if ok:
        print(f"ntfy notification sent: {title}")
    return ok


def ntfy_decision(all_problems, state, reminder_hours, now):
    """Decide what, if anything, to push in --ntfy-mode problems.

    Returns (kind, resolved) where kind is None, "alert", "reminder" or
    "resolved", and resolved lists problems that cleared since the last push.
    """
    current = {
        f"{city}: {problem_fingerprint(p)}": f"{city}: {p}"
        for city, problems in all_problems.items() for p in problems
    }
    previous = state.get("problems", {})
    resolved = [raw for fp, raw in previous.items() if fp not in current]

    if set(current) != set(previous):
        return ("alert" if current else "resolved"), resolved
    if current:
        last_sent = state.get("last_sent")
        try:
            age_hours = (now - datetime.fromisoformat(last_sent)).total_seconds() / 3600
        except (TypeError, ValueError):
            age_hours = None
        if age_hours is None or age_hours >= reminder_hours:
            return "reminder", []
    return None, []


def notify_ntfy(args, all_problems, lines, cities, state):
    """Push the fleet status to ntfy according to --ntfy-mode. Records the
    pushed problem set in state only when the push succeeded, so a failed
    push is retried on the next run."""
    if args.ntfy_mode == "never":
        return
    if not args.ntfy_url:
        print("ntfy: no --ntfy-url / NTFY_TOPIC_URL set, skipping push")
        return

    now = datetime.now(timezone.utc)
    kind, resolved = ntfy_decision(all_problems, state, args.ntfy_reminder_hours, now)
    if args.ntfy_mode == "always" and kind is None:
        kind = "reminder" if all_problems else "heartbeat"
    if kind is None:
        return

    env = args.env.upper()
    problem_lines = [f"- {city}: {p}" for city, ps in all_problems.items() for p in ps]
    if kind == "heartbeat":
        title = f"[{env}] SSLV fleet OK: {len(cities)}/{len(cities)} cities"
        priority, tags = "low", ["white_check_mark"]
        body = "\n".join(lines)
    elif kind == "resolved":
        title = f"[{env}] SSLV RESOLVED: all {len(cities)} cities OK"
        priority, tags = "default", ["white_check_mark"]
        body = "\n".join(["Resolved:"] + [f"- {r}" for r in resolved] + [""] + lines)
    else:
        urgent = any(
            p.startswith(URGENT_PROBLEM_PREFIXES)
            for ps in all_problems.values() for p in ps
        )
        prefix = "SSLV ALERT" if kind == "alert" else "SSLV STILL FAILING"
        title = f"[{env}] {prefix}: {', '.join(sorted(all_problems))}"
        priority = "urgent" if urgent else "high"
        tags = ["rotating_light"] if urgent else ["warning"]
        body_lines = ["Problems:"] + problem_lines
        if resolved:
            body_lines += ["", "Resolved:"] + [f"- {r}" for r in resolved]
        body = "\n".join(body_lines + [""] + lines)

    title = args.ntfy_title_prefix + title
    if send_ntfy(args.ntfy_url, title, body, priority, tags, args.ntfy_token):
        state["problems"] = {
            f"{city}: {problem_fingerprint(p)}": f"{city}: {p}"
            for city, ps in all_problems.items() for p in ps
        }
        state["last_sent"] = now.isoformat()


def main(argv=None):
    parser = argparse.ArgumentParser(description="SSLV fleet watchdog (M6 Item 6)")
    parser.add_argument("--cities-file", default=DEFAULT_CITIES_FILE)
    parser.add_argument("--env", default=os.getenv("ENV", "prod"),
                        help="deployment env for bucket names (default: prod)")
    parser.add_argument("--email-mode", choices=["problems", "always", "never"],
                        default="problems",
                        help="problems: email only when something is wrong"
                             " (default); always: daily digest; never: stdout only")
    parser.add_argument("--src-email", default=os.getenv("SRC_EMAIL") or "info@propertydata.lv")
    parser.add_argument("--dest-email", default=os.getenv("DEST_EMAIL") or "info@propertydata.lv")
    # SES stays pinned: the sender identity is verified in one region only.
    parser.add_argument("--aws-region", default="eu-west-1",
                        help="region for SES and, unless --s3-region says"
                             " otherwise, for the backup buckets")
    parser.add_argument("--s3-region",
                        default=os.getenv("S3_REGION") or os.getenv("AWS_REGION"),
                        help="region of the sslv-<env>-<city>-db-backups"
                             " buckets when it differs from --aws-region; the"
                             " wrong one fails with PermanentRedirect"
                             " (default: $S3_REGION, else $AWS_REGION)")
    parser.add_argument("--max-run-age-hours", type=float, default=26)
    parser.add_argument("--max-backup-age-hours", type=float, default=26)
    parser.add_argument("--max-running-hours", type=float, default=3,
                        help="a run still 'running' after this long is stuck")
    parser.add_argument("--min-backup-size-kb", type=int,
                        default=int(os.getenv("MIN_BACKUP_SIZE_KB", "1")),
                        help="hard floor: newest backup below this is a"
                             " truncated or failed dump"
                             " (default: $MIN_BACKUP_SIZE_KB or 1)")
    parser.add_argument("--backup-min-bytes-per-row", type=int,
                        default=int(os.getenv("BACKUP_MIN_BYTES_PER_ROW", "5")),
                        help="newest backup below floor + DB rows x this is"
                             " missing data (default: $BACKUP_MIN_BYTES_PER_ROW"
                             " or 5; staging measures ~19)")
    parser.add_argument("--backup-shrink-ratio", type=float,
                        default=float(os.getenv("BACKUP_SHRINK_RATIO", "0.5")),
                        help="newest backup below this fraction of the previous"
                             " backups' median has shrunk (default:"
                             " $BACKUP_SHRINK_RATIO or 0.5)")
    parser.add_argument("--backup-history", type=int,
                        default=int(os.getenv("BACKUP_HISTORY_N", "7")),
                        help="previous backups the shrink check compares with;"
                             " it needs at least 3 (default: $BACKUP_HISTORY_N or 7)")
    parser.add_argument("--ntfy-mode", choices=["problems", "always", "never"],
                        default="problems",
                        help="problems: push on problem-set change + reminders"
                             " (default); always: push every run (heartbeat);"
                             " never: no push. No-op without --ntfy-url")
    parser.add_argument("--ntfy-url", default=os.getenv("NTFY_TOPIC_URL"),
                        help="ntfy topic URL, e.g. https://ntfy.sh/<topic>"
                             " (default: $NTFY_TOPIC_URL)")
    parser.add_argument("--ntfy-token", default=os.getenv("NTFY_TOKEN"),
                        help="optional ntfy access token (default: $NTFY_TOKEN)")
    parser.add_argument("--ntfy-title-prefix", default="",
                        help='prepended to every push title, e.g. "[DRILL] "'
                             " (ASCII only: it is an HTTP header)")
    parser.add_argument("--ntfy-reminder-hours", type=float, default=6,
                        help="re-push an unchanged problem set after this long")
    parser.add_argument("--state-file",
                        default=os.getenv("WATCHDOG_STATE_FILE") or DEFAULT_STATE_FILE,
                        help="last pushed problem set + restart/OOM baselines")
    parser.add_argument("--min-mem-available-mib", type=int, default=150)
    parser.add_argument("--disk-warn-free-pct", type=float, default=20)
    parser.add_argument("--disk-crit-free-pct", type=float, default=10)
    parser.add_argument("--collapse-min-cities", type=int, default=3,
                        help="cities with 0 URLs on the same run that count as"
                             " a fleet-wide scraper collapse")
    parser.add_argument("--first-run-lookback-min", type=int, default=15,
                        help="OOM-kill lookback when there is no previous check")
    parser.add_argument("--heartbeat-ping-url", default=os.getenv("HEARTBEAT_PING_URL"),
                        help="dead-man's-switch URL pinged after every run"
                             " (default: $HEARTBEAT_PING_URL; skipped with"
                             " --ntfy-mode never)")
    args = parser.parse_args(argv)

    cities = parse_cities(args.cities_file)
    if not cities:
        print(f"ERROR: no cities found in {args.cities_file}")
        return 1

    # --ntfy-mode never (manual `make fleet-status`) is read-only: it must not
    # consume the restart/OOM baselines the timer-driven runs alert from.
    persist = args.ntfy_mode != "never"
    state = load_state(args.state_file)
    now_epoch = time.time()

    lines = []
    all_problems = {}
    for city in cities:
        line, problems = check_city(city, args)
        lines.append(line)
        if problems:
            all_problems[city] = problems

    collapse = check_scraper_collapse(all_problems, cities, args.collapse_min_cities)
    if collapse:
        all_problems[FLEET_KEY] = collapse

    host_line, host_problems = check_host(cities, args, state, now_epoch)
    lines.append(host_line)
    if host_problems:
        all_problems[HOST_KEY] = host_problems

    bad_cities = sum(1 for city in cities if city in all_problems)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    # Which buckets and thresholds: without them a prod report run on the
    # staging host reads like a staging outage.
    report = [f"SSLV fleet status [{args.env}] — {now} — {len(cities)} cities,"
              f" {bad_cities} with problems",
              f"thresholds: run/backup age {args.max_run_age_hours:g}h/"
              f"{args.max_backup_age_hours:g}h, backup floor"
              f" {args.min_backup_size_kb} KB + {args.backup_min_bytes_per_row}"
              f" B/row, shrink < {args.backup_shrink_ratio:.0%} of median", ""]
    report.extend(lines)
    if all_problems:
        report.append("")
        report.append("Problems:")
        for city, problems in all_problems.items():
            for problem in problems:
                report.append(f"- {city}: {problem}")
    body = "\n".join(report)
    print(body)

    if all_problems:
        subject = (f"SSLV FLEET ALERT [{args.env}]: problems in"
                   f" {', '.join(sorted(all_problems))}")
    else:
        subject = f"SSLV FLEET [{args.env}]: all {len(cities)} cities OK"
    if args.email_mode == "always" or (args.email_mode == "problems" and all_problems):
        send_email(subject, body, args.src_email, args.dest_email, args.aws_region)
    notify_ntfy(args, all_problems, lines, cities, state)

    if persist:
        state["last_check_epoch"] = now_epoch
        save_state(args.state_file, state)
        if args.heartbeat_ping_url:
            ping_heartbeat(args.heartbeat_ping_url)

    return 1 if all_problems else 0


if __name__ == "__main__":
    sys.exit(main())
