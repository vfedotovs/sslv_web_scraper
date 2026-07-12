#!/usr/bin/env python3
"""
This is entry point for module that provides basic API interface which will trigger web scrape job for specific city.

This module contains functions:
- home
- status
- async run_long_task (M7 P6: enqueues the pipeline and returns immediately)
- execute_pipeline (runs the pipeline in a background thread)
- check_today_cloud_data_file_exist
- get_todays_cloud_data_file_name

"""

from datetime import datetime
import logging
import logging.handlers as handlers
from logging.handlers import RotatingFileHandler
import os
import sys
import threading
import uvicorn
from fastapi import FastAPI, HTTPException
from app.wsmodules.file_downloader import download_latest_lambda_file
from app.wsmodules.web_scraper import scrape_website
# Optional city config (Phase 4)
try:
    from app.wsmodules.city_config import validate_city_slug, get_display_name
except Exception:
    validate_city_slug = lambda s: True
    get_display_name = lambda s, d=None: d or s
from app.wsmodules.data_format_changer import cloud_data_formater_main
from app.wsmodules.df_cleaner import df_cleaner_main
from app.wsmodules.db_worker import db_worker_main
from app.wsmodules.analytics import analytics_main
from app.wsmodules.aws_mailer import aws_mailer_main
from app.wsmodules import scrape_runs
from app.wsmodules import alert_mailer


log = logging.getLogger("fastapi")
log.setLevel(logging.INFO)
fastapi_log_format = logging.Formatter(
    "%(asctime)s [%(levelname)-5.5s] : %(funcName)s: %(lineno)d: %(message)s"
)

ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(fastapi_log_format)
log.addHandler(ch)

fh = handlers.RotatingFileHandler("ws_main.log", maxBytes=(1048576 * 5), backupCount=5)
fh.setFormatter(fastapi_log_format)
log.addHandler(fh)

app = FastAPI()

# M7 P6: one pipeline run at a time per ws container. The endpoint acquires
# this lock (non-blocking) before spawning the background run; the run
# releases it when finished. Replaces nothing-but-a-marker-file protection
# against overlapping runs.
_pipeline_lock = threading.Lock()


class PipelineStageError(Exception):
    """Raised when a pipeline stage fails; carries the failed stage name
    so the endpoint (and later monitoring/alerting) can report it."""

    def __init__(self, stage: str, original: Exception):
        self.stage = stage
        self.original = original
        super().__init__(f"Pipeline stage '{stage}' failed: {original}")


def run_pipeline_stages(stages: list) -> None:
    """Run (stage_name, callable) pairs in order.

    M6 monitoring Item 1: any exception raised inside a stage is no longer
    swallowed by the wsmodules — it propagates here and is wrapped in
    PipelineStageError so the run fails loudly with the stage name attached.
    """
    for stage_name, stage_func in stages:
        log.info("Running %s stage", stage_name)
        try:
            stage_func()
        except Exception as exc:
            log.error("Stage %s FAILED: %s", stage_name, exc)
            raise PipelineStageError(stage_name, exc) from exc
        log.info("Completed %s stage", stage_name)


@app.get("/")
def home():
    """Test enpoint to verify if fast-api is live"""
    log.info("Recieved GET request on / FastAPI server is ready ...")

    return {"FastAPI server is ready !!!"}


@app.get("/status")
def status():
    """M6 monitoring Item 5: machine-readable run status from scrape_runs.

    Returns the most recent run per city with status, counts, and duration,
    so the ts scheduler, the host watchdog (Item 6), or an operator can
    answer "did last night work?" without docker exec:
        curl http://localhost:8000/status
    Returns 503 when the DB is unreachable (a probe must not pretend health).
    """
    log.info("Received GET request on /status")
    try:
        scrape_runs.ensure_scrape_runs_table()
        last_runs = scrape_runs.get_last_run_per_city()
    except Exception as exc:
        log.error("/status failed to read scrape_runs: %s", exc)
        raise HTTPException(
            status_code=503, detail=f"scrape_runs table unavailable: {exc}"
        ) from exc
    return {
        "status": "ok",
        "cities": {run["city"]: _serialize_run(run) for run in last_runs},
    }


