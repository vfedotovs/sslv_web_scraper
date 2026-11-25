#!/usr/bin/env python3
"""Backup size calibration report (docs/backup_size_alerting_plan.md item 5).

Read-only: lists the newest backups per city with their size, the row count
the dump recorded (S3 metadata, written by backup.py since dev-1.7.9.17) and
the bytes per row each one works out to. Use it to set
BACKUP_MIN_BYTES_PER_ROW, or a per-city backup_min_bytes_per_row in
config/cities.yaml, from real numbers rather than a guess.

B/row is (size - floor) / rows: the highest BACKUP_MIN_BYTES_PER_ROW that
backup still passes. Backups made before row counts were recorded have none;
the newest one falls back to the live DB count (marked "live").

Usage:
  python3 scripts/backup_sizes.py --env staging [--city ogre] [--count 14]
Stdlib only, like fleet_watchdog.py, so it runs on the EC2 host as is.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fleet_watchdog as wd  # noqa: E402

# Fewer backups with a row count than this and a percentile means nothing.
MIN_SAMPLES = 5
# The suggestion leaves this much headroom below p10: bytes per row varies
# with the listings, and a warning that fires on real backups gets ignored.
SUGGEST_FRACTION = 0.25


def backup_rows(city, env, bucket, key, region, live_rows, newest):
    """(rows, source, problem) for one backup. rows is None when unknown;
    problem names a metadata env/city that is not this bucket's."""
    metadata = wd.get_backup_metadata(bucket, key, region)
    problem = None
    for field, expected in (("env", env), ("city", city)):
        recorded = metadata.get(field)
        if recorded and recorded.replace("-", "_") != expected.replace("-", "_"):
            problem = f"{field}={recorded}!"
    rows = wd.dump_rows(metadata)
    if rows is not None:
        return sum(rows), "dump", problem
    if newest and live_rows is not None:
        return sum(live_rows), "live", problem
    return None, "", problem


def percentile(values, fraction):
    """Nearest-rank, rounding down: the conservative side for a threshold."""
    ordered = sorted(values)
    return ordered[int(fraction * (len(ordered) - 1))]


def report_city(city, args, floor, now):
    """Print one city's table; returns [(city, B/row)] for the summary."""
    bucket = wd.backup_bucket(args.env, city)
    live_rows = wd.get_db_row_counts(city)
    live = (f"live LA:{live_rows[0]} RA:{live_rows[1]} = {sum(live_rows)} rows"
            if live_rows is not None else "live rows: unknown (db container?)")
    bpr_limit = args.city_settings.get(city, {}).get(
        "backup_min_bytes_per_row", args.backup_min_bytes_per_row)
    print(f"{city}  ({live}; threshold {bpr_limit} B/row)")

    outcome, detail = wd.get_backup_history(bucket, args.region, args.count)
    if outcome == "error":
        print(f"  could not list s3://{bucket}: {detail}\n")
        return []
    if outcome == "empty":
        print(f"  no backups in s3://{bucket}\n")
        return []

    samples = []
    for index, (key, age_hours, size) in enumerate(reversed(detail)):
        rows, source, problem = backup_rows(
            city, args.env, bucket, key, args.region, live_rows, newest=index == 0)
        when = (now - timedelta(hours=age_hours)).strftime("%Y-%m-%d %H:%M")
        cells = [f"  {when}", f"{size:>9} B"]
        if rows:
            bpr = (size - floor) / rows
            if source == "dump":
                samples.append((city, bpr))
            verdict = "WARN" if bpr < bpr_limit else ""
            cells += [f"{rows:>6} rows ({source})", f"{bpr:>7.1f} B/row", verdict]
        else:
            cells += ["     - rows", "", ""]
        if problem:
            cells.append(problem)
        print("  ".join(cells).rstrip())
    print()
    return samples


def main(argv=None):
    parser = argparse.ArgumentParser(description="Backup size calibration report (read-only)")
    parser.add_argument("--env", default=os.getenv("ENV", "prod"))
    parser.add_argument("--city", help="one city (default: all in cities.yaml)")
    parser.add_argument("--count", type=int, default=14,
                        help="newest backups per city (default 14)")
    parser.add_argument("--cities-file", default=wd.DEFAULT_CITIES_FILE)
    parser.add_argument("--s3-region",
                        default=os.getenv("S3_REGION") or os.getenv("AWS_REGION")
                        or "eu-west-1")
    parser.add_argument("--min-backup-size-kb", type=int,
                        default=int(os.getenv("MIN_BACKUP_SIZE_KB", "1")))
    parser.add_argument("--backup-min-bytes-per-row", type=int,
                        default=int(os.getenv("BACKUP_MIN_BYTES_PER_ROW", "5")))
    args = parser.parse_args(argv)
    args.region = args.s3_region

    cities = [args.city] if args.city else wd.parse_cities(args.cities_file)
    if not cities:
        print(f"ERROR: no cities found in {args.cities_file}")
        return 2
    args.city_settings = wd.parse_city_settings(args.cities_file)

    floor = args.min_backup_size_kb * 1024
    now = datetime.now(timezone.utc)
    print(f"SSLV backup sizes [{args.env}] — {now:%Y-%m-%d %H:%M} UTC —"
          f" newest {args.count} per city, floor {args.min_backup_size_kb} KB")
    print("B/row = (size - floor) / rows: the highest BACKUP_MIN_BYTES_PER_ROW"
          " that backup passes\n")

    samples = []
    for city in cities:
        samples += report_city(city, args, floor, now)

    values = [bpr for _, bpr in samples]
    if len(values) < MIN_SAMPLES:
        print(f"Only {len(values)} backup(s) record their row count (need"
              f" {MIN_SAMPLES}). Row counts are written since dev-1.7.9.17;"
              " re-run after a few nightly backups.")
        return 0
    lowest_city, lowest = min(samples, key=lambda sample: sample[1])
    p10 = percentile(values, 0.10)
    suggested = max(1, int(p10 * SUGGEST_FRACTION))
    print(f"Over {len(values)} backups with a recorded row count:"
          f" min {lowest:.1f} ({lowest_city}), p10 {p10:.1f},"
          f" median {percentile(values, 0.5):.1f} B/row")
    print(f"Suggested BACKUP_MIN_BYTES_PER_ROW: {suggested}"
          f" ({SUGGEST_FRACTION:.0%} of p10); current default:"
          f" {args.backup_min_bytes_per_row}")
    for city in sorted({city for city, _ in samples}):
        city_values = [bpr for c, bpr in samples if c == city]
        if min(city_values) < suggested:
            print(f"  {city}: min {min(city_values):.1f} B/row is below the"
                  f" suggestion - set backup_min_bytes_per_row for it in"
                  f" cities.yaml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
