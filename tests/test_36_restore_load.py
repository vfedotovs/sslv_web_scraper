"""Restores must load what the live restore loads, and fail like it (P-2).

1. `--scratch` counted ERROR lines and only warned, so `make test-restore`
   passed dumps that the live restore (ON_ERROR_STOP, one transaction) rejects.
2. The trixie-based backup image wrote pg_dump 17 dumps with
   `SET transaction_timeout = 0;`, which the postgres:15 city DBs reject: no
   backup taken before B-3 could be restored live.

A stub `docker` plays a PostgreSQL 15 server: its psql rejects that SET and a
broken statement, reports server_version_num, and records every SQL it loads.
"""
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "restore_db_city.sh"

DOCKER_STUB = r"""#!/bin/bash
# Records each SQL load (stdin of `psql ... -f -`) as $LOADS/<n>.sql.
args=" $* "
case "$1" in
  run) echo fake-container-id; exit 0 ;;
  rm|stop|start) exit 0 ;;
  inspect) echo true; exit 0 ;;
esac
[[ "$args" == *" pg_isready "* ]] && exit 0
[[ "$args" == *" pg_dump "* ]] && { echo "-- safety dump"; exit 0; }
if [[ "$args" == *" psql "* ]]; then
  [[ "$args" == *"SHOW server_version_num"* ]] && { echo "${PG_SERVER_VERSION:-150019}"; exit 0; }
  [[ "$args" == *"SELECT tablename"* ]] && { printf 'listed_ads\nremoved_ads\n'; exit 0; }
  [[ "$args" == *"SELECT count(*)"* ]] && { echo 5; exit 0; }
  sql=$(cat)
  if [[ "$sql" == *'\restrict probe'* ]]; then
    [[ -n "${PSQL_NO_RESTRICT:-}" ]] && { echo 'invalid command \restrict' >&2; exit 1; }
    exit 0
  fi
  n=$(ls "$LOADS" | wc -l | tr -d ' ')
  printf '%s\n' "$sql" > "$LOADS/$n.sql"
  if [[ -n "${PSQL_NO_RESTRICT:-}" && "$sql" == *'\restrict '* ]]; then
    echo 'psql:<stdin>:5: invalid command \restrict' >&2; exit 3
  fi
  if [[ "$sql" == *"SET transaction_timeout"* && "${PG_SERVER_VERSION:-150019}" -lt 170000 ]]; then
    echo 'psql:<stdin>:13: ERROR:  unrecognized configuration parameter "transaction_timeout"' >&2; exit 3
  fi
  if [[ "$sql" == *"BROKEN"* ]]; then
    echo 'psql:<stdin>:20: ERROR:  syntax error at or near "BROKEN"' >&2; exit 3
  fi
  exit 0
fi
exit 0
"""

# `aws s3 ls <prefix> --recursive` lists the keys in $S3_KEYS under that prefix;
# `aws s3 cp s3://... <file>` serves $DUMP_SRC gzipped.
AWS_STUB = r"""#!/bin/bash
echo "$@" >> "$AWS_CALLS"
case "$1 $2" in
  "s3 ls") prefix="${3#s3://*/}"
           grep "^${prefix}" "$S3_KEYS" | while read -r k; do echo "2026-10-11 02:00:04 3743 $k"; done
           exit 0 ;;
  "s3 cp") gzip -c "$DUMP_SRC" > "$4"; exit 0 ;;
esac
exit 0
"""

BODY = """SET statement_timeout = 0;
SET client_encoding = 'UTF8';
CREATE TABLE public.listed_ads (url_hash text, price integer);
COPY public.listed_ads (url_hash, price) FROM stdin;
abc\t100000
\\.
"""

# Header lines as pg_dump writes them (the \\restrict key is random per dump).
PG17_DUMP = ("--\n-- Dumped by pg_dump version 17.11 (Debian 17.11-0+deb13u1)\n\n"
             "\\restrict Kl0lHIGJhG\n\nSET transaction_timeout = 0;\n" + BODY
             + "\\unrestrict Kl0lHIGJhG\n")
PG15_DUMP = ("--\n-- Dumped by pg_dump version 15.19 (Debian 15.19-0+deb12u1)\n\n"
             "\\restrict UYz7WCFbtQ\n\n" + BODY + "\\unrestrict UYz7WCFbtQ\n")


@pytest.fixture
def host(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(DOCKER_STUB)
    (bin_dir / "docker").chmod(0o755)
    (bin_dir / "aws").write_text(AWS_STUB)
    (bin_dir / "aws").chmod(0o755)
    (tmp_path / "s3_keys.txt").write_text("")
    loads = tmp_path / "loads"
    loads.mkdir()
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", LOADS=str(loads),
               LOG_FILE=str(tmp_path / "restore.log"), AWS_CALLS=str(tmp_path / "aws_calls.txt"),
               S3_KEYS=str(tmp_path / "s3_keys.txt"), DUMP_SRC=str(tmp_path / "s3_dump.sql"))
    env.pop("PSQL_NO_RESTRICT", None)
    env.pop("PG_SERVER_VERSION", None)
    return tmp_path, env


