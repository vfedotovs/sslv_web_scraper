# Plan: `scripts/collect_logs_v3.sh` — multi-city aware log & artifact collector

Status: proposed
Branch: `dev-1.7.8.1`
Supersedes: `scripts/collect_logs_v2.sh`
Related: `deploy-multi-city-ws.sh`, `undeploy-multi-city.sh`, `scripts/backup_db_city.sh`, `scripts/restore_db_city.sh`, `config/cities.yaml`

---

## 1. Review of `collect_logs_v2.sh` (current state)

`collect_logs_v2.sh` was written for the **single-city, single-stack** era (one `ws`, one `ts`, one `db` on the host). Under the current multi-city deployment it is not just incomplete — it is actively broken.

### 1.1 Blocking defects under multi-city

| # | Line(s) | Defect | Impact |
|---|---------|--------|--------|
| D1 | 10–12 | `docker ps --filter "name=ws"` matches **every** city's ws container (`ogre-ws-1`, `jurmala-ws-1`, …). The result is a **multi-line string** assigned to a scalar. | Every subsequent `docker exec "$ws_container"` fails or silently targets a mangled name. With 6 cities the script is unusable. |
| D2 | 41, 53, 68, 78 | `docker cp "$container:$log" .` — all cities write into the **same CWD** with the **same filenames**. | Cities overwrite each other. No way to tell whose `analytics.log` you got. |
| D3 | 12 | `--filter "name=db-1"` also matches the *backup* stack naming and all cities. | Same as D1. |
| D4 | 3 | `set -e` without `-u`/`-o pipefail`; a single missing container aborts the whole collection. | One unhealthy city kills the run for all others. |
| D5 | 84 | `docker exec -t` for `pg_dump`. The `-t` allocates a TTY which **injects `\r` (CRLF)** into the SQL stream. | Dumps are subtly corrupt and can fail to restore. Known classic. |
| D6 | 84 | Output filename `pg_backup_...T%H:%M:%S.sql` contains **colons**. | Breaks on volume-mounted/exFAT paths and is ambiguous with `docker cp`'s `container:path` syntax. |
| D7 | 84 | Uncompressed plain SQL dump, unconditional, for **every** city. | 6 × full DB dumps on each log collection. Slow, huge, and a data-exfil footgun for a "collect logs" script. |
| D8 | 52 | `docker exec ... bash -c "ls $folder/*"` — `bash` may not exist in slim images; glob expansion of a large `data/` dir hits `ARG_MAX`; no `nullglob`. | Fails or truncates on cities with a long history. |

### 1.2 Content that is stale or missing

| # | Item | Detail |
|---|------|--------|
| C1 | `sendgrid_mailer.log` collected, `aws_mailer.log` **not** | SES is the active mailer (`src/ws/app/wsmodules/aws_mailer.py:52`). `alert_mailer.py:47` also writes to `aws_mailer.log`. The one log that matters for mail failures is never collected. |
| C2 | `backup` container **entirely absent** | `{city}-backup-1` exists in every deploy (`--profile backup`). Its `/var/log/backup.log` and `/var/log/cron.log` are the only record of daily DB backup success/failure. |
| C3 | City-prefixed artifacts not handled | M7 P7 introduced `city_file()` (`src/ws/app/wsmodules/file_paths.py`). Real filenames are now `jurmala-pandas_df.csv`, `jurmala-cleaned-sorted-df.csv`, `jurmala-email_body_txt_m4.txt`. v2's hardcoded un-prefixed names match **nothing**. |
| C4 | Newer artifacts missing | `{city}-discovered-urls.txt`, `{city}-basic_price_stats.txt`, `{city}-email_body_add_dates_table.txt` (see `aws_mailer.py:65–80`). |
| C5 | No `docker logs` (stdout/stderr) | Uvicorn tracebacks, container crash output, and Postgres startup errors live **only** in the Docker json-file log, never on disk inside the container. |
| C6 | No container/host state | No `docker ps`, no health-check history (`docker inspect .State.Health`), no image tags / `RELEASE_VERSION`, no disk usage, no `docker compose ls`. |
| C7 | Host-side deploy log ignored | `deploy-multi-city.log` (written by `deploy-multi-city-ws.sh:7`) is the first thing you need when a city failed to come up. |
| C8 | No archive, no manifest | Output is a pile of loose files in CWD. Nothing to attach to a ticket. |
| C9 | No redaction story | `.env.{city}` / `.env.prod` and `docker inspect` output carry `AWS_SECRET_ACCESS_KEY` and `POSTGRES_PASSWORD`. v2 doesn't collect them today, but v3 wants container config — so redaction becomes **mandatory**, not optional. |

