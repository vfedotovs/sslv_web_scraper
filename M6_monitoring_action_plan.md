# M6 — Monitoring Action Plan: Key Modules, Scraper, DB Tables State, and DB Backups

**Scope:** Simple but efficient monitoring for the dev-1.6.x application state — pipeline modules,
scraper health, DB table state, and DB backups. Deliberately stops short of Grafana/Prometheus-style
dashboards at this stage. Alerting channel is the AWS SES email path that already exists in the app.

---

## Review: What dev-1.6.x Already Provides (and Where the Gaps Are)

The dev-1.6.x branch line added real observability building blocks:

- Container healthchecks for `db` (pg_isready), `ws` (`/docs`), `ts` (`/health`)
- Dedicated per-city backup container (`src/backup-svc`) with internal cron at 02:00 UTC,
  rotating logs to `/var/log/backup.log` + stdout, `LOG_LEVEL` support
- Manual verification targets: `make verify-backup`, `check-backup-age`, `test-restore`,
  `e2e-backup-restore`
- Daily report email via AWS SES with city + release + date in the subject
- City-aware ts scheduler and multi-city deploy scripts

However, everything currently answers **"is the process alive?"**, not **"did the work succeed?"**:

1. **The scheduler can never know if a run worked.** `ts.py:execute_task` uses a 30-second
   timeout, while the synchronous `/run-task/{city}` call takes minutes to hours — ts logs a
   timeout every day regardless of outcome, and nothing downstream notices.
2. **`db_worker.py` swallows every DB error with `print(error)`** and continues, so a run can
   "complete" having written nothing to the database. Any monitoring built on top would lie.
3. **Run outcomes aren't recorded anywhere queryable.** The only per-run record is
   `scraped_and_removed.txt`, an append-only file inside the container.
4. **Backup failures are silent.** `backup.py` exits 1 on failure, but cron swallows the exit
   code; nothing checks that today's object actually landed in S3 with a sane size. A dead
   backup cron would be discovered at restore time.
5. **The success email is a positive-only signal.** A broken pipeline produces silence, and
   silence across 3–6 cities is easy to miss.

---

## Actionable Item List

### Item 1 — Make pipeline failures propagate (prerequisite)

Replace the `print(error)`-and-continue pattern in `db_worker.py` (and equivalent silent
excepts in other wsmodules) with raised exceptions caught once at the pipeline level in
`main.py`.

- **Impact: HIGH.** Every other monitoring item is dishonest without it — today a failed DB
  stage still looks like a successful run.
- **Effort: LOW.** ~0.5 day.

### Item 2 — Add a `scrape_runs` table (one row per city per run)

Written by ws at run start and end: city, started/finished timestamps, status
(running/success/failed + error text), and counts (pages fetched, URLs discovered,
new / still-listed / removed ads, rows in `listed_ads` / `removed_ads` after the run).

Replaces `scraped_and_removed.txt`, doubles as the "already ran today" guard (replacing
filesystem marker files in `check_lst_run_state`), and becomes the single source of truth
that items 3, 5, and 6 read.

- **Impact: HIGH.** Turns "check container logs across N cities" into one SQL query; also the
  run-status record the M7 scaling work (Problem 6, non-blocking endpoint) needs anyway.
- **Effort: LOW–MEDIUM.** ~1 day.

### Item 3 — Failure and anomaly emails through the existing SES path

Wrap the pipeline in `main.py` so any exception sends a short
`FAILED: {city} — {stage} — {error}` email. Add threshold checks on run counts:

- discovered ads == 0 → parser broke or ss.lv is blocking
- removed-count > ~30% of table in one run → discovery failure, not real delistings
- zero new ads for N consecutive days → likely silent breakage

The infrastructure (`aws_mailer`, SES credentials) already exists — this is mostly composing
a second, tiny message type.

- **Impact: HIGH.** Converts silence into signal; catches the two most likely real-world
  failures (site layout change, scraper blocked).
- **Effort: LOW.** ~0.5–1 day.

### Item 4 — Backup self-verification + staleness alert

Two parts:

1. **In-process check** in `backup.py` after upload: `head_object` the S3 key and fail loudly
   (SES email) if missing or below a minimum size — a near-empty dump means pg_dump connected
   to an empty DB. This automates the existing `make verify-backup` logic.
2. **Staleness check** — a once-daily step (in the backup container or the Item 6 watchdog)
   that alerts if the newest object in the city's `db-backups` bucket is older than ~26h.
   The staleness check is what catches a silently dead cron, which the in-process check
   cannot.

- **Impact: HIGH.** Backups are the only recovery path for the fresh-volume scenarios the
  recent deploy commits deal with; a silently dead cron means data loss discovered at
  restore time.
- **Effort: LOW.** ~0.5 day.

### Item 5 — A `/status` endpoint on ws

Returns JSON from `scrape_runs`: last run per city, status, counts, duration. Gives the ts
scheduler, the Item 6 watchdog, and the operator (via curl) a machine-readable answer to
"did last night work?" without `docker exec`.

- **Impact: MEDIUM–HIGH.**
- **Effort: LOW.** ~0.5 day once Item 2 exists.

### Item 6 — Host-level watchdog script + daily fleet digest

A single shell/Python script on the EC2 host, run by host cron. For each city in
`config/cities.yaml`:

- container health from `docker inspect` (db, ws, ts, backup)
- last run status/counts from `/status`
- DB table row counts
- S3 backup freshness (newest object age + size)

Then send **one** consolidated email: either a daily one-line-per-city digest, or (quieter)
email only when something is wrong. This is the "not Grafana yet" aggregation layer —
roughly 100 lines of script reusing Items 2–5.

- **Impact: MEDIUM–HIGH.** One email replaces per-city manual checking; scales to 10 cities
  unchanged.
- **Effort: LOW–MEDIUM.** ~1 day.

### Item 7 — Fix the ts→ws trigger feedback loop

Once `/run-task` stops blocking (M7 assessment Problem 6) or `/status` exists: ts fires the
trigger, then checks status ~30–60 min later and logs/emails if the run never started or
failed. Until then, at minimum log the 30s timeout as *expected* and alert only when the
trigger request itself is refused (connection error).

- **Impact: MEDIUM.**
- **Effort: LOW.** ~0.5 day.

### Item 8 — (Defer) CloudWatch/SNS alarms

Alarms on backup bucket PutObject activity, container restart counts, EC2 instance health.
Worth adopting when email-based alerting is outgrown, not before.

- **Impact: MEDIUM.**
- **Effort: MEDIUM.** Deferred — not at this stage.

---

## Recommended Implementation Order

| Order | Item | Rationale |
|-------|------|-----------|
| 1 | Item 1 — error propagation | Everything else reports lies without it |
| 2 | Item 2 — `scrape_runs` table | The data foundation for Items 3, 5, 6 |
| 3 | Item 3 — failure/anomaly emails | Biggest visibility win per hour spent; SES already wired |
| 4 | Item 4 — backup verify + staleness | Protects the recovery path; independent of ws changes |
| 5 | Item 5 — `/status` endpoint | Cheap once Item 2 exists |
| 6 | Item 6 — fleet watchdog digest | Aggregates everything; do last so it has data to read |
| 7 | Item 7 — ts feedback fix | Nice-to-have once Item 5 exists |
| 8 | Item 8 — CloudWatch/SNS | Defer |

**Total effort for Items 1–6: roughly 4–5 focused days.** None of it conflicts with the M7
scaling work — Items 1 and 2 actively support it (the `scrape_runs` table is the same
run-status record M7 Problem 6 needs).
