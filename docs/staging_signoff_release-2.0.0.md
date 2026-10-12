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
- [ ] **S-5 — Backup retention differs between the two backup paths. P0, before sign-off.**
  - The nightly backup container (`src/backup-svc`) keeps every backup: ogre had 21.
  - `scripts/backup_db_city.sh` hard-codes `keep_last=5` and deletes everything older from `db-backups/` after each upload. That script is behind `make backup-city`, `backup-all` and `e2e-backup-restore`.
  - On 2026-10-12 one `e2e-backup-restore CITY=ogre` run deleted 17 ogre staging backups. They had been copied to `s3://sslv-staging-ogre-db-backups/archive-2026-10-12/` first, so nothing was lost.
  - **Risk:** the production cutover runbook starts with a manual backup (R-4). `make backup-all M6_ENV=prod` would cut every production city bucket down to 5 backups.
  - **Fix:** use one retention rule for both paths. Make the script's limit a setting (`BACKUP_KEEP_LAST`) that defaults to **no pruning**, or to a count well above the nightly history (e.g. 60 days). Log what would be pruned before deleting, and apply the same rule in the backup container if pruning is wanted there.
  - **Tests:** a stub-`aws` test in the style of `test_28`: the default deletes nothing, an explicit limit deletes only the oldest beyond it, and `archive-*/` prefixes are never touched.
  - **Later:** decide whether to move the 17 archived ogre objects back into `db-backups/`.

## 2. Proofs

- [x] **P-1 — `make e2e-backup-restore CITY=ogre M6_ENV=staging`** (2026-10-12 17:45): passed. Backup, S3 check and scratch restore all worked, with rows 43/36/23 matching live, and no `psql` errors. It used the **db container's** `pg_dump` (via `backup_db_city.sh`), so it does not cover the backup container (P-3).
- [ ] **P-2 — Restores fail on errors, and old dumps load.**
  - `restore_db_city.sh --scratch` only counts `ERROR` lines and warns. Make it fail on any error, as the live restore does (`ON_ERROR_STOP`).
  - Make the live and scratch restores drop `SET transaction_timeout` when loading a `pg_dump` 17 dump into Postgres 15, so the backups taken before B-3 can be restored.
  - Test one old (17) and one new (15) dump.
- [ ] **P-3 — A backup made by the backup container restores, with errors failing.** After P-2, run `make test-restore CITY=ogre M6_ENV=staging`. It restores the latest backup in a throwaway container, reads S3 only and deletes nothing. The latest backup must be a 02:00 one: the header should read `deb12u1`, not `pgdg13`.
- [ ] **P-4 — Alerts still fire.** `make watchdog-drill M6_ENV=staging`.

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