### 1.3 What v2 got right (keep)

- Existence check before copy (`test -f`) rather than failing on missing files.
- Start/end timestamp logging.
- Graceful "no ws container → exit 0".

---

## 2. Architecture facts v3 must encode

Established from the current tree — these are the ground truth the script depends on.

**Naming.** `deploy-multi-city-ws.sh:299` runs `$COMPOSE_CMD --project-name "$city" … up -d`. Containers are therefore `{city}-db-1`, `{city}-ws-1`, `{city}-ts-1`, `{city}-backup-1`, where `{city}` is a top-level key of `config/cities.yaml`.

**City list.** `config/cities.yaml` → `salaspils`, `sigulda`, `marupes_pag`, `adazu_nov`, `ogre`, `jurmala`. Note underscores in keys; `deploy-multi-city-ws.sh:194` maps to slugs with `${city//_/-}` for S3 bucket names.

**Do not match containers by name substring.** Match by the compose label instead:
`com.docker.compose.project` = city, `com.docker.compose.service` = `ws|ts|db|backup`.
This is exact, survives renames, and is the only thing that reliably separates cities.

**Working directories.** `src/ws/Dockerfile` declares **no `WORKDIR`** → ws logs and artifacts land in **`/`**. `src/ts/Dockerfile:3` → `WORKDIR /app`. `src/backup-svc/Dockerfile:10` → `/app`, but logs go to `/var/log`.

**The ws container has no `CITY` env var** (see `docker-compose.yml` ws service). City must come from the compose project label or be passed in — never inferred from container env.

**Complete log inventory (verified):**

| Service | Path in container | Source |
|---|---|---|
| ws | `/ws_main.log` | `main.py:51` |
| ws | `/web_scraper.log` | `web_scraper.py:97` |
| ws | `/raw_data_report_formatter.log` | `data_format_changer.py:62` |
| ws | `/dataframe_sanitizer.log` | `df_cleaner.py:51` |
| ws | `/dbworker.log` | `db_worker.py:53`, `scrape_runs.py:42` |
| ws | `/analytics.log` | `analytics.py:56` |
| ws | `/aws_mailer.log` | `aws_mailer.py:53`, `alert_mailer.py:48` |
| ws | `/s3_file_downloader.log` | `file_downloader.py:24` |
| ws | `/sendgrid_mailer.log` | `sendgrid_mailer.py:40` (legacy, best-effort) |
| ts | `/app/task_scheduler.log` | `ts.py:36` |
| backup | `/var/log/backup.log` | `backup.py:27` |
| backup | `/var/log/cron.log` | `backup-svc/Dockerfile:30` |

All ws/ts logs are `RotatingFileHandler` → **`.log.1` … `.log.9` rotations exist and must be collected too** (v2 collects only `.log`).

**Artifact inventory (city-prefixed via `city_file()`):**
`{city}-pandas_df.csv`, `{city}-cleaned-sorted-df.csv`, `{city}-email_body_txt_m4.txt`, `{city}-basic_price_stats.txt`, `{city}-email_body_add_dates_table.txt`, `{city}-discovered-urls.txt`, `{city}-raw-data-report.txt`, plus dirs `/data/` and `/local_lambda_raw_scraped_data/`. Legacy un-prefixed names still occur for `ogre` — support both.

---

## 3. Target design for v3

