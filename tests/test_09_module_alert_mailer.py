"""Tests for alert_mailer module (M6 monitoring Item 3)."""
import os
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

# alert_mailer imports "app.wsmodules.scrape_runs" (container layout), so
# make src/ws importable the same way the ws container does.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "ws"))

from app.wsmodules import alert_mailer


def make_run(**overrides):
    run = {
        "run_id": 1, "city": "ogre", "status": "success",
        "started_at": datetime(2026, 7, 12, 0, 41), "finished_at": None,
        "failed_stage": None, "error": None,
        "pages_fetched": 2, "urls_discovered": 63, "new_ads": 3,
        "still_listed_ads": 58, "removed_ads": 2,
        "listed_table_rows": 61, "removed_table_rows": 940,
    }
    run.update(overrides)
    return run


# --- check_run_anomalies ---

def test_healthy_run_has_no_anomalies():
    assert alert_mailer.check_run_anomalies([make_run()]) == []


def test_empty_runs_list_has_no_anomalies():
    assert alert_mailer.check_run_anomalies([]) == []


def test_zero_urls_discovered_is_anomaly():
    anomalies = alert_mailer.check_run_anomalies([make_run(urls_discovered=0)])
    assert len(anomalies) == 1
    assert "Discovered ads == 0" in anomalies[0]


def test_removed_spike_is_anomaly():
    # 40 removed of 100 pre-run rows = 40% > default 30% threshold
    run = make_run(still_listed_ads=60, removed_ads=40)
    anomalies = alert_mailer.check_run_anomalies([run])
    assert len(anomalies) == 1
    assert "40%" in anomalies[0]


def test_removed_below_threshold_is_not_anomaly():
    # 20 removed of 100 pre-run rows = 20% < 30% threshold
    run = make_run(still_listed_ads=80, removed_ads=20)
    assert alert_mailer.check_run_anomalies([run]) == []


def test_zero_new_ads_streak_is_anomaly():
    runs = [make_run(new_ads=0) for _ in range(alert_mailer.ALERT_ZERO_NEW_RUNS)]
    anomalies = alert_mailer.check_run_anomalies(runs)
    assert len(anomalies) == 1
    assert "Zero new ads" in anomalies[0]


def test_zero_new_ads_short_streak_is_not_anomaly():
    runs = [make_run(new_ads=0) for _ in range(alert_mailer.ALERT_ZERO_NEW_RUNS - 1)]
    assert alert_mailer.check_run_anomalies(runs) == []


def test_zero_new_ads_streak_ignores_failed_runs():
    # failed runs (new_ads None) between successes must not break the streak
    runs = [
        make_run(new_ads=0),
        make_run(status="failed", new_ads=None),
        make_run(new_ads=0),
        make_run(new_ads=0),
    ]
    anomalies = alert_mailer.check_run_anomalies(runs)
    assert any("Zero new ads" in a for a in anomalies)


def test_streak_broken_by_run_with_new_ads():
    runs = [make_run(new_ads=0), make_run(new_ads=0), make_run(new_ads=5)]
    assert alert_mailer.check_run_anomalies(runs) == []


# --- send_alert_email ---

def test_send_alert_email_success():
    client = MagicMock()
    client.send_email.return_value = {"MessageId": "abc-123"}
    with patch.object(alert_mailer.boto3, "client", return_value=client):
        assert alert_mailer.send_alert_email("subj", "body") is True
    kwargs = client.send_email.call_args.kwargs
    assert kwargs["Message"]["Subject"]["Data"] == "subj"
    assert kwargs["Message"]["Body"]["Text"]["Data"] == "body"


def test_send_alert_email_never_raises():
    with patch.object(alert_mailer.boto3, "client", side_effect=Exception("no creds")):
        assert alert_mailer.send_alert_email("subj", "body") is False


# --- send_pipeline_failure_alert ---

def test_failure_alert_subject_and_body():
    with patch.object(alert_mailer, "send_alert_email", return_value=True) as mock_send, \
         patch.object(alert_mailer, "format_recent_runs", return_value="history"):
        alert_mailer.send_pipeline_failure_alert("ogre", "db_worker", "conn refused")
    subject, body = mock_send.call_args[0]
    assert subject == "SSLV ALERT: ogre pipeline FAILED at db_worker"
    assert "FAILED: ogre — db_worker — conn refused" in body
    assert "history" in body


def test_failure_alert_survives_history_query_failure():
    with patch.object(alert_mailer, "send_alert_email", return_value=True) as mock_send, \
         patch.object(alert_mailer, "format_recent_runs", side_effect=Exception("db down")):
        alert_mailer.send_pipeline_failure_alert("ogre", "db_worker", "boom")
    _, body = mock_send.call_args[0]
    assert "Scrape run history unavailable." in body


# --- check_and_alert ---

def test_check_and_alert_sends_email_when_anomalies():
    runs = [make_run(urls_discovered=0)]
    with patch.object(alert_mailer, "get_recent_runs", return_value=runs), \
         patch.object(alert_mailer, "format_recent_runs", return_value="history"), \
         patch.object(alert_mailer, "send_alert_email", return_value=True) as mock_send:
        anomalies = alert_mailer.check_and_alert("ogre")
    assert len(anomalies) == 1
    subject, body = mock_send.call_args[0]
    assert subject == "SSLV ANOMALY: ogre — 1 check(s) tripped"
    assert "Discovered ads == 0" in body


def test_check_and_alert_silent_when_healthy():
    with patch.object(alert_mailer, "get_recent_runs", return_value=[make_run()]), \
         patch.object(alert_mailer, "send_alert_email") as mock_send:
        assert alert_mailer.check_and_alert("ogre") == []
    mock_send.assert_not_called()


def test_check_and_alert_never_raises():
    with patch.object(alert_mailer, "get_recent_runs", side_effect=Exception("db down")):
        assert alert_mailer.check_and_alert("ogre") == []
