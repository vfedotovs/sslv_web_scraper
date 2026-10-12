# Staging sign-off plan — `release-2.0.0`

**Host:** `staging-eu-north-1`, deploy dir `~/test-staging-1-7-9-23` (the only one; older dirs are archived in `~/archive/old-deploys-2026-10-12/`).
**Build on staging:** `b2dd36e` (`v1.5.12-131-gb2dd36e`), deployed 2026-10-12 17:38 UTC.
**Related:** [`staging_review_dev-1.7.9.23.md`](staging_review_dev-1.7.9.23.md) (B-items), [`release-2.0.0_main_merge_inventory.md`](release-2.0.0_main_merge_inventory.md) (merge, R-0).

Staging passes when every item in sections 1–3 is done.

---

## 1. Fixes found on staging

- [x] **S-1 — Report header count.** `main`'s header said "Total active listings: 5" for jurmala, which has 301 active. The table only holds the ads fetched in this run, so the line is now "New listings in this report: N" (`b2dd36e`). *Check:* the 2026-10-13 emails.
- [x] **S-2 — `M6_ENV` case.** `make fleet-status M6_ENV=Staging` reported all six cities BAD, because it looked for `sslv-Staging-*` buckets. Now `make` lowercases `M6_ENV` and stops on unknown values, and `fleet_watchdog.py --env` does the same (`b2dd36e`). Verified on the host.
- [x] **S-3 — Watchdog ran old code.** The systemd units used `~/prepord-test-branch-dev-1794`. They were reinstalled with `make watchdog-install M6_ENV=staging` from the release dir. Settings are unchanged, and the first check was OK (2026-10-12 17:41).
- [x] **S-4 — Old deploy dirs.** Four old dirs that each had a `docker-compose.yml` were archived and removed, so only one deployment can exist.
- [x] **S-5 — Backup retention differs between the two backup paths. P0, before sign-off.**
  - The nightly backup container (`src/backup-svc`) keeps every backup: ogre had 21. There is no S3 lifecycle rule on the staging or prod ogre buckets either.
  - `scripts/backup_db_city.sh` hard-coded `keep_last=5` and deleted everything older from `db-backups/` after each upload. That script is behind `make backup-city`, `backup-all` and `e2e-backup-restore`.
  - On 2026-10-12 one `e2e-backup-restore CITY=ogre` run deleted 17 ogre staging backups. They had been copied to `s3://sslv-staging-ogre-db-backups/archive-2026-10-12/` first. The staging bucket is also versioned, so the 17 are still there as delete markers.
  - **Risk:** **prod buckets are not versioned** (checked: `sslv-prod-ogre-db-backups`). The production cutover runbook starts with a manual backup (R-4), and `make backup-all M6_ENV=prod` would have deleted all but 5 backups in every prod city bucket, permanently.
  - **Fixed:**
    - Pruning is opt-in: `--keep-last N`, or `BACKUP_KEEP_LAST=N` with `make`. The default is 0, which deletes nothing, matching the nightly container.
    - The script logs `pruning X of Y` before deleting, and only touches dated `db-backups/YYYY/MM/DD/pg_backup_*.sql.gz` keys.
    - The value is fixed before `.env.<city>` is sourced, and anything that isn't a number stops the script before any backup.
    - The GNU-only `head -n -N` is gone.
  - **Tests:** `tests/test_35_backup_retention.py` (10, stub `aws`/`docker`).
  - **Later:** decide whether to move the 17 archived ogre objects back into `db-backups/`, and whether prod buckets should get versioning or a lifecycle rule.

## 2. Proofs

