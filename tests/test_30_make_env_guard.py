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
           "BACKUP_MIN_BYTES_PER_ROW", "BACKUP_SHRINK_RATIO", "BACKUP_HISTORY_N",
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


# --- backup size calibration (docs/backup_size_alerting_plan.md items 4-5) ---

def test_backup_sizes_is_read_only_and_warns_on_env_mismatch(staging_host):
    result = make(["backup-sizes", "CITY=ogre", "COUNT=5"], staging_host, dry_run=True)
    assert result.returncode == 0
    assert "Reporting on 'prod' while this host runs 'staging'" in result.stdout
    assert "scripts/backup_sizes.py --env prod --city ogre" in result.stdout
    assert "--count 5" in result.stdout


def test_watchdog_install_records_backup_thresholds_only_when_set(staging_host):
    result = make(["watchdog-install", "M6_ENV=staging", "BACKUP_MIN_BYTES_PER_ROW=7"],
                  staging_host, dry_run=True)
    assert result.returncode == 0
    # The recipe skips the empty ones (VAR=) at run time.
    assert "BACKUP_MIN_BYTES_PER_ROW=7" in result.stdout
    assert "BACKUP_SHRINK_RATIO= BACKUP_HISTORY_N=" in result.stdout


def test_watchdog_status_flags_a_floor_left_from_an_older_install(tmp_path):
    env_file = tmp_path / "sslv-watchdog.env"
    env_file.write_text("ENV=prod\nMIN_BACKUP_SIZE_KB=10\n")
    result = make(["watchdog-status"], env_file)  # systemctl may fail; the check runs first
    assert "sets MIN_BACKUP_SIZE_KB=10; the default is now 1" in result.stdout
    assert "make watchdog-install M6_ENV=prod" in result.stdout


def test_watchdog_status_quiet_about_a_current_floor(staging_host):
    staging_host.write_text("ENV=staging\nMIN_BACKUP_SIZE_KB=1\n")
    assert "MIN_BACKUP_SIZE_KB" not in make(["watchdog-status"], staging_host).stdout


# --- 2026-09-27: NTFY_TOPIC_URL without https:// ---

def test_watchdog_install_adds_https_to_a_bare_topic(staging_host):
    result = make(["watchdog-install", "M6_ENV=staging",
                   "NTFY_TOPIC_URL=ntfy.sh/staging-sslv-mc-alerts",
                   "HEARTBEAT_PING_URL=hc-ping.com/uuid"], staging_host, dry_run=True)
    assert result.returncode == 0
    assert '"https://ntfy.sh/staging-sslv-mc-alerts"' in result.stdout
    assert "https://hc-ping.com/uuid" in result.stdout
    assert '"ntfy.sh/' not in result.stdout


def test_prod_install_refuses_the_bare_staging_topic(staging_host):
    """Without the scheme the topic did not equal the staging default, so
    the guard against prod pushing to the staging topic let it through."""
    result = make(["watchdog-install", "M6_ENV=prod",
                   "NTFY_TOPIC_URL=ntfy.sh/staging-sslv-mc-alerts"], staging_host)
    assert result.returncode != 0
    assert "would push to the staging topic" in result.stdout


def test_watchdog_status_flags_a_bare_topic_in_the_env_file(staging_host):
    staging_host.write_text("ENV=staging\nNTFY_TOPIC_URL=ntfy.sh/staging-sslv-mc-alerts\n")
    out = make(["watchdog-status"], staging_host).stdout
    assert "has NTFY_TOPIC_URL=ntfy.sh/staging-sslv-mc-alerts without https://" in out
    assert "make watchdog-install M6_ENV=staging" in out


def test_watchdog_status_quiet_about_an_https_topic(staging_host):
    assert "without https://" not in make(["watchdog-status"], staging_host).stdout


# --- M6_ENV is lowercased and checked (2026-10-12: M6_ENV=Staging -> all BAD) ---

@pytest.mark.parametrize("given, used", [("Staging", "staging"), ("PROD", "prod"), ("dev", "dev")])
def test_m6_env_is_lowercased(given, used, staging_host):
    result = make(["fleet-status", f"M6_ENV={given}"], staging_host, dry_run=True)
    assert result.returncode == 0, result.stderr
    assert f"--env {used} " in result.stdout


def test_unknown_m6_env_stops_make(staging_host):
    result = make(["fleet-status", "M6_ENV=qa"], staging_host, dry_run=True)
    assert result.returncode != 0
    assert "M6_ENV='qa' is not one of: prod staging dev" in result.stderr
