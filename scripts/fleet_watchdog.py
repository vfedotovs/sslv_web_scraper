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

Then prints a one-line-per-city report and sends ONE consolidated email
via AWS SES (aws CLI): by default only when something is wrong
(--email-mode problems); use --email-mode always for a daily digest, or
never for terminal-only use (e.g. `make fleet-status`).

ntfy push (critical-monitoring P0, docs/critical_monitoring_ntfy_plan.md):
--ntfy-mode problems pushes to NTFY_TOPIC_URL only when the set of problems
changes (new alert, partial recovery, all resolved) plus a reminder every
--ntfy-reminder-hours while still failing, so a frequent timer does not spam.
State is kept in --state-file. --ntfy-mode always pushes every run (daily
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
import subprocess
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
URGENT_PROBLEM_PREFIXES = ("last run", "newest backup", "NO backups")
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
    (ws port 8000 is not exposed to the host). Returns dict or None."""
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
        return data.get("cities", {}).get(city)
    except (ValueError, AttributeError):
        return None


def check_last_run(city, max_age_hours):
    """Evaluate the last scrape run from /status; returns (summary, problems)."""
    problems = []
    run = get_ws_status(city)
    if run is None:
        return "run:unknown", [f"could not read /status from {city}-ws-1"]

    status = run.get("status")
    started_at = run.get("started_at")
    age_hours = None
    if started_at:
        try:
            started = datetime.fromisoformat(started_at)
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - started).total_seconds() / 3600
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
    if age_hours is not None and age_hours > max_age_hours:
        problems.append(
            f"last run is {age_hours:.0f}h old (> {max_age_hours}h) —"
            " scheduler may be dead"
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


def get_backup_freshness(bucket, region):
    """Newest object under db-backups/ via aws s3api.
    Returns (key, age_hours, size_bytes), 'empty', or 'error'."""
    rc, out, _ = run_cmd([
        "aws", "s3api", "list-objects-v2",
        "--bucket", bucket, "--prefix", "db-backups/",
        "--query", "sort_by(Contents, &LastModified)[-1].{Key: Key, LastModified: LastModified, Size: Size}",
        "--output", "json", "--region", region,
    ], timeout=60)
    if rc != 0:
        return "error"
    try:
        newest = json.loads(out)
    except ValueError:
        return "error"
    if not newest:
        return "empty"
    last_modified = datetime.fromisoformat(newest["LastModified"].replace("Z", "+00:00"))
    age_hours = (datetime.now(timezone.utc) - last_modified).total_seconds() / 3600
    return newest["Key"], age_hours, newest["Size"]


def check_backup(city, env, region, max_age_hours):
    """Evaluate S3 backup freshness; returns (summary, problems)."""
    bucket = f"sslv-{env}-{city.replace('_', '-')}-db-backups"
    result = get_backup_freshness(bucket, region)
    if result == "error":
        return "bkp:unknown", [f"could not list s3://{bucket}"]
    if result == "empty":
        return "bkp:none", [f"NO backups in s3://{bucket}"]
    key, age_hours, size = result
    summary = f"bkp:{age_hours:.0f}h {size // 1024}KB"
    problems = []
    if age_hours > max_age_hours:
        problems.append(
            f"newest backup is {age_hours:.0f}h old (> {max_age_hours}h):"
            f" s3://{bucket}/{key}"
        )
    return summary, problems


def check_city(city, args):
    """All checks for one city; returns (report line, problems list)."""
    problems = []

    states, container_problems = check_containers(city)
    problems.extend(container_problems)
    ok_containers = sum(
        1 for svc, expected in CITY_SERVICES.items() if states[svc] == expected
    )
    ctr_summary = f"ctr:{ok_containers}/{len(CITY_SERVICES)}"

    run_summary, run_problems = check_last_run(city, args.max_run_age_hours)
    problems.extend(run_problems)

    rows = get_db_row_counts(city)
    if rows is None:
        rows_summary = "LA:? RA:?"
        problems.append("could not read table row counts from db container")
    else:
        rows_summary = f"LA:{rows[0]} RA:{rows[1]}"

    backup_summary, backup_problems = check_backup(
        city, args.env, args.aws_region, args.max_backup_age_hours
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


def notify_ntfy(args, all_problems, lines, cities):
    """Push the fleet status to ntfy according to --ntfy-mode."""
    if args.ntfy_mode == "never":
        return
    if not args.ntfy_url:
        print("ntfy: no --ntfy-url / NTFY_TOPIC_URL set, skipping push")
        return

    now = datetime.now(timezone.utc)
    state = load_state(args.state_file)
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

    if send_ntfy(args.ntfy_url, title, body, priority, tags, args.ntfy_token):
        save_state(args.state_file, {
            "problems": {
                f"{city}: {problem_fingerprint(p)}": f"{city}: {p}"
                for city, ps in all_problems.items() for p in ps
            },
            "last_sent": now.isoformat(),
        })


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
    parser.add_argument("--aws-region", default="eu-west-1")
    parser.add_argument("--max-run-age-hours", type=float, default=26)
    parser.add_argument("--max-backup-age-hours", type=float, default=26)
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
    parser.add_argument("--ntfy-reminder-hours", type=float, default=6,
                        help="re-push an unchanged problem set after this long")
    parser.add_argument("--state-file",
                        default=os.getenv("WATCHDOG_STATE_FILE") or DEFAULT_STATE_FILE,
                        help="where the last pushed problem set is remembered")
    args = parser.parse_args(argv)

    cities = parse_cities(args.cities_file)
    if not cities:
        print(f"ERROR: no cities found in {args.cities_file}")
        return 1

    lines = []
    all_problems = {}
    for city in cities:
        line, problems = check_city(city, args)
        lines.append(line)
        if problems:
            all_problems[city] = problems

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    report = [f"SSLV fleet status — {now} — {len(cities)} cities,"
              f" {len(all_problems)} with problems", ""]
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
        subject = (f"SSLV FLEET ALERT: problems in"
                   f" {', '.join(sorted(all_problems))}")
    else:
        subject = f"SSLV FLEET: all {len(cities)} cities OK"
    if args.email_mode == "always" or (args.email_mode == "problems" and all_problems):
        send_email(subject, body, args.src_email, args.dest_email, args.aws_region)
    notify_ntfy(args, all_problems, lines, cities)

    return 1 if all_problems else 0


if __name__ == "__main__":
    sys.exit(main())
