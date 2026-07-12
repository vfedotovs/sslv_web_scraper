#!/usr/bin/env python3
"""scrape_runs module (M6 monitoring Item 2).

Records one row per city per pipeline run in the scrape_runs DB table:
  - started_at / finished_at timestamps
  - status: running / success / failed (+ failed_stage and error text)
  - counts: pages fetched, URLs discovered, new / still-listed / removed ads,
    and listed_ads / removed_ads table row totals after the run

This table replaces the scraped_and_removed.txt debug file and the
filesystem "already ran today" marker files, and is the single source of
truth read by the failure/anomaly mailer (Item 3), the /status endpoint
(Item 5), and the host-level watchdog (Item 6).

Usage from the pipeline (see main.py):
    ensure_scrape_runs_table()
    run_id = start_run(city)
    ... stages call record_counts(...) as they learn numbers ...
    finish_run("success")  or  finish_run("failed", failed_stage=..., error=...)

record_counts() is deliberately best-effort (logs a warning instead of
raising): telemetry must never fail a run that is otherwise succeeding.
start_run()/finish_run() DO raise on DB errors — if the run cannot be
recorded, the run must fail loudly (M6 Item 1 philosophy).
"""

import sys
import logging
from logging import handlers
import psycopg2
from app.wsmodules.config import config


logger = logging.getLogger("scrape_runs")
logger.setLevel(logging.INFO)
log_format = logging.Formatter(
    "%(asctime)s [%(levelname)-5.5s]: %(funcName)s: %(lineno)d: %(message)s"
)
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(log_format)
logger.addHandler(ch)
fh = handlers.RotatingFileHandler("dbworker.log", maxBytes=(1048576 * 5), backupCount=7)
fh.setFormatter(log_format)
logger.addHandler(fh)


# Columns that stages are allowed to update via record_counts()
COUNT_COLUMNS = (
    "pages_fetched",
    "urls_discovered",
    "new_ads",
    "still_listed_ads",
    "removed_ads",
    "listed_table_rows",
    "removed_table_rows",
)

# run_id of the run currently executing in this process (one run at a time
# per ws container; stages report counts against it without signature changes)
_current_run_id = None


def _connect():
    """Opens a new DB connection using database.ini params."""
    params = config()
    return psycopg2.connect(**params)


