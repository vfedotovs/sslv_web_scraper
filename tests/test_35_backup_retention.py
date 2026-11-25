"""backup_db_city.sh must not delete backups unless asked (S-5).

Regression tests for 2026-10-12: the script pruned the city bucket to the
newest 5 objects after every upload, while the nightly backup container keeps
every backup. One `make e2e-backup-restore CITY=ogre M6_ENV=staging` deleted
17 ogre staging backups; prod buckets have no versioning, so the same run there
(or `make backup-all M6_ENV=prod` before a cutover) would lose them for good.

Pruning is now opt-in (--keep-last N / BACKUP_KEEP_LAST) and only touches dated
backup keys under db-backups/. Stub `aws`/`docker` on PATH, as in test_28.
"""
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "backup_db_city.sh"
BUCKET = "sslv-staging-ogre-db-backups"

# What the ogre staging bucket held on 2026-10-12: one backup a night since 09-22.
DATED = [f"db-backups/2026/{m:02d}/{d:02d}/pg_backup_2026{m:02d}{d:02d}_020004.sql.gz"
         for m, d in [(9, n) for n in range(22, 31)] + [(10, n) for n in range(1, 13)]]
# Under db-backups/ but not a dated nightly backup: never a prune candidate.
OTHER = ["db-backups/README.txt", "db-backups/2026/09/01/manual-before-migration.sql.gz"]

AWS_STUB = """#!/bin/bash
echo "$@" >> "$AWS_CALLS"
case "$1 $2" in
  "s3 cp") [[ "$3" == s3://* ]] && printf 'fake dump' > "$4"; exit 0 ;;
  "s3 ls") if [[ "$*" == *--recursive* ]]; then
             while read -r key; do echo "2026-10-12 02:00:06 3775 $key"; done < "$AWS_KEYS"
           fi; exit 0 ;;
  *) exit 0 ;;
esac
"""

DOCKER_STUB = """#!/bin/bash
for arg in "$@"; do
  if [[ "$arg" == pg_dump ]]; then echo "-- fake pg_dump"; exit 0; fi
done
exit 0
"""


@pytest.fixture
def host(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("aws", AWS_STUB), ("docker", DOCKER_STUB)):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    (tmp_path / ".env.ogre").write_text(
        "POSTGRES_PASSWORD=secret\nDB_USER=new_docker_user\nDB_NAME=new_docker_db\n")
    keys = tmp_path / "keys.txt"
    keys.write_text("\n".join(DATED + OTHER) + "\n")
    env = {k: v for k, v in os.environ.items() if k != "BACKUP_KEEP_LAST"}
    env.update(PATH=f"{bin_dir}:{os.environ['PATH']}", AWS_CALLS=str(tmp_path / "calls.txt"),
               AWS_KEYS=str(keys), LOG_FILE=str(tmp_path / "backup.log"))
    return tmp_path, env


def run(host, *args, **extra_env):
    cwd, env = host
    result = subprocess.run(["bash", str(SCRIPT), "--city", "ogre", "--env", "staging", *args],
                            capture_output=True, text=True, timeout=120, cwd=cwd,
                            env=dict(env, **extra_env))
    calls_file = cwd / "calls.txt"
    calls = calls_file.read_text().splitlines() if calls_file.exists() else []
    return result, calls


def deleted(calls):
    return [c.split()[2].removeprefix(f"s3://{BUCKET}/") for c in calls if c.startswith("s3 rm ")]


def uploaded(calls):
    return [c for c in calls if c.startswith("s3 cp ") and f"s3://{BUCKET}/db-backups/" in c]


def test_default_deletes_nothing(host):
    result, calls = run(host)
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(uploaded(calls)) == 1
    assert deleted(calls) == []
    assert "keeping all backups" in result.stdout


def test_keep_last_deletes_only_the_oldest_dated_backups(host):
    result, calls = run(host, "--keep-last", "5")
    assert result.returncode == 0, result.stdout + result.stderr
    assert deleted(calls) == DATED[:-5]          # 16 oldest, oldest first
    assert "pruning 16 of 21 backup(s)" in result.stdout


def test_env_var_sets_the_same_limit(host):
    _, calls = run(host, BACKUP_KEEP_LAST="20")
    assert deleted(calls) == DATED[:1]


def test_flag_overrides_env_var(host):
    _, calls = run(host, "--keep-last", "0", BACKUP_KEEP_LAST="5")
    assert deleted(calls) == []


def test_non_backup_keys_are_never_pruned(host):
    _, calls = run(host, "--keep-last", "1")
    gone = deleted(calls)
    assert len(gone) == len(DATED) - 1
    assert not set(gone) & set(OTHER)


def test_limit_above_count_prunes_nothing(host):
    result, calls = run(host, "--keep-last", "60")
    assert deleted(calls) == []
    assert "nothing to prune" in result.stdout


def test_env_file_cannot_change_the_limit(host):
    cwd, _ = host
    with open(cwd / ".env.ogre", "a") as env_file:
        env_file.write("BACKUP_KEEP_LAST=1\n")
    result, calls = run(host)
    assert result.returncode == 0, result.stdout + result.stderr
    assert deleted(calls) == []


@pytest.mark.parametrize("bad", ["abc", "-1", "5x"])
def test_invalid_limit_stops_before_any_backup(host, bad):
    result, calls = run(host, "--keep-last", bad)
    assert result.returncode != 0
    assert "--keep-last must be a number" in result.stdout + result.stderr
    assert uploaded(calls) == [] and deleted(calls) == []
