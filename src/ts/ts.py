#!/usr/bin/env python3
"""
This module is sending HTTP GET requests to fast_api endpints
every day at 0:40 AM UTC (TASK_TIME), and verifies the run outcome an
hour later (VERIFY_TIME) via the ws /status endpoint (M6 monitoring
Item 7): the trigger timeout is expected (the pipeline outlives it), so
the real signal is the recorded run state — ts alerts via SES when the
trigger is refused, the run never started, or the run failed.

It solves triggering task using cronjob on schedule problem with multiple
container application
"""

import logging
from logging.handlers import RotatingFileHandler
import sys
import time
import os
from datetime import datetime, timezone
import requests
import schedule
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread

# boto3 is used for SES alert emails (M6 monitoring Item 7). Optional so a
# stripped-down ts image degrades to log-only alerts instead of crashing.
try:
    import boto3
except ImportError:
    boto3 = None


log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

LOG_FILE = "task_scheduler.log"
# Create a rotating file handler
file_handler = RotatingFileHandler(LOG_FILE,
                                   maxBytes=1024 * 1024,
                                   backupCount=9)
file_formatter = logging.Formatter(
    "%(asctime)s [%(threadName)-12.12s] "
    "[%(levelname)-5.5s] : %(funcName)s: %(lineno)d: %(message)s")

file_handler.setFormatter(file_formatter)
log.addHandler(file_handler)

# Create a stdout (console) handler
stdout_handler = logging.StreamHandler(sys.stdout)
stdout_formatter = logging.Formatter(
    "%(asctime)s [%(threadName)-12.12s] "
    "[%(levelname)-5.5s] : %(funcName)s: %(lineno)d: %(message)s")

stdout_handler.setFormatter(stdout_formatter)
log.addHandler(stdout_handler)

# Dynamic city support for multi-city (reads CITY from .env.<city>)
city = os.getenv("CITY", "ogre").lower()
WS_HOST = os.getenv("WS_HOST", "ws")
URL = f"http://{WS_HOST}:8000/run-task/{city}"
STATUS_URL = f"http://{WS_HOST}:8000/status"

# Daily schedule (UTC): trigger the scrape at TASK_TIME, then verify its
# outcome at VERIFY_TIME via the ws /status endpoint (M6 Items 5+7).
TASK_TIME = os.getenv("TASK_TIME", "00:40")
VERIFY_TIME = os.getenv("VERIFY_TIME", "01:40")
AWS_REGION = os.getenv("AWS_REGION", "eu-west-1")


def send_alert(subject: str, body: str) -> bool:
    """Send a short alert email via AWS SES. Never raises.

    Mirrors ws alert_mailer (M6 Item 3). Degrades to log-only when boto3
    or credentials are unavailable — an alert failure must not crash the
    scheduler loop.
    """
    if boto3 is None:
        log.error("ALERT (email unavailable, boto3 not installed): %s — %s",
                  subject, body)
        return False
    sender = os.getenv("SRC_EMAIL") or "info@propertydata.lv"
    recipient = os.getenv("DEST_EMAIL") or "info@propertydata.lv"
    try:
        client = boto3.client("ses", region_name=AWS_REGION)
        response = client.send_email(
            Destination={"ToAddresses": [recipient]},
            Message={
                "Body": {"Text": {"Charset": "UTF-8", "Data": body}},
                "Subject": {"Charset": "UTF-8", "Data": subject},
            },
            Source=sender,
        )
        log.info("Alert email sent! Subject: %s MessageId: %s",
                 subject, response["MessageId"])
        return True
    except Exception as e:
        log.error("Failed to send alert email '%s': %s", subject, e)
        return False


class HealthCheckHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler for health checks"""

    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status":"healthy"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Suppress default logging to avoid cluttering logs"""
        pass


def run_health_server():
    """Run health check server in background thread"""
    server = HTTPServer(('0.0.0.0', 8080), HealthCheckHandler)
    log.info("Health check server started on port 8080")
    server.serve_forever()


def execute_task():
    """
    Executes an HTTP GET request to the run-task/{city} FastAPI endpoint.

    This function sends an HTTP GET request to the dynamic URL for the
    current CITY. It logs information about the request,
    response, and any errors that may occur.

    Returns:
        None

    Raises:
        requests.Timeout: If the HTTP request times out.
        requests.RequestException: If an error occurs during the HTTP request.

    Note:
        The CITY env var (from .env.<city>) determines the endpoint.
    """
    timeout_seconds = 30

    try:
        log.info("HTTP GET %s", URL)
        response = requests.get(URL, timeout=timeout_seconds)
        if response.status_code == 200:
            log.info('HTTP GET response - 200')
        else:
            # e.g. 500 from a fast pipeline failure: ws already sent its own
            # failure alert (M6 Item 3) and verify_task will see the failed
            # run — log it, no duplicate email from ts.
            log.error(
                'HTTP GET response failed with %s code: %s',
                response.status_code, response.text)
        log.info("FAST_API Response: %s", response.text)

    except requests.Timeout:
        # M6 Item 7: this is EXPECTED — the synchronous /run-task pipeline
        # runs far longer than the trigger timeout. The run outcome is
        # verified separately by verify_task at VERIFY_TIME via /status.
        log.info(
            "Trigger request timed out after %s seconds — expected, the"
            " pipeline keeps running in ws. Outcome will be verified at"
            " %s UTC via %s", timeout_seconds, VERIFY_TIME, STATUS_URL)
    except requests.RequestException as request_exception:
        # Connection refused/DNS failure: the trigger itself never reached
        # ws — the run will NOT happen. This is the one trigger-side case
        # worth an immediate alert (M6 Item 7).
        log.error("Trigger request failed: %s", str(request_exception))
        send_alert(
            f"SSLV ALERT: {city} scrape trigger FAILED",
            f"The daily trigger GET {URL} could not reach the ws container:\n"
            f"{request_exception}\n\n"
            f"The scrape run for {city} will not happen today unless the ws"
            f" container recovers and the task is triggered manually:\n"
            f"  curl http://localhost:8000/run-task/{city}\n\n"
            f"Check: docker ps / docker logs {city}-ws-1",
        )


