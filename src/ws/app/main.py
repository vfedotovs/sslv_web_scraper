#!/usr/bin/env python3
"""
This is entry point for module that provides basic API interface which will trigger web scrape job for specific city.

This module contains functions:
- home
- async run_long_task
- check_today_cloud_data_file_exist
- get_todays_cloud_data_file_name
- check_lst_run_state

"""

from datetime import datetime
import logging
import logging.handlers as handlers
from logging.handlers import RotatingFileHandler
import os
import sys
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


@app.get("/run-task/{city}")
async def run_long_task(city: str):
    """Endpoint to trigger scrape, format and insert data in DB for a specific city.
    Phase 3: city param fully wired for report naming across pipeline.
    Example verification (Item 10): curl http://localhost:8000/run-task/jurmala
    Then check data/jurmala-raw-data-report-*.txt and logs for correct city files.
    """
    log.info("Received GET request to start scraping job for %s city", city)
    if not validate_city_slug(city):
        log.warning("City slug '%s' not found in cities.yaml (proceeding with env config)", city)
    display = get_display_name(city, city)
    # download_latest_lambda_file()
    # todays_cloud_data_file_exist = check_today_cloud_data_file_exist()
    # TODO implement flag skip LAMBDA_FILE
    todays_cloud_data_file_exist = False

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
        result_message = (
            f"FAST_API: scrape {city} city apartments"
            " task using cloud ws file run completed"
        )
    else:
        lst_run_state = check_lst_run_state(city)
        if lst_run_state:
            log.info("EXIT: will not call ws_worker module because task was run last 24H")
            return {
                "message": "Local scraper job already has run,"
                " in last 24H will not run today again"
            }
        log.info("Running scrape_website task will create local ws file for %s (%s)", city, display)
        stages = [("web_scraper", lambda: scrape_website(city_slug=city))] + downstream_stages
        source = "locally scraped file"
        result_message = (
            f"FAST_API: scrape {city} city apartments "
            "task using local scrape job was completed"
        )

    # M6 monitoring Item 1: single pipeline-level catch. A failed stage now
    # fails the whole run and returns HTTP 500 instead of pretending success.
    try:
        run_pipeline_stages(stages)
    except PipelineStageError as exc:
        log.exception("Pipeline FAILED for city %s (source: %s): %s", city, source, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    log.info("Completed /run-task/%s using %s", city, source)
    return {"message": result_message}


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


def check_lst_run_state(city_name) -> bool:
    """
    Returns true if a {city}-raw-data-report-YYYY-MM-DD.txt file
    with today's date exists in the data/ folder.
    """
    todays_date = datetime.today().strftime("%Y-%m-%d")
    target_filename = city_name + "-raw-data-report-" + todays_date + ".txt"
    if not os.path.exists("data"):
        os.makedirs("data")
    for filename in os.listdir("data"):
        if filename == target_filename:
            log.info("File %s found, task for %s has run today", target_filename, city_name)
            return True
    log.info(
        "File %s was not found, running scrape task for %s city", target_filename, city_name
    )
    return False


if __name__ == "__main__":
    uvicorn.run(app)
