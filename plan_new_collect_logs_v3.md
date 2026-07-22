# Plan: `scripts/collect_logs_v3.sh` — multi-city aware log & artifact collector

Status: in progress — Phases 1–5 done, Phases 6–10 pending
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

### Phase 1 — Foundation — ✅ DONE

- [x] **1.1** Create `scripts/collect_logs_v3.sh`; `set -euo pipefail`; keep `collect_logs_v2.sh` in place until v3 is verified.
- [x] **1.2** Add `log_info` / `log_warn` / `log_error` matching the `[ts] [LEVEL] msg` format of `deploy-multi-city-ws.sh:10–29`, teeing to `<bundle>/collect.log`.
- [x] **1.3** Extract the `parse_cities()` awk parser into `scripts/lib/cities.sh` and have every caller source it.
  **Note:** the plan said four copies; there were **five** — `deploy-multi-city-ws.sh`, `undeploy-multi-city.sh`, `scripts/backup_db_city.sh`, `scripts/restore_db_city.sh` and `scripts/get_last_s3_file.sh:32`. All five now source the lib. Two path shapes are in use: root scripts source `${SCRIPT_DIR}/scripts/lib/cities.sh`, scripts in `scripts/` source `${SCRIPT_DIR}/lib/cities.sh`.
- [x] **1.4** Implement CLI parsing for every flag in §3, with `--help` in the same style as `restore_db_city.sh:22`. Repeated `--city`/`--services` values are de-duplicated; flags that take a value reject a missing/flag-shaped argument.
- [x] **1.5** Detect `docker compose` vs `docker-compose` (reuse `deploy-multi-city-ws.sh:86–93`).
- [x] **1.6** Preflight: `docker` on PATH and daemon reachable; `config/cities.yaml` present; output dir creatable and writable. All failures exit `2`.
- [x] **1.7** *(pulled forward from 8.5)* `.gitignore` entries for `log-bundles/` and `sslv-logs-*.tar.gz` — needed already, since Phase 1 creates the default output dir inside the repo.

**Phase 1 status:** the script validates inputs, resolves the city list, and lays out the bundle tree (`host/`, `cities/<city>/`, `collect.log`), then exits `0` with a notice that collection is pending. `--running-only` is parsed and recorded but is only *applied* in Phase 2, where discovery lands.

### Phase 2 — Correct multi-city container discovery *(fixes D1, D3)* — ✅ DONE

- [x] **2.1** `find_container(city, service)` matches on `com.docker.compose.project` / `com.docker.compose.service`, using `docker ps -a` so stopped/crashed containers are still found. `container_state()` reports the state via `docker inspect`.
- [x] **2.2** `discover_running_projects()` lists distinct running compose projects and is intersected with the `cities.yaml` list under `--running-only`. Unrelated compose projects on the host are ignored. Exits `2` if no requested city has anything running.
- [x] **2.3** Per-(city, service) status is recorded to `.status.tsv` and rendered as the discovery table in `MANIFEST.txt`. `absent` is reported, not treated as an error. (A TSV file rather than an associative array — bash 3.2 on macOS has none.)
- [x] **2.4** Output dirs are `cities/<city>/<service>/`, created only when a container is actually found, so undeployed cities leave no empty noise.
- [x] **2.5** Each city runs through `collect_city()` behind an `if`; a non-zero return logs a warning, records the city as troubled, and the run continues. Any troubled city downgrades the final exit to `1`.

**Verified against labeled fixture containers:** `ogre` with ws+ts running and db `exited`, `jurmala` with ws only, four cities absent, plus a decoy container named `sslv-ws-standalone` carrying no compose labels. v3 found the exited `ogre-db-1`, kept `jurmala-ws-1` separate, and ignored the decoy entirely — the exact case where v2's `--filter name=ws` misfires. Failure isolation was confirmed by injecting a failure into `ogre`: `jurmala` was still collected and the run exited `1`.

