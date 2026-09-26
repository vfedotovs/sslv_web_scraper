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
        with pytest.raises(RuntimeError, match="truncated or failed"):
            backup.verify_backup_in_s3("bucket", "db-backups/x.sql.gz")


def test_verify_passes_small_db_dump():
    """A 58-row staging DB dumps to 2.9 KB (2026-09-26); the old 10 KB
    default failed it and emailed an alert every night."""
    client = make_s3_client(head_response={"ContentLength": 2956})
    with patch.object(backup.boto3, "client", return_value=client):
        backup.verify_backup_in_s3("bucket", "db-backups/x.sql.gz")  # no raise


def test_verify_small_db_dump_with_rows_has_no_warnings():
    client = make_s3_client(head_response={"ContentLength": 2956})
    with patch.object(backup.boto3, "client", return_value=client):
        assert backup.verify_backup_in_s3(
            "bucket", "k", rows=(49, 9), previous=("prev", (48, 9))) == []


def test_verify_warns_when_dump_is_small_for_its_rows():
    """An estimate, so a log warning - not an alert email."""
    client = make_s3_client(head_response={"ContentLength": 2640})
    with patch.object(backup.boto3, "client", return_value=client):
        warnings = backup.verify_backup_in_s3("bucket", "k", rows=(900, 4100))
    assert warnings == ["s3://bucket/k is 2640 bytes for 5000 rows"
                        " (expected >= 26024 at 5 B/row)"]


def test_verify_fails_when_db_lost_rows_since_previous_backup():
    client = make_s3_client(head_response={"ContentLength": 50 * 1024})
    with patch.object(backup.boto3, "client", return_value=client):
        with pytest.raises(RuntimeError, match="the DB lost data: it had 30 rows"
                                               r".* vs 5000 in the previous backup"
                                               " s3://bucket/db-backups/prev"):
            backup.verify_backup_in_s3("bucket", "k", rows=(20, 10),
                                       previous=("db-backups/prev", (900, 4100)))


def test_verify_skips_row_drop_without_previous_counts():
    """Backups made before row counts were recorded have no metadata."""
    client = make_s3_client(head_response={"ContentLength": 50 * 1024})
    with patch.object(backup.boto3, "client", return_value=client):
        assert backup.verify_backup_in_s3("bucket", "k", rows=(20, 10),
                                          previous=("db-backups/prev", None)) == []


# --- row counts and metadata ---

def test_count_db_rows_parses_psql_output():
    result = MagicMock(returncode=0, stdout="49|9\n", stderr="")
    with patch.object(backup.subprocess, "run", return_value=result) as run, \
         patch.dict(os.environ, {"POSTGRES_PASSWORD": "secret"}):
        assert backup.count_db_rows() == (49, 9)
    assert run.call_args[0][0][0] == "psql"
    assert run.call_args[1]["env"]["PGPASSWORD"] == "secret"


@pytest.mark.parametrize("result", [
    MagicMock(returncode=1, stdout="", stderr='relation "listed_ads" does not exist'),
    MagicMock(returncode=0, stdout="garbage", stderr=""),
])
def test_count_db_rows_failure_returns_none(result):
    with patch.object(backup.subprocess, "run", return_value=result):
        assert backup.count_db_rows() is None


def test_count_db_rows_missing_psql_returns_none():
    with patch.object(backup.subprocess, "run", side_effect=FileNotFoundError("psql")):
        assert backup.count_db_rows() is None


def test_read_backup_rows_from_metadata():
    client = make_s3_client(head_response={
        "Metadata": {"env": "prod", "city": "ogre", "listed-ads": "49", "removed-ads": "9"}})
    with patch.object(backup.boto3, "client", return_value=client):
        assert backup.read_backup_rows("bucket", "k") == (49, 9)


def test_read_backup_rows_without_metadata_returns_none():
    client = make_s3_client(head_response={"Metadata": {}})
    with patch.object(backup.boto3, "client", return_value=client):
        assert backup.read_backup_rows("bucket", "k") is None