def get_run_status():
    """Fetch this city's last-run entry from the ws /status endpoint.

    Returns the run dict, or None when /status is unreachable/invalid.
    """
    try:
        response = requests.get(STATUS_URL, timeout=30)
        response.raise_for_status()
        return response.json().get("cities", {}).get(city)
    except (requests.RequestException, ValueError) as e:
        log.error("Could not fetch %s: %s", STATUS_URL, e)
        return None


def evaluate_run_status(run, today: str):
    """M6 Item 7 verification rules. Returns (problem, detail) or (None, msg).

    Args:
        run: this city's entry from /status (dict or None)
        today: UTC date string YYYY-MM-DD to compare started_at against
    """
    if run is None:
        return ("no run recorded",
                "ws /status has no runs recorded for this city")
    started_at = run.get("started_at") or ""
    if not started_at.startswith(today):
        return ("run never started today",
                f"last recorded run started at {started_at or 'unknown'}")
    status = run.get("status")
    if status == "failed":
        return ("run failed",
                f"failed at stage {run.get('failed_stage')}: {run.get('error')}")
    if status == "running":
        return (None, f"run still in progress (started {started_at})")
    return (None,
            f"run succeeded: new:{run.get('new_ads')}"
            f" removed:{run.get('removed_ads')}"
            f" listed rows:{run.get('listed_table_rows')}")


def verify_task():
    """Verify the outcome of today's triggered run via /status (M6 Item 7).

    Scheduled at VERIFY_TIME (default 01:40 UTC, an hour after the trigger).
    Logs the outcome; alerts when the run never started, is not recorded,
    or failed. ws also emails on failure (Item 3) — this is the scheduler-
    side confirmation that catches the cases ws cannot see (trigger lost,
    ws restarted mid-run, run never started).
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log.info("Verifying todays (%s) scrape run outcome for %s via %s",
             today, city, STATUS_URL)
    run = get_run_status()
    if run is None:
        send_alert(
            f"SSLV ALERT: {city} run verification impossible",
            f"Could not read {STATUS_URL} one hour after the daily trigger.\n"
            f"The ws container may be down or the DB unreachable — todays"
            f" scrape outcome for {city} is unknown.\n\n"
            f"Check: docker ps / docker logs {city}-ws-1",
        )
        return
    problem, detail = evaluate_run_status(run, today)
    if problem is None:
        log.info("Run verification OK for %s: %s", city, detail)
        return
    log.error("Run verification for %s: %s (%s)", city, problem, detail)
    send_alert(
        f"SSLV ALERT: {city} daily scrape — {problem}",
        f"Verification at {VERIFY_TIME} UTC found: {problem}\n{detail}\n\n"
        f"Trigger URL: {URL}\n"
        f"Manual retry:  curl http://localhost:8000/run-task/{city}\n"
        f"Check: docker logs {city}-ws-1",
    )


def run_task_scheduler():
    """
    Run the task scheduler for the current CITY.

    This function initializes the task scheduler to execute the task
    for the current city. It sets up a daily scheduled task
    to trigger an HTTP GET call to the 'run-task/{city}' endpoint
    at 0:40 AM UTC. The scheduler continuously checks for pending
    tasks and runs them.

    The function enters a loop that periodically checks the scheduler
    for pending tasks. After each check, it sleeps for 3600 seconds
    (1 hour) before checking again. The loop continues indefinitely.

    Note:
        - The CITY environment variable (from .env.<city>) controls
          which city endpoint is called.
        - Ensure that execute_task properly handles the HTTP GET call.
        - The 'log' object must be defined in the global scope.

    Returns:
        None

    """
    log.info("--- Started task_scheduler module ---")

    # Start health check server in background thread
    health_thread = Thread(target=run_health_server, daemon=True)
    health_thread.start()

    log.info("Scheduling daily trigger at %s and verification at %s (UTC)",
             TASK_TIME, VERIFY_TIME)
    schedule.every().day.at(TASK_TIME).do(execute_task)
    # M6 Item 7: verify the run outcome an hour after triggering
    schedule.every().day.at(VERIFY_TIME).do(verify_task)
    while True:
        # Check for pending tasks in the scheduler and run them
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger(__name__)

    run_task_scheduler()
