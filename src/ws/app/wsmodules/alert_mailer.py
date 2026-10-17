#!/usr/bin/env python3
"""alert_mailer module (M6 monitoring Item 3).

Sends short failure and anomaly alert emails through the same AWS SES
path used by the daily report mailer (aws_mailer.py). Two message types:

1. Pipeline failure alert — sent from the pipeline-level failure handler
   in main.py when any stage raises (Item 1 propagation):
       Subject: SSLV ALERT: {city} pipeline FAILED at {stage}

2. Anomaly alert — sent after a *successful* run when threshold checks on
   the scrape_runs counts (Item 2) trip:
       - urls_discovered == 0        → parser broke or ss.lv is blocking
       - removed ads > N% of table   → discovery failure, not real delistings
       - zero new ads for N runs     → likely silent breakage

Thresholds are env-configurable:
    ALERT_REMOVED_PCT     max % of pre-run listed_ads rows that may be
                          removed in one run (default 30)
    ALERT_ZERO_NEW_RUNS   consecutive successful runs with zero new ads
                          before alerting (default 3)

Every public function here is best-effort by design: alerting must never
mask the original failure or fail an otherwise-successful run. Errors are
logged, not raised (unlike the pipeline modules per Item 1 — an alert is
telemetry, not pipeline work).
"""

import os
import sys
import logging
from logging import handlers
import boto3
from botocore.exceptions import ClientError

from app.wsmodules.scrape_runs import get_recent_runs, format_recent_runs


log = logging.getLogger("alert_mailer")
log.setLevel(logging.INFO)
alert_log_format = logging.Formatter(
    "%(asctime)s [%(levelname)-5.5s] : %(funcName)s: %(lineno)d: %(message)s"
)
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(alert_log_format)
log.addHandler(ch)
fh = handlers.RotatingFileHandler(
    "aws_mailer.log", maxBytes=(1048576 * 5), backupCount=7
)
fh.setFormatter(alert_log_format)
log.addHandler(fh)


AWS_REGION = "eu-west-1"

# Anomaly thresholds (see module docstring)
ALERT_REMOVED_PCT = int(os.getenv("ALERT_REMOVED_PCT", "30"))
ALERT_ZERO_NEW_RUNS = int(os.getenv("ALERT_ZERO_NEW_RUNS", "3"))


def _get_sender() -> str:
    return os.getenv("SRC_EMAIL") or "info@propertydata.lv"


def _get_recipient() -> str:
    return os.getenv("DEST_EMAIL") or "info@propertydata.lv"


def send_alert_email(subject: str, body: str) -> bool:
    """Send a short alert email via AWS SES. Never raises.

    Returns True when SES accepted the message, False otherwise — a failed
    alert must not mask the pipeline error it is reporting.
    """
    try:
        client = boto3.client("ses", region_name=AWS_REGION)
        response = client.send_email(
            Destination={"ToAddresses": [_get_recipient()]},
            Message={
                "Body": {"Text": {"Charset": "UTF-8", "Data": body}},
                "Subject": {"Charset": "UTF-8", "Data": subject},
            },
            Source=_get_sender(),
        )
        log.info(f"Alert email sent! Subject: {subject} "
                 f"MessageId: {response['MessageId']}")
        return True
    except ClientError as e:
        log.error(f"Failed to send alert email '{subject}': "
                  f"{e.response['Error']['Message']}")
        return False
    except Exception as e:
        log.error(f"Failed to send alert email '{subject}': {e}")
        return False


def send_pipeline_failure_alert(city: str, stage: str, error: str) -> bool:
    """Compose and send the FAILED: {city} — {stage} — {error} email."""
    subject = f"SSLV ALERT: {city} pipeline FAILED at {stage}"
    body_lines = [
        f"FAILED: {city} — {stage} — {error}",
        "",
        "The daily scrape pipeline failed and no report email was sent.",
        "Check the ws container logs for the full traceback:",
        f"  docker logs {city}-ws-1",
        "",
    ]
    body_lines.append(_recent_runs_block(city))
    return send_alert_email(subject, "\n".join(body_lines))


def check_run_anomalies(runs: list) -> list:
    """Evaluate anomaly rules against recent runs (newest first).

    Args:
        runs: list of scrape_runs dicts as returned by get_recent_runs(),
              where runs[0] is the run that just finished successfully.

    Returns:
        List of human-readable anomaly description strings (empty = healthy).
    """
    anomalies = []
    if not runs:
        return anomalies
    run = runs[0]

    urls_discovered = run.get("urls_discovered")
    if urls_discovered == 0:
        anomalies.append(
            "Discovered ads == 0 — the list page parser is broken or"
            " ss.lv is blocking the scraper."
        )

    removed = run.get("removed_ads") or 0
    still = run.get("still_listed_ads") or 0
    pre_run_table_rows = still + removed
    if pre_run_table_rows > 0:
        removed_pct = removed * 100 / pre_run_table_rows
        if removed_pct > ALERT_REMOVED_PCT:
            anomalies.append(
                f"Removed {removed} of {pre_run_table_rows} listed ads"
                f" ({removed_pct:.0f}% > {ALERT_REMOVED_PCT}% threshold) in one"
                " run — likely a discovery failure, not real delistings."
            )

    successful = [r for r in runs if r.get("status") == "success"]
    recent_success = successful[:ALERT_ZERO_NEW_RUNS]
    if (
        len(recent_success) >= ALERT_ZERO_NEW_RUNS
        and all(r.get("new_ads") == 0 for r in recent_success)
    ):
        anomalies.append(
            f"Zero new ads for the last {ALERT_ZERO_NEW_RUNS} successful runs"
            " — likely silent breakage in URL discovery or diffing."
        )

    return anomalies


def check_and_alert(city: str) -> list:
    """Run anomaly checks for a just-finished successful run; email if any trip.

    Called from main.py after finish_run('success'). Best-effort: any error
    (DB unavailable, SES failure) is logged and swallowed — anomaly checking
    must never fail a run that succeeded.

    Returns the list of detected anomalies (useful for logging/tests).
    """
    try:
        runs = get_recent_runs(city, limit=ALERT_ZERO_NEW_RUNS + 5)
        anomalies = check_run_anomalies(runs)
        if not anomalies:
            log.info(f"No run anomalies detected for city {city}")
            return []
        log.warning(f"Detected {len(anomalies)} run anomaly(ies) for city"
                    f" {city}: {anomalies}")
        subject = (
            f"SSLV ANOMALY: {city} — {len(anomalies)} check(s) tripped"
        )
        body_lines = [f"Anomalies detected after a successful run for {city}:", ""]
        body_lines.extend(f"- {anomaly}" for anomaly in anomalies)
        body_lines.append("")
        body_lines.append(_recent_runs_block(city))
        send_alert_email(subject, "\n".join(body_lines))
        return anomalies
    except Exception as e:
        log.error(f"Anomaly check failed for city {city}: {e}")
        return []


def _recent_runs_block(city: str) -> str:
    """Recent run history for alert email bodies (best-effort)."""
    try:
        return format_recent_runs(city)
    except Exception as e:
        log.warning(f"Could not fetch recent run history for alert body: {e}")
        return "Scrape run history unavailable."