def ensure_scrape_runs_table() -> None:
    """Create the scrape_runs table (and index) if it does not exist."""
    conn = None
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS scrape_runs (
                run_id SERIAL PRIMARY KEY,
                city TEXT NOT NULL,
                started_at TIMESTAMP NOT NULL DEFAULT now(),
                finished_at TIMESTAMP,
                status TEXT NOT NULL DEFAULT 'running',
                failed_stage TEXT,
                error TEXT,
                pages_fetched INTEGER,
                urls_discovered INTEGER,
                new_ads INTEGER,
                still_listed_ads INTEGER,
                removed_ads INTEGER,
                listed_table_rows INTEGER,
                removed_table_rows INTEGER
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS scrape_runs_city_started_idx
            ON scrape_runs (city, started_at DESC)
        """)
        conn.commit()
        cur.close()
        logger.info("Ensured scrape_runs table exists")
    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(f"Error ensuring scrape_runs table exists: {error}")
        raise
    finally:
        if conn is not None:
            conn.close()


def start_run(city: str) -> int:
    """Insert a 'running' row for this city and remember it as the current run.

    Raises on DB errors: a run that cannot be recorded must not start silently.
    """
    global _current_run_id
    conn = None
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO scrape_runs (city, status) VALUES (%s, 'running') RETURNING run_id",
            (city,),
        )
        run_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        _current_run_id = run_id
        logger.info(f"Started scrape run {run_id} for city {city}")
        return run_id
    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(f"Failed to record run start for city {city}: {error}")
        raise
    finally:
        if conn is not None:
            conn.close()


def record_counts(**counts) -> None:
    """Update count columns on the current run row (best-effort telemetry).

    Called from inside pipeline stages (web_scraper, db_worker) as numbers
    become known. Unknown column names raise ValueError (programming error);
    DB problems only log a warning — recording metrics must never fail a
    stage that is otherwise succeeding.
    """
    for key in counts:
        if key not in COUNT_COLUMNS:
            raise ValueError(f"Unknown scrape_runs count column: {key}")
    if _current_run_id is None:
        logger.warning(f"No active scrape run; skipping record_counts({counts})")
        return
    conn = None
    try:
        conn = _connect()
        cur = conn.cursor()
        assignments = ", ".join(f"{col} = %s" for col in counts)
        values = list(counts.values()) + [_current_run_id]
        cur.execute(
            f"UPDATE scrape_runs SET {assignments} WHERE run_id = %s", values
        )
        conn.commit()
        cur.close()
        logger.info(f"Recorded counts for run {_current_run_id}: {counts}")
    except (Exception, psycopg2.DatabaseError) as error:
        logger.warning(f"Failed to record counts {counts} for run {_current_run_id}: {error}")
    finally:
        if conn is not None:
            conn.close()


def finish_run(status: str, failed_stage: str = None, error: str = None) -> None:
    """Mark the current run finished with 'success' or 'failed' (+ error info).

    Raises on DB errors for the success path (the DB was just written by
    db_worker, so a failure here is real). The caller wraps the failed path.
    """
    global _current_run_id
    if status not in ("success", "failed"):
        raise ValueError(f"Invalid run status: {status}")
    if _current_run_id is None:
        logger.warning(f"No active scrape run; skipping finish_run({status})")
        return
    conn = None
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            """UPDATE scrape_runs
               SET status = %s, failed_stage = %s, error = %s, finished_at = now()
               WHERE run_id = %s""",
            (status, failed_stage, error, _current_run_id),
        )
        conn.commit()
        cur.close()
        logger.info(f"Finished scrape run {_current_run_id} with status: {status}")
        _current_run_id = None
    except (Exception, psycopg2.DatabaseError) as db_error:
        logger.error(f"Failed to record run finish for run {_current_run_id}: {db_error}")
        raise
    finally:
        if conn is not None:
            conn.close()


def has_succeeded_today(city: str) -> bool:
    """DB-based 'already ran today' guard (replaces filesystem marker files).

    Only successful runs count — a failed run may be retried the same day.
    """
    conn = None
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            """SELECT 1 FROM scrape_runs
               WHERE city = %s AND status = 'success'
                 AND started_at::date = CURRENT_DATE
               LIMIT 1""",
            (city,),
        )
        found = cur.fetchone() is not None
        cur.close()
        logger.info(f"Successful run today for city {city}: {found}")
        return found
    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(f"Failed to check todays run state for city {city}: {error}")
        raise
    finally:
        if conn is not None:
            conn.close()


def get_recent_runs(city: str = None, limit: int = 7) -> list:
    """Return recent runs (newest first) as a list of dicts.

    Used by the daily email summary now, and by the /status endpoint (Item 5)
    and watchdog (Item 6) later.
    """
    columns = (
        "run_id", "city", "started_at", "finished_at", "status",
        "failed_stage", "error",
    ) + COUNT_COLUMNS
    conn = None
    try:
        conn = _connect()
        cur = conn.cursor()
        if city is not None:
            cur.execute(
                f"SELECT {', '.join(columns)} FROM scrape_runs"
                " WHERE city = %s ORDER BY started_at DESC LIMIT %s",
                (city, limit),
            )
        else:
            cur.execute(
                f"SELECT {', '.join(columns)} FROM scrape_runs"
                " ORDER BY started_at DESC LIMIT %s",
                (limit,),
            )
        rows = cur.fetchall()
        cur.close()
        return [dict(zip(columns, row)) for row in rows]
    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(f"Failed to fetch recent runs: {error}")
        raise
    finally:
        if conn is not None:
            conn.close()


def format_recent_runs(city: str = None, limit: int = 7) -> str:
    """Human-readable recent-run summary block for the daily report email.

    Replaces the old scraped_and_removed.txt section. Example line:
    2026-07-12 00:41 ogre success | pages: 2 urls: 63 new: 3 still: 58 removed: 2 | LA TBL rows: 61 RA TBL rows: 940
    """
    lines = ["Scrape run history (latest first):"]
    for run in get_recent_runs(city, limit):
        started = run["started_at"].strftime("%Y-%m-%d %H:%M") if run["started_at"] else "?"
        line = (
            f"{started} {run['city']} {run['status']}"
            f" | pages: {run['pages_fetched']} urls: {run['urls_discovered']}"
            f" new: {run['new_ads']} still: {run['still_listed_ads']}"
            f" removed: {run['removed_ads']}"
            f" | LA TBL rows: {run['listed_table_rows']}"
            f" RA TBL rows: {run['removed_table_rows']}"
        )
        if run["status"] == "failed":
            line += f" | stage: {run['failed_stage']} error: {run['error']}"
        lines.append(line)
    return "\n".join(lines)