```
scripts/collect_logs_v3.sh [OPTIONS]

  --city CITY           Collect one city (repeatable)
  --all                 Collect every city in config/cities.yaml (default)
  --running-only        Only cities that currently have containers up
  --services LIST       Comma list: ws,ts,db,backup       (default: all)
  --since DURATION      docker logs --since window        (default: 72h)
  --with-db-dump        Include pg_dump per city          (default: OFF)
  --with-data-dirs      Include /data + /local_lambda_...  (default: OFF, large)
  --no-redact           Skip secret scrubbing             (default: redact ON)
  --output-dir DIR      Destination root                  (default: ./log-bundles)
  --no-archive          Leave the tree unpacked
  -h, --help
```

**Output layout** — one bundle, one archive, per-city isolation (fixes D2):

```
log-bundles/sslv-logs-2026-07-22T10-31-05Z/
├── MANIFEST.txt              # what was collected, what was skipped + why
├── SUMMARY.txt               # health matrix + last ERROR per city
├── host/
│   ├── docker-ps.txt
│   ├── docker-compose-ls.txt
│   ├── docker-images.txt
│   ├── docker-system-df.txt
│   ├── df-h.txt
│   ├── uname.txt
│   └── deploy-multi-city.log
└── cities/
    ├── ogre/
    │   ├── ws/{logs/*.log*, artifacts/*, stdout.log, inspect.json, health.json}
    │   ├── ts/{logs/task_scheduler.log*, stdout.log, inspect.json, health.json}
    │   ├── db/{stdout.log, inspect.json, health.json, pg_backup_*.sql.gz}
    │   └── backup/{logs/backup.log*, logs/cron.log, stdout.log, inspect.json}
    └── jurmala/…
```

---

## 4. Actionable item list

### Phase 1 — Foundation

- [ ] **1.1** Create `scripts/collect_logs_v3.sh`; `set -euo pipefail`; keep `collect_logs_v2.sh` in place until v3 is verified.
- [ ] **1.2** Add `log_info` / `log_warn` / `log_error` matching the `[ts] [LEVEL] msg` format of `deploy-multi-city-ws.sh:10–29`, teeing to `<bundle>/collect.log`.
- [ ] **1.3** Copy the `parse_cities()` awk parser from `deploy-multi-city-ws.sh:39–62` (also present in `backup_db_city.sh:77`, `restore_db_city.sh:64`). **Extract it once** into `scripts/lib/cities.sh` and have all four scripts source it — three divergent copies is a latent bug.
- [ ] **1.4** Implement CLI parsing for every flag in §3, with `--help` in the same style as `restore_db_city.sh:22`.
- [ ] **1.5** Detect `docker compose` vs `docker-compose` (reuse `deploy-multi-city-ws.sh:86–93`).
- [ ] **1.6** Preflight: `docker info` reachable; `config/cities.yaml` present; output dir writable. Fail fast with a clear message.

### Phase 2 — Correct multi-city container discovery *(fixes D1, D3)*

- [ ] **2.1** Implement `find_container(city, service)`:
  ```bash
  docker ps -a \
    --filter "label=com.docker.compose.project=${city}" \
    --filter "label=com.docker.compose.service=${service}" \
    --format '{{.Names}}' | head -n1
  ```
  Use `-a` so **stopped/crashed** containers are still collected — those are the ones you actually need logs from.
- [ ] **2.2** Implement `discover_cities()` for `--running-only`: list distinct `com.docker.compose.project` labels and intersect with `cities.yaml`.
- [ ] **2.3** Record per-(city, service) status — `running` / `exited` / `absent` — into `MANIFEST.txt`. Absent ≠ error.
- [ ] **2.4** Guarantee **per-city output directories** so no cross-city overwrite is possible.
- [ ] **2.5** Isolate per-city failures: wrap each city in a function, `|| { log_warn; continue; }`. One broken city must never abort the run *(fixes D4)*.

### Phase 3 — Log collection *(fixes C1, C2, C5, and rotations)*

