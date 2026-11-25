"""Tests for scripts/backup_sizes.py (docs/backup_size_alerting_plan.md item 5)."""
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("backup_sizes", SCRIPTS / "backup_sizes.py")
sizes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sizes)
wd = sizes.wd


def listing(*objects):
    """(hours_ago, size) pairs, oldest first, as aws s3api prints them."""
    now = datetime.now(timezone.utc)
    return json.dumps([
        {"Key": f"db-backups/{i}.sql.gz", "Size": size,
         "LastModified": (now - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i, (h, size) in enumerate(objects)
    ])


def fake_aws(history, metadata_by_key):
    """run_cmd stand-in: listing for list-objects-v2, per-key metadata for
    head-object (missing key = the call fails, as for an old backup)."""
    def run(cmd, timeout=60):
        if "head-object" in cmd:
            key = cmd[cmd.index("--key") + 1]
            if key in metadata_by_key:
                return 0, json.dumps(metadata_by_key[key]), ""
            return 254, "", "404"
        return 0, history, ""
    return run


def meta(listed, removed, env="staging", city="ogre"):
    return {"env": env, "city": city, "listed-ads": str(listed), "removed-ads": str(removed)}


def run_main(capsys, history, metadata, live=(49, 9), argv=()):
    with patch.object(wd, "run_cmd", side_effect=fake_aws(history, metadata)), \
         patch.object(wd, "get_db_row_counts", return_value=live):
        code = sizes.main(["--env", "staging", "--city", "ogre", *argv])
    return code, capsys.readouterr().out


def test_table_shows_newest_first_with_bytes_per_row(capsys):
    history = listing((26, 2888), (2, 2956))
    metadata = {"db-backups/1.sql.gz": meta(49, 9)}
    code, out = run_main(capsys, history, metadata)
    assert code == 0
    lines = [line for line in out.splitlines() if line.startswith("  20")]
    # newest: (2956 - 1024) / 58 rows = 33.3 B/row, from the dump's metadata
    assert "2956 B" in lines[0] and "58 rows (dump)" in lines[0] and "33.3 B/row" in lines[0]
    assert "2888 B" in lines[1] and "- rows" in lines[1]  # before row counts existed
    assert "WARN" not in out


def test_newest_backup_without_metadata_uses_live_rows(capsys):
    _, out = run_main(capsys, listing((2, 2956)), {})
    assert "58 rows (live)" in out
    # live counts are not dump counts: they do not feed the suggestion
    assert "Only 0 backup(s) record their row count" in out


def test_backup_below_threshold_is_marked_warn(capsys):
    _, out = run_main(capsys, listing((2, 2640)), {"db-backups/0.sql.gz": meta(900, 4100)},
                      live=(900, 4100))
    line = next(line for line in out.splitlines() if "2640 B" in line)
    assert "5000 rows (dump)" in line and "0.3 B/row" in line and line.endswith("WARN")


def test_backup_from_another_env_is_flagged(capsys):
    """2026-09-21: staging dumps in the prod buckets."""
    _, out = run_main(capsys, listing((2, 2956)),
                      {"db-backups/0.sql.gz": meta(49, 9, env="prod")})
    assert "env=prod!" in out


def test_suggestion_is_a_quarter_of_p10(capsys):
    sizes_by_day = [(h, 1024 + 58 * bpr) for h, bpr in
                    [(146, 20), (122, 19), (98, 21), (74, 18), (50, 22), (26, 19), (2, 20)]]
    metadata = {f"db-backups/{i}.sql.gz": meta(49, 9) for i in range(len(sizes_by_day))}
    _, out = run_main(capsys, listing(*sizes_by_day), metadata)
    assert "Over 7 backups with a recorded row count: min 18.0 (ogre), p10 18.0," \
           " median 20.0 B/row" in out
    assert "Suggested BACKUP_MIN_BYTES_PER_ROW: 4 (25% of p10); current default: 5" in out
    assert "below the suggestion" not in out


def test_listing_error_is_reported_not_raised(capsys):
    with patch.object(wd, "run_cmd", return_value=(254, "", "An error occurred (NoSuchBucket)")), \
         patch.object(wd, "get_db_row_counts", return_value=None):
        code = sizes.main(["--env", "staging", "--city", "ogre"])
    out = capsys.readouterr().out
    assert code == 0
    assert "could not list s3://sslv-staging-ogre-db-backups: NoSuchBucket" in out
    assert "live rows: unknown" in out


def test_count_sets_the_listing_size(capsys):
    with patch.object(wd, "run_cmd", side_effect=fake_aws(listing((2, 2956)), {})) as run, \
         patch.object(wd, "get_db_row_counts", return_value=(49, 9)):
        sizes.main(["--env", "staging", "--city", "ogre", "--count", "3"])
    cmd = run.call_args_list[0][0][0]
    assert "[-3:]" in cmd[cmd.index("--query") + 1]


def test_percentile_rounds_down():
    assert sizes.percentile([5, 1, 3, 2, 4], 0.10) == 1
    assert sizes.percentile([5, 1, 3, 2, 4], 0.5) == 3