def _serialize_run(run: dict) -> dict:
    """JSON-friendly view of a scrape_runs row (ISO timestamps + duration)."""
    started = run.get("started_at")
    finished = run.get("finished_at")
    duration_seconds = None
    if started is not None and finished is not None:
        duration_seconds = int((finished - started).total_seconds())
    serialized = dict(run)
    serialized["started_at"] = started.isoformat() if started else None
    serialized["finished_at"] = finished.isoformat() if finished else None
    serialized["duration_seconds"] = duration_seconds
    return serialized


def execute_pipeline(city: str, stages: list, source: str) -> None:
    """M7 P6: run the pipeline stages in a background thread.

    Outcomes are recorded in scrape_runs (already started by the endpoint)
    and surfaced via /status — a background run has no HTTP response to
    fail with, so scrape_runs + alert emails are the only truth. Always
    releases the pipeline lock at the end.
    """
    try:
        run_pipeline_stages(stages)
        scrape_runs.finish_run("success")
        # M6 monitoring Item 3: anomaly checks on the finished run's counts
        # (zero ads discovered, removed-spike, zero new ads streak); emails
        # an anomaly alert if any trip. Best-effort, never fails the run.
        alert_mailer.check_and_alert(city)
        log.info("Completed run-task for %s using %s", city, source)
    except PipelineStageError as exc:
        log.exception("Pipeline FAILED for city %s (source: %s): %s", city, source, exc)
        try:
            scrape_runs.finish_run("failed", failed_stage=exc.stage, error=str(exc.original))
        except Exception as record_exc:
            log.error("Could not record failed run in scrape_runs: %s", record_exc)
        # M6 monitoring Item 3: failure alert email (best-effort, never raises)
        alert_mailer.send_pipeline_failure_alert(city, exc.stage, str(exc.original))
    except Exception as exc:
        # Safety net (e.g. finish_run itself failed): never exit the thread
        # leaving a zombie 'running' row unreported.
        log.exception("Pipeline run for city %s broke outside stages: %s", city, exc)
        try:
            scrape_runs.finish_run("failed", failed_stage="post-stages", error=str(exc))
        except Exception as record_exc:
            log.error("Could not record failed run in scrape_runs: %s", record_exc)
        alert_mailer.send_pipeline_failure_alert(city, "post-stages", str(exc))
    finally:
        _pipeline_lock.release()