**Not yet applied:** `--since`, `--with-db-dump`, `--with-data-dirs`, `--no-archive` are parsed and recorded in `MANIFEST.txt` but only take effect in Phases 3–8.

### Phase 3 — Log collection *(fixes C1, C2, C5, and rotations)* — ✅ DONE

- [x] **3.1** ws log inventory defined from the §2 table. `aws_mailer.log` is now collected (C1); `sendgrid_mailer.log` retained as best-effort legacy.
- [x] **3.2** Rotations collected — the glob is `*.log*`, so `.log.1`…`.log.9` come along.
- [x] **3.3** `copy_logs()` does one streamed tar per service instead of v2's per-file `docker cp` loop. The container-side program is POSIX `sh`, and it filters the glob down to entries that actually exist, so a partial match (e.g. `backup.log` present, `cron.log` absent) still yields a valid archive *(fixes D8)*.
- [x] **3.4** ts: `/app/*.log*`.
- [x] **3.5** backup: `/var/log/backup.log*` + `/var/log/cron.log` — the service v2 ignored entirely (C2).
- [x] **3.6** `collect_stdout()` writes `docker logs --since --timestamps` to `stdout.log` for all four services incl. `db`, capturing stdout and stderr together *(fixes C5)*.
- [x] **3.7** Capped at `--tail 50000`.
- [x] **3.8** *(added)* **Stopped-container fallback.** `docker exec` requires a running container, so the tar path cannot work on a crashed one — which would have made Phase 2's `docker ps -a` pointless for file logs. `copy_logs_stopped()` falls back to `docker cp` of the known log names. Rotations are unrecoverable this way, and the MANIFEST says so explicitly.

**Verified against fixture containers** (`ogre` ws/ts/db/backup, `jurmala` ws, `sigulda` ws, plus an unlabeled `sslv-ws-standalone` decoy):

| Check | Result |
|---|---|
| Cross-city isolation (D2) | `ogre/ws/logs/ws_main.log` and `jurmala/ws/logs/ws_main.log` hold their own distinct content |
| `aws_mailer.log` (C1) | collected |
| Rotations (3.2) | `ws_main.log`, `.log.1`, `.log.2`; `task_scheduler.log.1`; `backup.log.1` |
| backup service (C2) | `backup.log`, `backup.log.1`, `cron.log` |
| stdout capture (C5) | stderr *and* stdout, RFC3339-timestamped |
| Stopped container | 8 known logs recovered from an exited ws via `docker cp`, flagged `(no rotations: container exited)` |
| No logs present | `logs=0 (none present)`, no empty `logs/` dir created |
| `--since` plumbing | `--since 1s` → 0 lines, `--since 72h` → 2 lines |
| Decoy container | ignored — never attributed to any city |
| Temp files | no `sslv-collect.*` left in `TMPDIR` |

### Phase 4 — Artifacts *(fixes C3, C4)* — ✅ DONE

- [x] **4.1** Artifacts land in `ws/artifacts/`. **The running-container path globs by extension** (`*.csv *.txt *.png *.pdf`) in the ws root rather than enumerating names: one ws container serves exactly one city, so everything there belongs to that city. This picks up the city-scoped *and* legacy names at once and keeps working when a new stage file appears. The stopped-container path cannot glob, so `ws_artifact_names()` emits both `{city}-{name}` and bare `{name}` for every base, mirroring `get_data_files_to_remove()` in `aws_mailer.py` and `file_remover.py`.
- [x] **4.2** `{city}-raw-data-report.txt` and legacy `Ogre-raw-data-report.txt` both collected.
- [x] **4.3** `/data` and `/local_lambda_raw_scraped_data` are copied only under `--with-data-dirs`, tar-streamed via `copy_dir()` rather than globbing `ls` output *(fixes D8)*.
- [x] **4.4** Without the flag, `ws/listings/{data,local_lambda_raw_scraped_data}.txt` record file count, total size and `ls -la` — enough to diagnose "no input file found" at near-zero cost. Absent directories are reported as such.