- [ ] **3.1** Define the ws log array from the §2 table — **add `aws_mailer.log`**, keep `sendgrid_mailer.log` as best-effort legacy.
- [ ] **3.2** Collect **rotated** files: glob `*.log*` rather than exact names, so `.log.1`…`.log.9` come along.
- [ ] **3.3** Replace the per-file `docker cp` loop with a single streamed tar per service — one exec instead of N, and it handles globs and missing files cleanly:
  ```bash
  docker exec "$c" sh -c 'tar cf - -C / *.log* 2>/dev/null' | tar xf - -C "$dest/logs"
  ```
  Use `sh`, not `bash` — `python:3.8-slim-buster` has no guarantee of bash *(fixes D8)*.
- [ ] **3.4** Add **ts**: `/app/task_scheduler.log*`.
- [ ] **3.5** Add **backup** (new): `/var/log/backup.log*`, `/var/log/cron.log`.
- [ ] **3.6** Add `docker logs --since "$SINCE" --timestamps` → `stdout.log` for **all four** services incl. `db`. This is the only place uvicorn tracebacks and Postgres startup errors appear *(fixes C5)*.
- [ ] **3.7** Cap `docker logs` with `--tail 50000` to keep bundles sane on long-running stacks.

### Phase 4 — Artifacts *(fixes C3, C4)*

- [ ] **4.1** Build the artifact list through the `city_file()` convention: try `{city}-{name}` first, fall back to bare `{name}` (legacy `ogre`). Mirror the list in `aws_mailer.py:65–80`.
- [ ] **4.2** Collect `{city}-raw-data-report.txt` and `Ogre-raw-data-report.txt`.
- [ ] **4.3** Put `/data/` and `/local_lambda_raw_scraped_data/` behind `--with-data-dirs` (off by default — these grow without bound). When enabled, tar-stream the directory rather than globbing `ls` output *(fixes D8)*.
- [ ] **4.4** When data dirs are off, still record a **listing** (`ls -la`) of both dirs plus file counts — usually enough to diagnose "no input file found", at ~zero cost.

### Phase 5 — DB dump *(fixes D5, D6, D7)*

- [ ] **5.1** Make the dump **opt-in** via `--with-db-dump`. A log collector should not exfiltrate 6 full databases by default.
- [ ] **5.2** Drop the `-t` flag — use `docker exec -i` (or no flag). Prevents CRLF corruption.
- [ ] **5.3** Pipe through `gzip -9`; filename `pg_backup_{city}_YYYY-MM-DDTHHMMSSZ.sql.gz` — **no colons**.
- [ ] **5.4** Skip cleanly when the db container is not `running`, and log the skip.
- [ ] **5.5** In `--help` and `MANIFEST.txt`, point at `scripts/backup_db_city.sh` as the correct tool for real backups — this dump is for **debugging only** and does not go to S3.

### Phase 6 — Environment & state capture *(fixes C6, C7)*

- [ ] **6.1** `host/`: `docker ps -a`, `docker compose ls`, `docker images`, `docker system df`, `df -h`, `uname -a`, docker/compose versions.
- [ ] **6.2** Copy host-side `deploy-multi-city.log` into `host/` *(fixes C7)*.
- [ ] **6.3** Per container: `docker inspect` → `inspect.json`, and `.State.Health` → `health.json` (health-check failure history is the fastest route to "why is ws unhealthy").
- [ ] **6.4** Capture `RELEASE_VERSION` and image digest per city — needed to correlate a bug with a deployed build.
- [ ] **6.5** Capture the `SCRAPE_URL_LIMIT` / `SCRAPE_DELAY_SEC` / `TASK_TIME` / `VERIFY_TIME` effective values (post-redaction) — these change scraper behaviour and are the usual suspects.
- [ ] **6.6** Probe `ws:8000/status` from inside the network per city and save the JSON:
  ```bash
  $COMPOSE_CMD --project-name "$city" run --rm --no-deps curlimages/curl \
    -s --max-time 10 http://ws:8000/status
  ```
  (`main.py:99` — same pattern as the post-deploy trigger at `deploy-multi-city-ws.sh:307`.)