@app.get("/run-task/{city}")
async def run_long_task(city: str):
    """Endpoint to trigger scrape, format and insert data in DB for a specific city.

    M7 P6: enqueue-and-return. The pipeline executes in a background
    thread; this handler responds immediately so the event loop, health
    checks and further requests stay alive during the run. Run outcome is
    tracked in scrape_runs and queried via /status (which the ts
    scheduler already does at VERIFY_TIME — M6 Item 7).
    Returns 409 when a run is already in progress in this container.
    """
    log.info("Received GET request to start scraping job for %s city", city)
    if not validate_city_slug(city):
        log.warning("City slug '%s' not found in cities.yaml (proceeding with env config)", city)
    display = get_display_name(city, city)
    # download_latest_lambda_file()
    # todays_cloud_data_file_exist = check_today_cloud_data_file_exist()
    # TODO implement flag skip LAMBDA_FILE
    todays_cloud_data_file_exist = False

    # M6 monitoring Item 2: run bookkeeping table (guard + run status rows)
    scrape_runs.ensure_scrape_runs_table()

    # Shared downstream stages (data formatting → email), run after either
    # the cloud raw-data file or a local scrape produced today's raw report.
    downstream_stages = [
        ("data_format_changer", lambda: cloud_data_formater_main(city)),
        ("df_cleaner", df_cleaner_main),
        ("db_worker", db_worker_main),
        ("analytics", analytics_main),
        ("aws_mailer", lambda: aws_mailer_main(city)),
    ]

    if todays_cloud_data_file_exist is True:
        last_cloud_file_name = get_todays_cloud_data_file_name()
        log.info(
            "Cloud scraper module data file: %s "
            "found will be used in "
            " data_formater_module ",
            last_cloud_file_name,
        )
        stages = downstream_stages
        source = "cloud ws file"
    else:
        # M6 monitoring Item 2: DB-based "already ran today" guard
        # (replaces the filesystem marker file check in check_lst_run_state).
        # Only successful runs count — a failed run may be retried same day.
        if scrape_runs.has_succeeded_today(city):
            log.info("EXIT: will not call ws_worker module because task was run last 24H")
            return {
                "message": "Local scraper job already has run,"
                " in last 24H will not run today again"
            }
        log.info("Running scrape_website task will create local ws file for %s (%s)", city, display)
        stages = [("web_scraper", lambda: scrape_website(city_slug=city))] + downstream_stages
        source = "locally scraped file"

    # M7 P6: overlap guard — one run at a time per container. 409 lets the
    # caller distinguish "busy" from "accepted".
    if not _pipeline_lock.acquire(blocking=False):
        log.warning("Rejected /run-task/%s: another pipeline run is in progress", city)
        raise HTTPException(
            status_code=409,
            detail="A pipeline run is already in progress; check /status",
        )

    # Record the run before returning so the caller gets a run_id and
    # /status immediately shows 'running'. If recording fails, the run
    # must not start silently (M6 Item 1 philosophy).
    try:
        run_id = scrape_runs.start_run(city)
        worker = threading.Thread(
            target=execute_pipeline,
            args=(city, stages, source),
            name=f"pipeline-{city}",
            daemon=True,
        )
        worker.start()
    except Exception as exc:
        _pipeline_lock.release()
        log.error("Failed to start background pipeline for %s: %s", city, exc)
        raise HTTPException(
            status_code=500, detail=f"Could not start pipeline run: {exc}"
        ) from exc

    log.info("Accepted /run-task/%s (run_id %s, source: %s); running in background", city, run_id, source)
    return {
        "message": (
            f"FAST_API: scrape {city} city apartments task accepted;"
            f" running in background using {source}"
        ),
        "run_id": run_id,
        "status_url": "/status",
    }


def check_today_cloud_data_file_exist() -> bool:
    """Checks if a cloud raw-data file for today exists
    (generated by AWS lambda scraper and downloaded from S3)."""
    cloud_file_folder = "local_lambda_raw_scraped_data"
    todays_date = datetime.today().strftime("%Y-%m-%d")
    log.info("Searching for cloud files with todays date: %s ", todays_date)
    if not os.path.exists(cloud_file_folder):
        log.error("Folder %s does not exist creating empty folder", cloud_file_folder)
        os.makedirs(cloud_file_folder)
    for file_name in os.listdir(cloud_file_folder):
        if todays_date in file_name:
            log.info("File %s containing today date %s found, ", file_name, todays_date)
            return True
    log.info(
        "File containing today date %s was not found, "
        "will try to find local scraper file",
        todays_date,
    )
    return False


def get_todays_cloud_data_file_name() -> str:
    """Returns the name of today's cloud raw-data file if present."""

    cloud_file_folder = "local_lambda_raw_scraped_data"
    todays_date = datetime.today().strftime("%Y-%m-%d")
    log.info("Searching for cloud scraper file  with todays date: %s ", todays_date)
    if not os.path.exists(cloud_file_folder):
        log.error("Folder %s does not exist creating empty folder ", cloud_file_folder)
        os.makedirs(cloud_file_folder)
    for file_name in os.listdir(cloud_file_folder):
        if todays_date in file_name:
            log.info("File %s containing todays date%s found", file_name, todays_date)
            return file_name


if __name__ == "__main__":
    uvicorn.run(app)