**Also:** `copy_logs`/`copy_logs_stopped` were renamed `copy_glob_files`/`copy_named_files`, since they now move artifacts as well as logs.

**Verified against fixtures** (`ogre` ws with M7 P7 city-scoped artifacts + both data dirs, `jurmala` ws with its own):

| Check | Result |
|---|---|
| City-scoped names (C3) | all 8 `ogre-*` artifacts collected — the names v2 matched none of |
| Cross-city isolation | `jurmala/ws/artifacts/` held only its own 2 files |
| Logs vs artifacts | `ws_main.log` went to `logs/`, never duplicated into `artifacts/` |
| Listings (4.4) | file count, size and `ls -la`; absent dir reported as "not present" |
| `--with-data-dirs` (4.3) | all 3 files copied under `data-dirs/`, and `listings/` correctly not written |
| Stopped container | all 8 city-scoped artifacts recovered via `docker cp`; data dirs skipped with reason |
| Legacy fallback (4.1/4.2) | bare `pandas_df.csv` and `Ogre-raw-data-report.txt` collected alongside the city-scoped ones |
| Temp files | none leaked |

### Phase 5 — DB dump *(fixes D5, D6, D7)* — ✅ DONE

- [x] **5.1** Opt-in via `--with-db-dump`; default reports `db-dump=off`.
- [x] **5.2** No `-t`. Plain `docker exec`, so nothing turns `\n` into `\r\n` in the SQL stream.
- [x] **5.3** Streamed through `gzip -9` to `pg_backup_{city}_{UTC}.sql.gz`, timestamp `%Y-%m-%dT%H%M%SZ` — no colons.
- [x] **5.4** Non-running db containers are skipped with the reason recorded in the MANIFEST.
- [x] **5.5** `--help` and the MANIFEST both state this is a debug dump that never reaches S3, and point at `scripts/backup_db_city.sh` / `scripts/restore_db_city.sh`.
- [x] **5.6** *(added)* Failure handling: `gzip -t` integrity check, a `MIN_DUMP_BYTES` guard flagging a suspiciously small dump (empty database — same idea as `MIN_BACKUP_SIZE_KB` in `backup.py`), and pg_dump's stderr preserved as `pg_dump-error.txt` when the dump fails, with no truncated `.gz` left behind.
- [x] **5.7** *(added)* Credentials are expanded by the shell **inside** the container, reading the env postgres already has, so the password never appears in this script's argv, its logs, or the bundle.

**Verified against a real Postgres fixture** (500 `listed_ads` + 200 `removed_ads` rows):

| Check | Result |
|---|---|
| Default off (5.1) | `db-dump=off`, only `stdout.log` written |
| **D5 regression** | v3 dump: **0** carriage returns. The same DB dumped with v2's `docker exec -t`: **861**. The bug is real and fixed. |
| Restore | v3 dump restored into a clean Postgres — 500 and 200 rows back |
| Filename (D6) | no colons |
| Integrity (5.3) | `gzip -t` passes |
| Stopped db (5.4) | skipped, reason in MANIFEST, no dump file |
| Empty DB (5.6) | flagged `SUSPICIOUSLY SMALL` at 372 bytes |
| pg_dump failure (5.6) | error text kept as `pg_dump-error.txt`, no truncated `.gz`, city marked troubled, exit `1` |
| Password (5.7) | `testpw123` absent from every file in the bundle |

**Bug found and fixed while testing:** `log()` wrote to **stdout**, and several `collect_*` helpers return their MANIFEST detail string on stdout via `$(...)`. A warning raised inside one of them was captured into that string and landed in the MANIFEST's COLLECTED column instead of the console — visible as `db-dump=` being replaced by the warning text. `log()` now writes to stderr, which is where diagnostics belong and makes every helper safe to call in a command substitution.

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
- [x] **8.5** Add `.gitignore` entries for `log-bundles/` and `sslv-logs-*.tar.gz` — done early as item 1.7.

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
