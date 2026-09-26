"""Make targets must not act on another environment than the host runs.

`make backup-all` on the staging host defaults to M6_ENV=prod, which dumped the
staging DBs into the prod buckets on 2026-09-21. The host's env is recorded in
/etc/sslv-watchdog.env by `make watchdog-install`; writing targets refuse a
mismatch, read-only ones only warn.

Blocked cases run make for real - the guard exits before any command runs.
Allowed cases use `make -n`, which prints the recipe without executing it.
"""
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent


@pytest.fixture
def staging_host(tmp_path):
    """A host whose watchdog config says it runs staging."""
    env_file = tmp_path / "sslv-watchdog.env"
    env_file.write_text("ENV=staging\nNTFY_TOPIC_URL=https://ntfy.sh/topic\n")
    return env_file


# Variables the outer `make test` may have exported (and MAKEFLAGS, which
# carries its command-line overrides) would otherwise leak into these runs.
AMBIENT = {"FORCE_ENV", "M6_ENV", "MIN_BACKUP_SIZE_KB", "HOST_ENV",
           "WATCHDOG_ENV_FILE", "MAKEFLAGS", "MAKELEVEL", "MFLAGS"}


def make(args, env_file, dry_run=False):
    cmd = ["make"]
    if dry_run:
        cmd.append("-n")
    cmd += [*args, f"WATCHDOG_ENV_FILE={env_file}"]
    env = {k: v for k, v in os.environ.items() if k not in AMBIENT}
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                          cwd=REPO, env=env)


@pytest.mark.parametrize("target", ["backup-all", "backup-city", "restore-all",
                                    "test-restore", "deploy-prod", "undeploy-prod"])
def test_prod_targets_refused_on_a_staging_host(target, staging_host):
    result = make([target], staging_host)
    assert result.returncode != 0
    assert "This host runs 'staging'" in result.stdout
    # Nothing beyond the guard ran.
    assert "scripts/backup_db_city.sh" not in result.stdout
    assert "deploy-multi-city-ws.sh" not in result.stdout


def test_matching_env_is_allowed(staging_host):
    result = make(["backup-all", "M6_ENV=staging"], staging_host, dry_run=True)
    assert result.returncode == 0
    assert "--env staging" in result.stdout


def test_force_env_overrides_the_guard(staging_host):
    result = make(["backup-all", "M6_ENV=prod", "FORCE_ENV=1"], staging_host, dry_run=True)
    assert result.returncode == 0
    assert "--env prod" in result.stdout


def test_no_watchdog_config_means_no_guard(tmp_path):
    """Dev machines have no /etc/sslv-watchdog.env: the guard stays quiet."""
    result = make(["backup-all", "M6_ENV=prod"], tmp_path / "missing.env", dry_run=True)
    assert result.returncode == 0
    # -n prints the guard without running it; with no config its test is inert.
    assert '[ -n "" ]' in result.stdout
    assert "--env prod" in result.stdout


def test_read_only_targets_warn_but_still_run(staging_host):
    result = make(["fleet-status"], staging_host, dry_run=True)
    assert result.returncode == 0
    assert "Reporting on 'prod' while this host runs 'staging'" in result.stdout
    assert "fleet_watchdog.py" in result.stdout


# --- minimum backup size: one hard floor for every env ---

@pytest.mark.parametrize("env", ["staging", "dev", "prod"])
def test_min_backup_size_is_the_same_hard_floor_everywhere(env, staging_host):
    result = make(["verify-backup", f"M6_ENV={env}", "FORCE_ENV=1"], staging_host, dry_run=True)
    assert "--min-size-kb 1" in result.stdout


def test_min_backup_size_can_be_overridden(staging_host):
    result = make(["fleet-status", "M6_ENV=staging", "MIN_BACKUP_SIZE_KB=7"],
                  staging_host, dry_run=True)
    assert "--min-backup-size-kb 7" in result.stdout
