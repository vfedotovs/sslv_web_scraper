"""Tests for M7 Problem 6: pipeline off the request path.

/run-task/{city} must enqueue the pipeline into a background thread and
return immediately (with a run_id and /status pointer); an in-process
lock rejects overlapping runs with 409; the background executor records
success/failure in scrape_runs and always releases the lock.
"""
import asyncio
import os
import sys
import threading
import time

import pytest

# container layout imports (app...)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "ws"))

from fastapi import HTTPException

from app import main


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture(autouse=True)
def pipeline_lock_guard():
    """Keep the module-level lock clean across tests."""
    if main._pipeline_lock.locked():
        main._pipeline_lock.release()
    yield
    wait_for(lambda: not main._pipeline_lock.locked())
    if main._pipeline_lock.locked():
        main._pipeline_lock.release()


@pytest.fixture
def calls(monkeypatch):
    """Patch scrape_runs/alert_mailer/stages; record interactions."""
    record = {"start": [], "finish": [], "failure_alerts": [], "anomaly_checks": []}
    monkeypatch.setattr(main.scrape_runs, "ensure_scrape_runs_table", lambda: None)
    monkeypatch.setattr(main.scrape_runs, "has_succeeded_today", lambda city: False)
    monkeypatch.setattr(
        main.scrape_runs, "start_run",
        lambda city: (record["start"].append(city), 42)[1],
    )
    monkeypatch.setattr(
        main.scrape_runs, "finish_run",
        lambda status, failed_stage=None, error=None: record["finish"].append(
            (status, failed_stage, error)
        ),
    )
    monkeypatch.setattr(
        main.alert_mailer, "send_pipeline_failure_alert",
        lambda city, stage, error: record["failure_alerts"].append((city, stage, error)),
    )
    monkeypatch.setattr(
        main.alert_mailer, "check_and_alert",
        lambda city: record["anomaly_checks"].append(city),
    )
    for stage_func in (
        "scrape_website", "cloud_data_formater_main", "df_cleaner_main",
        "db_worker_main", "analytics_main", "aws_mailer_main",
    ):
        monkeypatch.setattr(main, stage_func, lambda *a, **kw: None)
    return record


# --- endpoint returns immediately -------------------------------------------------

def test_endpoint_returns_while_pipeline_still_running(monkeypatch, calls):
    started = threading.Event()
    release = threading.Event()

    def slow_scrape(city_slug=None):
        started.set()
        release.wait(timeout=5)

    monkeypatch.setattr(main, "scrape_website", slow_scrape)

    response = asyncio.run(main.run_long_task("ogre"))

    # response arrived before the pipeline finished
    assert "accepted" in response["message"]
    assert response["run_id"] == 42
    assert response["status_url"] == "/status"
    assert started.wait(timeout=5)
    assert main._pipeline_lock.locked()   # run still in progress
    assert calls["finish"] == []          # not finished yet

    release.set()
    assert wait_for(lambda: calls["finish"] == [("success", None, None)])
    assert wait_for(lambda: not main._pipeline_lock.locked())
    assert calls["anomaly_checks"] == ["ogre"]


def test_second_call_while_running_returns_409(monkeypatch, calls):
    started = threading.Event()
    release = threading.Event()

    def slow_scrape(city_slug=None):
        started.set()
        release.wait(timeout=5)

    monkeypatch.setattr(main, "scrape_website", slow_scrape)
    asyncio.run(main.run_long_task("ogre"))
    assert started.wait(timeout=5)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(main.run_long_task("ogre"))
    assert exc_info.value.status_code == 409
    assert "/status" in exc_info.value.detail
    # busy rejection must not start a second run
    assert calls["start"] == ["ogre"]

    release.set()


def test_already_succeeded_today_does_not_start_run(monkeypatch, calls):
    monkeypatch.setattr(main.scrape_runs, "has_succeeded_today", lambda city: True)
    response = asyncio.run(main.run_long_task("ogre"))
    assert "already has run" in response["message"]
    assert calls["start"] == []
    assert not main._pipeline_lock.locked()


def test_start_run_failure_releases_lock_and_returns_500(monkeypatch, calls):
    def broken_start(city):
        raise RuntimeError("db down")

    monkeypatch.setattr(main.scrape_runs, "start_run", broken_start)
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(main.run_long_task("ogre"))
    assert exc_info.value.status_code == 500
    assert not main._pipeline_lock.locked()


# --- background executor -----------------------------------------------------------

def test_execute_pipeline_success_records_and_releases(calls):
    main._pipeline_lock.acquire()
    main.execute_pipeline("ogre", [("noop", lambda: None)], "test source")
    assert calls["finish"] == [("success", None, None)]
    assert calls["anomaly_checks"] == ["ogre"]
    assert not main._pipeline_lock.locked()


def test_execute_pipeline_stage_failure_records_and_alerts(calls):
    def boom():
        raise ValueError("kaboom")

    main._pipeline_lock.acquire()
    main.execute_pipeline("ogre", [("web_scraper", boom)], "test source")
    assert calls["finish"] == [("failed", "web_scraper", "kaboom")]
    assert calls["failure_alerts"] == [("ogre", "web_scraper", "kaboom")]
    assert calls["anomaly_checks"] == []
    assert not main._pipeline_lock.locked()


def test_execute_pipeline_finish_run_crash_still_releases_lock(monkeypatch, calls):
    def broken_finish(status, failed_stage=None, error=None):
        raise RuntimeError("scrape_runs unavailable")

    monkeypatch.setattr(main.scrape_runs, "finish_run", broken_finish)
    main._pipeline_lock.acquire()
    main.execute_pipeline("ogre", [("noop", lambda: None)], "test source")
    # safety net alerted and the lock is free for the next run
    assert calls["failure_alerts"] and calls["failure_alerts"][0][1] == "post-stages"
    assert not main._pipeline_lock.locked()