def restore(host, dump_text, *args, **extra_env):
    cwd, env = host
    dump = cwd / "dump.sql"
    dump.write_text(dump_text)
    result = subprocess.run(["bash", str(SCRIPT), "--city", "ogre", "--env", "staging",
                             "--file", str(dump), *args],
                            capture_output=True, text=True, timeout=120, cwd=cwd,
                            env=dict(env, **extra_env))
    loads = sorted((cwd / "loads").glob("*.sql"), key=lambda p: int(p.stem))
    return result, [p.read_text() for p in loads]


# --- scratch ---

def test_scratch_loads_a_pg17_dump_into_postgres_15(host):
    result, loads = restore(host, PG17_DUMP, "--scratch")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "dropping SET transaction_timeout" in result.stdout
    assert len(loads) == 1
    assert "transaction_timeout" not in loads[0]
    assert "SET statement_timeout = 0;" in loads[0] and "\\restrict Kl0lHIGJhG" in loads[0]


def test_scratch_keeps_the_setting_for_postgres_17(host):
    result, loads = restore(host, PG17_DUMP, "--scratch", PG_SERVER_VERSION="170006")
    assert result.returncode == 0
    assert "SET transaction_timeout = 0;" in loads[0]
    assert "dropping" not in result.stdout


def test_scratch_loads_a_pg15_dump_unchanged(host):
    result, loads = restore(host, PG15_DUMP, "--scratch")
    assert result.returncode == 0
    assert loads[0].rstrip("\n") == PG15_DUMP.rstrip("\n")


def test_scratch_fails_on_the_first_error(host):
    """It used to log 'psql reported 1 error(s)' and pass."""
    result, _ = restore(host, PG15_DUMP.replace("SET client_encoding", "BROKEN client_encoding"),
                        "--scratch")
    assert result.returncode == 1
    assert "Scratch restore FAILED for ogre" in result.stdout
    assert 'syntax error at or near "BROKEN"' in result.stdout
    assert "Restored tables" not in result.stdout


def test_scratch_loads_in_one_stopping_transaction():
    # Same flags as the live restore.
    script = SCRIPT.read_text()
    scratch = script[script.index("scratch_restore() {"):script.index("# report_tables")]
    assert "-v ON_ERROR_STOP=1 --single-transaction -f -" in scratch


def test_scratch_strips_restrict_for_an_old_psql(host):
    result, loads = restore(host, PG17_DUMP, "--scratch", PSQL_NO_RESTRICT="1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "\\restrict" not in loads[0] and "\\unrestrict" not in loads[0]
    assert "transaction_timeout" not in loads[0]


# --- live ---

def test_live_restore_loads_a_pg17_dump_into_postgres_15(host):
    result, loads = restore(host, PG17_DUMP, "--yes")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Restore completed for ogre" in result.stdout
    assert loads[0].startswith("SET client_min_messages = warning;\nDROP SCHEMA public CASCADE;")
    assert "transaction_timeout" not in loads[0]
    assert "COPY public.listed_ads" in loads[0]


def test_live_restore_still_rolls_back_on_error(host):
    result, _ = restore(host, PG15_DUMP.replace("SET client_encoding", "BROKEN client_encoding"),
                        "--yes")
    assert result.returncode == 1
    assert "Restore FAILED for ogre and was rolled back" in result.stdout


# --- prepare-init (src/db is FROM postgres:15, init runs with ON_ERROR_STOP) ---

def test_prepare_init_writes_a_dump_postgres_15_can_run(host):
    cwd, _ = host
    result, _ = restore(host, PG17_DUMP, "--prepare-init")
    assert result.returncode == 0, result.stdout + result.stderr
    written = list((cwd / "src" / "db").glob("pg_backup_*.sql"))
    assert len(written) == 1
    text = written[0].read_text()
    assert "transaction_timeout" not in text and "COPY public.listed_ads" in text


# --- --date picks the newest backup of that day ---

def restore_from_s3(host, *args):
    cwd, env = host
    (cwd / "s3_keys.txt").write_text("\n".join([
        "db-backups/2026/10/11/pg_backup_20261011_020003.sql.gz",
        "db-backups/2026/10/12/pg_backup_20261012_020005.sql.gz",
        "db-backups/2026/10/12/pg_backup_20261012_174534.sql.gz",
    ]) + "\n")
    (cwd / "s3_dump.sql").write_text(PG17_DUMP)
    result = subprocess.run(["bash", str(SCRIPT), "--city", "ogre", "--env", "staging", *args],
                            capture_output=True, text=True, timeout=120, cwd=cwd, env=env)
    calls = (cwd / "aws_calls.txt").read_text().splitlines() if (cwd / "aws_calls.txt").exists() else []
    return result, [c for c in calls if c.startswith("s3 cp ")]


def test_date_restores_the_newest_backup_of_that_day(host):
    """The key used to be guessed as pg_backup_2026_10_12.sql.gz, which never exists."""
    result, downloads = restore_from_s3(host, "--date", "2026_10_12", "--scratch")
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(downloads) == 1
    assert "db-backups/2026/10/12/pg_backup_20261012_174534.sql.gz" in downloads[0]


def test_date_without_a_backup_fails(host):
    result, downloads = restore_from_s3(host, "--date", "2026_10_09", "--scratch")
    assert result.returncode == 1
    assert "No backup for 2026_10_09" in result.stdout
    assert downloads == []


def test_date_must_be_yyyy_mm_dd(host):
    result, downloads = restore_from_s3(host, "--date", "2026-10-12", "--scratch")
    assert result.returncode == 1
    assert "--date must be YYYY_MM_DD" in result.stdout
    assert downloads == []