def test_upload_sends_metadata():
    client = MagicMock()
    with patch.object(backup.boto3, "client", return_value=client):
        backup.upload_to_s3("/tmp/f.sql.gz", "bucket", {"env": "prod"})
    assert client.upload_file.call_args[1]["ExtraArgs"] == {"Metadata": {"env": "prod"}}


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
    newest = ("db-backups/prev.sql.gz", None, 2900)
    with patch.object(backup, "count_db_rows", return_value=(49, 9)), \
         patch.object(backup, "backup_postgres", return_value=str(backup_file)), \
         patch.object(backup, "find_newest_backup", return_value=newest), \
         patch.object(backup, "read_backup_rows", return_value=(48, 9)), \
         patch.object(backup, "upload_to_s3", return_value="db-backups/k.sql.gz") as mock_up, \
         patch.object(backup, "verify_backup_in_s3", return_value=[]) as mock_verify, \
         patch.object(backup, "send_alert_email", alert), \
         patch.dict(os.environ, {"S3_BUCKET": "test-bucket", "ENV": "staging",
                                 "CITY": "ogre"}):
        backup.run_backup()
    assert mock_up.call_args[0][2] == {"env": "staging", "city": "ogre",
                                       "listed-ads": "49", "removed-ads": "9"}
    mock_verify.assert_called_once_with(
        "test-bucket", "db-backups/k.sql.gz", (49, 9),
        ("db-backups/prev.sql.gz", (48, 9)))
    alert.assert_not_called()
    assert not backup_file.exists()  # cleaned up


def test_run_backup_survives_unreadable_previous_backup(tmp_path):
    backup_file = tmp_path / "pg_backup_test.sql.gz"
    backup_file.write_bytes(b"x" * 1024)
    alert = MagicMock(return_value=True)
    with patch.object(backup, "count_db_rows", return_value=None), \
         patch.object(backup, "backup_postgres", return_value=str(backup_file)), \
         patch.object(backup, "find_newest_backup", side_effect=Exception("AccessDenied")), \
         patch.object(backup, "upload_to_s3", return_value="db-backups/k.sql.gz") as mock_up, \
         patch.object(backup, "verify_backup_in_s3", return_value=[]) as mock_verify, \
         patch.object(backup, "send_alert_email", alert), \
         patch.dict(os.environ, {"S3_BUCKET": "test-bucket", "ENV": "prod", "CITY": "ogre"}):
        backup.run_backup()
    assert mock_up.call_args[0][2] == {"env": "prod", "city": "ogre"}  # no row counts
    mock_verify.assert_called_once_with("test-bucket", "db-backups/k.sql.gz", None, None)
    alert.assert_not_called()


def test_run_backup_verify_failure_sends_alert():
    alert = MagicMock(return_value=True)
    with patch.object(backup, "count_db_rows", return_value=(49, 9)), \
         patch.object(backup, "find_newest_backup", return_value=None), \
         patch.object(backup, "backup_postgres", return_value="/tmp/fake.sql.gz"), \
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
    assert "uploaded but failed verification" in body


# --- send_alert_email ---

def test_send_alert_email_never_raises():
    with patch.object(backup.boto3, "client", side_effect=Exception("no creds")):
        assert backup.send_alert_email("subj", "body") is False


# --- pg_dump invocation ---

def test_pg_dump_uses_clean_if_exists(monkeypatch):
    """Dumps must drop objects before recreating them, so a restore over an
    existing DB neither fails on CREATE nor appends duplicate rows."""
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
    ok = MagicMock(returncode=0, stderr="")
    with patch.object(backup.subprocess, "run", return_value=ok) as run:
        backup.backup_postgres()
    pg_dump_args = run.call_args_list[0][0][0]
    assert pg_dump_args[0] == "pg_dump"
    assert "--clean" in pg_dump_args and "--if-exists" in pg_dump_args
    assert run.call_args_list[0][1]["env"]["PGPASSWORD"] == "secret"