- [x] **P-1 — `make e2e-backup-restore CITY=ogre M6_ENV=staging`** (2026-10-12 17:45): passed. Backup, S3 check and scratch restore all worked, with rows 43/36/23 matching live, and no `psql` errors. It used the **db container's** `pg_dump` (via `backup_db_city.sh`), so it does not cover the backup container (P-3).
- [x] **P-2 — Restores fail on errors, and old dumps load.**
  - `restore_db_city.sh --scratch` now loads like the live restore: `ON_ERROR_STOP`, one transaction, and it fails with psql's first error. Before, it counted `ERROR` lines and only warned.
  - A shared `prepare_load_file` step is used by the scratch, live and `--prepare-init` restores. It drops `SET transaction_timeout` when the dump is from `pg_dump` 17+ and the target server is older than 17. It also keeps the existing `\restrict` handling for an older `psql`.
  - `--prepare-init` targets the version in `src/db/Dockerfile` (`postgres:15`), whose init scripts also run with `ON_ERROR_STOP`.
  - **Tests:** `tests/test_36_restore_load.py`, 9 tests with a stub `docker` acting as a Postgres 15 server. 6 of them fail on the old script.
  - **Real Docker, locally (2026-10-12):** genuine `pg_dump` 17.11 and 15.19 dumps of the staging ogre data, and a broken dump.
    - `--scratch`: the 17 dump loads with the line dropped (43/35/22), the 15 dump loads unchanged, and the broken dump fails with exit 1.
    - Live (`--yes`): the 17 dump replaces the DB, and the broken dump rolls back with the previous data kept.
  - Also fixed `--date YYYY_MM_DD`. It guessed the key `pg_backup_YYYY_MM_DD.sql.gz`, which never matches the real `pg_backup_YYYYMMDD_HHMMSS.sql.gz` names, so it always failed. It now restores the newest backup of that day (3 more tests, 12 in total).
  - The staging run against real S3 backups is P-3.
- [x] **P-3 — A backup made by the backup container restores, with errors failing.** Run on staging with `5b3e8ee`, 2026-10-12 17:59. Read S3 only, throwaway containers, nothing left behind.
  - `make test-restore M6_ENV=staging`: **6/6 OK** in strict mode. Five cities restored their 02:00 backup from the new backup container (`pg_dump 15.19 … deb12u1`), e.g. salaspils 24/18/24 and jurmala 301/141/23. Ogre restored its 17:45 e2e backup (db container, `pgdg13`): 43/36/23.
  - Old `pg_dump` 17 backup, `--date 2026_10_11` for ogre (`17.11 … deb13u1`, has `SET transaction_timeout`): dropped the line and restored OK, 43/35/22.
  - Follow-up in the soak: after the 2026-10-13 02:00 backup, `make test-restore CITY=ogre M6_ENV=staging` covers ogre's first backup from the new container.
- [x] **P-4 — Alerts still fire.** `make watchdog-drill M6_ENV=staging` on `5b3e8ee`, 2026-10-12 18:00: **8/8 PASS**.
  - Alert and recovery pushes for memory, disk, backup, oom, stuck-run, collapse and container (a real `docker stop salaspils-ts-1`), plus the heartbeat: 15 `[DRILL]` pushes accepted by ntfy.
  - Afterwards the watchdog timer resumed, `salaspils-ts-1` was healthy and rescheduled for 00:40, and all containers were healthy.
  - **Manual:** confirm the 15 `[DRILL]` notifications arrived on the phone. Check #7 (missing heartbeat) stays a manual one-day test (`docs/critical_monitoring_ntfy_plan.md`).

## 3. Soak (V-6): 3 consecutive clean nights

| Night | Build | 00:40 scrape | 01:40 verify | 02:00 backup | Watchdog | Notes |
|---|---|---|---|---|---|---|
| 1 — 2026-10-12 | `3955e4f` | 6/6 success | 6/6 OK | 6/6, `pg_dump` 15.19 | no alerts | jurmala peak RSS 122 MB. Found S-1 and S-2 |
| 2 — 2026-10-13 | `b2dd36e` | | | | | first night with S-1 |
| 3 — 2026-10-14 | `b2dd36e` | | | | | |

Each morning: `make fleet-status M6_ENV=staging`, plus `scrape_runs`, the emails (subject version, `[staging]`, header), backups (`pg_dump` header), and `ws` memory.

- [ ] **L-1 — Final evidence.** After night 3, run `make collect-logs` on the host, review the bundle, and record the sign-off here.

## 4. Before production (not needed to pass staging)

- [ ] Remove the false `ERROR` lines: `remove_tmp_files … No such file` and the analytics "DataFrame is empty" line (review item 7).
- [ ] Rewrite `staging.yml` like `main.yml`, or disable it. It still has the single-city deploy, which removes all containers and images.
- [ ] README top half for multi-city (M-7).
- [ ] Production cutover runbook (R-4/R-5): backup first (needs **S-5**), cities moved one at a time, rollback.
- [ ] Deploys after the nightly run only skip the post-deploy check. Decide on a `force` option for `/run-task`.