### Phase 7 — Redaction *(fixes C9 — required before Phase 6 output is shareable)*

- [ ] **7.1** Implement `redact()` over all text output, on by default. Mask `AWS_SECRET_ACCESS_KEY`, `AWS_ACCESS_KEY_ID`, `POSTGRES_PASSWORD`, `DB_PASSWORD`, `SENDGRID_API_KEY`, and any `AKIA[0-9A-Z]{16}`.
- [ ] **7.2** Apply to `inspect.json` specifically — `.Config.Env` is a plaintext dump of every secret in `docker-compose.yml`.
- [ ] **7.3** Never collect `.env.*` or `database.ini`. Record only *presence* + mtime.
- [ ] **7.4** `--no-redact` must print a loud warning and stamp `REDACTION: DISABLED` into `MANIFEST.txt`.
- [ ] **7.5** Add a self-test: grep the finished bundle for the secret patterns; abort with a non-zero exit if any hit survives.

### Phase 8 — Packaging & summary *(fixes C8)*

- [ ] **8.1** Write `MANIFEST.txt`: timestamp, host, script version, flags used, per-(city, service) collected/skipped table with reasons, redaction state.
- [ ] **8.2** Write `SUMMARY.txt`: a health matrix (city × service → state) plus the last 5 `ERROR`/`CRITICAL` lines from each city's ws logs. This is the artifact a human reads first.
- [ ] **8.3** `tar czf sslv-logs-<ts>.tar.gz`, print the absolute path and human-readable size on exit. `--no-archive` to skip.
- [ ] **8.4** Exit codes: `0` all requested cities collected; `1` partial; `2` fatal preflight failure.
- [ ] **8.5** Add `.gitignore` entries for `log-bundles/` and `sslv-logs-*.tar.gz` — the repo already ignores `*.log`/`*.txt`/`*.csv` broadly, but not the bundle dir or the tarball.

### Phase 9 — Integration & docs

- [ ] **9.1** Add `make collect-logs` (all cities) and `make collect-logs CITY=jurmala`.
- [ ] **9.2** Document in `README.md` and `CLAUDE.md` under a "Log collection (multi-city)" heading, next to the backup/restore flow.
- [ ] **9.3** Optional `--upload-s3` writing to `s3://sslv-{env}-{city-slug}-scraped-data/log-bundles/{date}/` — reuse the `${city//_/-}` slug rule from `deploy-multi-city-ws.sh:194`. Keep off by default; redaction self-test (7.5) must pass before any upload.
- [ ] **9.4** Deprecate `collect_logs_v2.sh`: header comment pointing at v3, remove after one release cycle.

### Phase 10 — Verification

- [ ] **10.1** Single running city → correct tree, no cross-city leakage.
- [ ] **10.2** All 6 cities → 6 isolated dirs, all logs present, sane runtime and bundle size.
- [ ] **10.3** One city stopped, one never deployed → both handled, exit `0`/`1` as designed, reasons in `MANIFEST.txt`.
- [ ] **10.4** `--with-db-dump` → `gunzip -t` passes and the dump contains **no `\r`** (`grep -c $'\r'` == 0) — direct regression test for D5.
- [ ] **10.5** Redaction self-test on a bundle from a real deploy — zero secret hits.
- [ ] **10.6** Run on the EC2 production host; confirm no interference with the `{city}-backup-1` cron at 02:00.

---

## 5. Suggested ordering

Phases 1 → 2 → 3 give a working, correct multi-city collector and can ship on their own. **Phase 7 (redaction) must land before Phase 6 output is shared anywhere**, since `inspect.json` carries every secret in the compose file. Phases 8–9 are polish. Phases 4, 5 and 10 can proceed in parallel with the rest.

Minimum viable v3: **Phases 1, 2, 3, 8.1–8.3** — that alone fixes every blocking defect in §1.1 and the two worst content gaps (`aws_mailer.log`, `backup` container).
