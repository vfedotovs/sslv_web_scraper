"""Tests for backup-svc backup.py verification + staleness alerts (M6 Item 4)."""
import datetime
import importlib.util
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

BACKUP_PY = Path(__file__).parent.parent / "src" / "backup-svc" / "backup.py"

spec = importlib.util.spec_from_file_location("backup_svc_backup", BACKUP_PY)
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


def make_s3_client(head_response=None, head_error=None, pages=None):
    client = MagicMock()
    if head_error is not None:
        client.head_object.side_effect = head_error
    else:
        client.head_object.return_value = head_response or {}
    paginator = MagicMock()
    paginator.paginate.return_value = pages or []
    client.get_paginator.return_value = paginator
    return client


# --- verify_backup_in_s3 ---

def test_verify_passes_for_plausible_size():
    client = make_s3_client(head_response={"ContentLength": 50 * 1024})
    with patch.object(backup.boto3, "client", return_value=client):
        backup.verify_backup_in_s3("bucket", "db-backups/x.sql.gz")  # no raise


def test_verify_fails_when_object_missing():
    client = make_s3_client(head_error=Exception("404 Not Found"))
    with patch.object(backup.boto3, "client", return_value=client):
        with pytest.raises(RuntimeError, match="not found"):
            backup.verify_backup_in_s3("bucket", "db-backups/x.sql.gz")


def test_verify_fails_when_object_too_small():
    client = make_s3_client(head_response={"ContentLength": 100})
    with patch.object(backup.boto3, "client", return_value=client):
        with pytest.raises(RuntimeError, match="near-empty dump"):
            backup.verify_backup_in_s3("bucket", "db-backups/x.sql.gz")


# --- find_newest_backup ---

def test_find_newest_backup_picks_latest():
    now = datetime.datetime.now(datetime.timezone.utc)
    pages = [{"Contents": [
        {"Key": "db-backups/old.sql.gz", "LastModified": now - datetime.timedelta(days=2), "Size": 111},
        {"Key": "db-backups/new.sql.gz", "LastModified": now, "Size": 222},
    ]}]
    client = make_s3_client(pages=pages)
    with patch.object(backup.boto3, "client", return_value=client):
        key, last_modified, size = backup.find_newest_backup("bucket")
    assert key == "db-backups/new.sql.gz"
    assert size == 222


def test_find_newest_backup_empty_bucket_returns_none():
    client = make_s3_client(pages=[{}])
    with patch.object(backup.boto3, "client", return_value=client):
        assert backup.find_newest_backup("bucket") is None


# --- check_backup_staleness ---

def run_staleness(newest, find_error=None):
    """Run check_backup_staleness with mocked finder + alert; return alert mock and exit code."""
    alert = MagicMock(return_value=True)
    finder = MagicMock(return_value=newest, side_effect=find_error)
    exit_code = None
    with patch.object(backup, "find_newest_backup", finder), \
         patch.object(backup, "send_alert_email", alert):
        try:
            backup.check_backup_staleness()
        except SystemExit as e:
            exit_code = e.code
    return alert, exit_code


def test_staleness_fresh_backup_no_alert():
    now = datetime.datetime.now(datetime.timezone.utc)
    alert, exit_code = run_staleness(("db-backups/x.sql.gz", now - datetime.timedelta(hours=2), 999999))
    alert.assert_not_called()
    assert exit_code is None


def test_staleness_old_backup_alerts_and_exits():
    now = datetime.datetime.now(datetime.timezone.utc)
    alert, exit_code = run_staleness(("db-backups/x.sql.gz", now - datetime.timedelta(hours=48), 999999))
    assert exit_code == 1
    subject, body = alert.call_args[0]
    assert "STALE" in subject
    assert "db-backups/x.sql.gz" in body


def test_staleness_no_backups_alerts_and_exits():
    alert, exit_code = run_staleness(None)
    assert exit_code == 1
    subject, _ = alert.call_args[0]
    assert "NO backups" in subject


def test_staleness_listing_failure_alerts_and_exits():
    alert, exit_code = run_staleness(None, find_error=Exception("AccessDenied"))
    assert exit_code == 1
    subject, body = alert.call_args[0]
    assert "staleness check FAILED" in subject
    assert "AccessDenied" in body


# --- run_backup failure alerting ---

def test_run_backup_failure_sends_alert_and_exits():
    alert = MagicMock(return_value=True)
    with patch.object(backup, "backup_postgres", side_effect=Exception("pg_dump: connection refused")), \
         patch.object(backup, "send_alert_email", alert):
        with pytest.raises(SystemExit) as excinfo:
            backup.run_backup()
    assert excinfo.value.code == 1
    subject, body = alert.call_args[0]
    assert "FAILED at pg_dump" in subject
    assert "connection refused" in body


def test_run_backup_success_verifies_and_sends_no_alert(tmp_path):
    backup_file = tmp_path / "pg_backup_test.sql.gz"
    backup_file.write_bytes(b"x" * 1024)
    alert = MagicMock(return_value=True)
    with patch.object(backup, "backup_postgres", return_value=str(backup_file)), \
         patch.object(backup, "upload_to_s3", return_value="db-backups/k.sql.gz") as mock_up, \
         patch.object(backup, "verify_backup_in_s3") as mock_verify, \
         patch.object(backup, "send_alert_email", alert), \
         patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}):
        backup.run_backup()
    mock_up.assert_called_once()
    mock_verify.assert_called_once_with("test-bucket", "db-backups/k.sql.gz")
    alert.assert_not_called()
    assert not backup_file.exists()  # cleaned up


def test_run_backup_verify_failure_sends_alert():
    alert = MagicMock(return_value=True)
    with patch.object(backup, "backup_postgres", return_value="/tmp/fake.sql.gz"), \
         patch.object(backup, "upload_to_s3", return_value="db-backups/k.sql.gz"), \
         patch.object(backup, "verify_backup_in_s3",
                      side_effect=RuntimeError("near-empty dump")), \
         patch.object(backup, "send_alert_email", alert), \
         patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}):
        with pytest.raises(SystemExit):
            backup.run_backup()
    subject, body = alert.call_args[0]
    assert "FAILED at s3_verify" in subject
    assert "near-empty dump" in body


# --- send_alert_email ---

def test_send_alert_email_never_raises():
    with patch.object(backup.boto3, "client", side_effect=Exception("no creds")):
        assert backup.send_alert_email("subj", "body") is False
