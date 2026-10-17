"""A staging backup/restore must never touch a prod bucket.

Regression tests for the 2026-09-21 incident: `make backup-all M6_ENV=staging`
uploaded the staging DBs into the sslv-prod-* buckets and pruned real prod
backups. `.env.<city>` is sourced with `set -a` for DB credentials, and its
legacy single-city values (ENV=prod, S3_BUCKET=sslv-prod-<city>-db-backups)
overwrote the script's own ENV and redirected every upload.

The scripts are driven with stub `aws`/`docker` commands on PATH, so nothing
here talks to AWS or Docker.
"""
import os
import re
import subprocess
from pathlib import Path
from typing import NamedTuple

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
BACKUP_SCRIPT = SCRIPTS_DIR / "backup_db_city.sh"
RESTORE_SCRIPT = SCRIPTS_DIR / "restore_db_city.sh"

# What a staging host really has on disk: a per-city env file left over from
# the single-city M5 setup, naming the prod bucket.
ENV_CITY_FILE = """POSTGRES_PASSWORD=secret
DB_USER=new_docker_user
DB_NAME=new_docker_db
ENV=prod
S3_BUCKET=sslv-prod-ogre-db-backups
"""

AWS_STUB = """#!/bin/bash
# Records every call, and answers the few the scripts need.
echo "$@" >> "$AWS_CALLS"
case "$1 $2" in
  "s3 cp")  [[ "$3" == s3://* ]] && printf 'fake dump' > "$4"; exit 0 ;;
  "s3 ls")  exit 0 ;;                 # no objects: prune finds nothing
  *) exit 0 ;;
esac
"""

DOCKER_STUB = """#!/bin/bash
# `docker exec ... pg_dump ...` -> a plausible dump on stdout
for arg in "$@"; do
  if [[ "$arg" == pg_dump ]]; then
    echo "-- fake pg_dump output"
    echo "CREATE TABLE listed_ads (id integer);"
    exit 0
  fi
done
exit 0
"""


CITIES = re.findall(
    r"^  ([A-Za-z0-9_-]+):$",
    (Path(__file__).parent.parent / "config" / "cities.yaml").read_text(),
    re.M,
)


class Run(NamedTuple):
    returncode: int
    stdout: str
    stderr: str
    aws_calls: str


@pytest.fixture
def host(tmp_path):
    """A fake host: stub aws/docker on PATH and one .env.<city> per city,
    each naming the prod bucket, as the staging host really has."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("aws", AWS_STUB), ("docker", DOCKER_STUB)):
        path = bin_dir / name
        path.write_text(body)
        path.chmod(0o755)
    for city in CITIES:
        (tmp_path / f".env.{city}").write_text(ENV_CITY_FILE)
    calls = tmp_path / "aws_calls.txt"
    env = dict(
        os.environ,
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        AWS_CALLS=str(calls),
        LOG_FILE=str(tmp_path / "script.log"),
    )
    return tmp_path, env, calls


def run(script, args, host_fixture):
    cwd, env, calls = host_fixture
    result = subprocess.run(
        ["bash", str(script), *args],
        capture_output=True, text=True, timeout=120, cwd=cwd, env=env,
    )
    return Run(result.returncode, result.stdout, result.stderr,
               calls.read_text() if calls.exists() else "")


def uploads(result):
    return [l for l in result.aws_calls.splitlines() if l.startswith("s3 cp") and "s3://" in l]


# --- backup ---

def test_staging_backup_ignores_prod_bucket_from_env_file(host):
    result = run(BACKUP_SCRIPT, ["--city", "ogre", "--env", "staging"], host)
    assert result.returncode == 0, result.stdout + result.stderr
    destinations = uploads(result)
    assert destinations, "no upload recorded"
    assert all("sslv-staging-ogre-db-backups" in d for d in destinations)
    assert not any("sslv-prod-" in d for d in destinations)
    assert "Ignoring S3_BUCKET=sslv-prod-ogre-db-backups" in result.stdout


def test_staging_backup_keeps_env_flag_across_cities(host):
    """ENV=prod from the first city's env file must not leak into the next:
    that is why later cities logged "(env: prod)" during the incident."""
    result = run(BACKUP_SCRIPT, ["--all", "--env", "staging"], host)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "(env: prod)" not in result.stdout
    assert not any("sslv-prod-" in d for d in uploads(result))
    # One upload per city in config/cities.yaml, all to staging buckets.
    assert len(uploads(result)) == len(CITIES)


def test_backup_refuses_bucket_from_another_env(host):
    result = run(BACKUP_SCRIPT,
                 ["--city", "ogre", "--env", "staging",
                  "--bucket", "sslv-prod-ogre-db-backups"], host)
    assert result.returncode == 1
    assert "Refusing to upload" in result.stdout
    assert uploads(result) == []


def test_backup_bucket_override_within_env_is_allowed(host):
    result = run(BACKUP_SCRIPT,
                 ["--city", "ogre", "--env", "staging",
                  "--bucket", "sslv-staging-ogre-db-backups-alt"], host)
    assert result.returncode == 0, result.stdout + result.stderr
    assert all("sslv-staging-ogre-db-backups-alt" in d for d in uploads(result))


def test_prod_backup_still_uses_prod_bucket(host):
    result = run(BACKUP_SCRIPT, ["--city", "ogre", "--env", "prod"], host)
    assert result.returncode == 0, result.stdout + result.stderr
    assert all("sslv-prod-ogre-db-backups" in d for d in uploads(result))


# --- restore ---

def test_staging_restore_reads_staging_bucket(host):
    """The env file names the prod bucket; the restore must not follow it -
    that would load prod data into the staging DB."""
    result = run(RESTORE_SCRIPT, ["--city", "ogre", "--env", "staging", "--yes"], host)
    assert "sslv-staging-ogre-db-backups" in result.stdout
    assert "sslv-prod-ogre-db-backups" not in result.aws_calls
    assert "Ignoring S3_BUCKET=sslv-prod-ogre-db-backups" in result.stdout


def test_restore_refuses_bucket_from_another_env(host):
    result = run(RESTORE_SCRIPT,
                 ["--city", "ogre", "--env", "staging", "--yes",
                  "--bucket", "sslv-prod-ogre-db-backups"], host)
    assert result.returncode == 1
    assert "Refusing to restore" in result.stdout
    assert "s3 cp" not in result.aws_calls
