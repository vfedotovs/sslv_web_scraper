"""Tests for ts.py trigger feedback loop (M6 monitoring Item 7)."""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

TS_PY = Path(__file__).parent.parent / "src" / "ts" / "ts.py"

spec = importlib.util.spec_from_file_location("ts_module", TS_PY)
ts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ts)

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")


def make_run(**overrides):
    run = {
        "status": "success", "started_at": f"{TODAY}T00:41:00",
        "failed_stage": None, "error": None,
        "new_ads": 3, "removed_ads": 2, "listed_table_rows": 61,
    }
    run.update(overrides)
    return run


# --- evaluate_run_status ---

def test_successful_todays_run_is_ok():
    problem, detail = ts.evaluate_run_status(make_run(), TODAY)
    assert problem is None
    assert "run succeeded" in detail


def test_running_run_is_ok_not_alerted():
    problem, detail = ts.evaluate_run_status(make_run(status="running"), TODAY)
    assert problem is None
    assert "in progress" in detail


def test_failed_run_is_problem():
    run = make_run(status="failed", failed_stage="db_worker", error="boom")
    problem, detail = ts.evaluate_run_status(run, TODAY)
    assert problem == "run failed"
    assert "db_worker" in detail


def test_yesterdays_run_means_never_started():
    run = make_run(started_at="2020-01-01T00:41:00")
    problem, detail = ts.evaluate_run_status(run, TODAY)
    assert problem == "run never started today"
    assert "2020-01-01" in detail


def test_no_recorded_run_is_problem():
    problem, _ = ts.evaluate_run_status(None, TODAY)
    assert problem == "no run recorded"


# --- verify_task ---

def test_verify_ok_sends_no_alert():
    with patch.object(ts, "get_run_status", return_value=make_run()), \
         patch.object(ts, "send_alert") as alert:
        ts.verify_task()
    alert.assert_not_called()


def test_verify_failed_run_alerts():
    run = make_run(status="failed", failed_stage="db_worker", error="boom")
    with patch.object(ts, "get_run_status", return_value=run), \
         patch.object(ts, "send_alert") as alert:
        ts.verify_task()
    subject, body = alert.call_args[0]
    assert "run failed" in subject
    assert "db_worker" in body


def test_verify_status_unreachable_alerts():
    with patch.object(ts, "get_run_status", return_value=None), \
         patch.object(ts, "send_alert") as alert:
        ts.verify_task()
    subject, _ = alert.call_args[0]
    assert "verification impossible" in subject


# --- get_run_status ---

def test_get_run_status_returns_city_entry():
    response = MagicMock()
    response.json.return_value = {"cities": {ts.city: make_run()}}
    with patch.object(ts.requests, "get", return_value=response):
        run = ts.get_run_status()
    assert run["status"] == "success"


def test_get_run_status_unreachable_returns_none():
    with patch.object(ts.requests, "get",
                      side_effect=requests.ConnectionError("refused")):
        assert ts.get_run_status() is None


# --- execute_task ---

def test_trigger_timeout_is_expected_no_alert():
    with patch.object(ts.requests, "get", side_effect=requests.Timeout()), \
         patch.object(ts, "send_alert") as alert:
        ts.execute_task()
    alert.assert_not_called()


def test_trigger_connection_refused_alerts():
    with patch.object(ts.requests, "get",
                      side_effect=requests.ConnectionError("refused")), \
         patch.object(ts, "send_alert") as alert:
        ts.execute_task()
    subject, body = alert.call_args[0]
    assert "trigger FAILED" in subject
    assert ts.city in subject
    assert "could not reach the ws container" in body


def test_trigger_http_500_logs_but_does_not_alert():
    """ws already alerts on pipeline failure (Item 3); no duplicate from ts."""
    response = MagicMock(status_code=500, text="pipeline failed")
    with patch.object(ts.requests, "get", return_value=response), \
         patch.object(ts, "send_alert") as alert:
        ts.execute_task()
    alert.assert_not_called()


# --- send_alert ---

def test_send_alert_never_raises():
    with patch.object(ts.boto3, "client", side_effect=Exception("no creds")):
        assert ts.send_alert("subj", "body") is False


def test_send_alert_sends_via_ses():
    client = MagicMock()
    client.send_email.return_value = {"MessageId": "abc"}
    with patch.object(ts.boto3, "client", return_value=client):
        assert ts.send_alert("subj", "body") is True
    kwargs = client.send_email.call_args.kwargs
    assert kwargs["Message"]["Subject"]["Data"] == "subj"
