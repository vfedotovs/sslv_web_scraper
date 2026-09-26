# Backup size alerting: fewer false positives — implementation plan

Branches: `dev-1.7.9.16` (items 1, 2), `dev-1.7.9.17` (items 3, 6) · Source: `make fleet-status` on the preprod host, 2026-09-26 13:22 UTC

## 0. What the 2026-09-26 report actually says

| Signal | Verdict | Why |
|---|---|---|
| `bkp: 2KB` / `5KB` < 10 KB | **False positive** | The DBs hold 24–318 listed + 6–16 removed rows. A gzip'd `pg_dump --clean` of that is 2–5 KB. A fixed 10 KB floor can only work for a large prod DB. |
| `bkp: 91h` > 26h | **Probably real — needs checking before it is tuned** | Every city's newest object is from 2026-09-22 18:33–18:34 UTC, 4 s apart. That looks like one manual `backup-all` run, not the 02:00 cron. The daily cron has not written to **these** buckets since then. |
| Buckets are `sslv-prod-*` | **Possibly the wrong env** | `fleet-status` defaults to `M6_ENV=prod`. The host folder is `prepord-test-branch-*`, and LA:24 looks like a fresh DB, not prod history. If this host is staging, the report checked prod buckets that this host never writes to. No `host_env_warn` line appeared, so `/etc/sslv-watchdog.env` is either missing or says `ENV=prod`. |

**Conclusion:** the size floor needs to change (items 1–6), but the age alert is not a false positive. Confirm which env this host runs (item 7, logs below) before changing anything about age.

### Update 2026-09-26 13:33: logs from the host

- The host is **staging** (`/etc/sslv-watchdog.env`: `ENV=staging`, `MIN_BACKUP_SIZE_KB=1`). `make fleet-status M6_ENV=staging` reports 0 problems, and staging backups are 12h old. **The age alerts came from checking prod buckets from the staging host.** No prod host has written to them since the 2026-09-22 cleanup.
- **The false positive that is still active is the backup container.** `ogre-backup-1` has no `MIN_BACKUP_SIZE_KB`, so `backup.py` used its 10 KB default. Every night since 2026-09-23 it uploads a good 2.7–3.0 KB dump, then logs `FAILED at s3_verify` and sends an SES alert. `docker-compose.yml` also defaulted it to 10.
- Calibration from staging: ogre has 58 rows in 2,956 B and jurmala 334 rows in ~8 KB, so data costs ~19 B/row gzip'd on top of ~1.9 KB of schema. Size grows ~70 B/day.
- Minor: `docker logs` shows every backup line twice, because both `cron.log` and `backup.log` are tailed to stdout. `pgrep` is missing from the image.

## 1. Stop the noise now

- [x] On the staging host, run `make fleet-status M6_ENV=staging`: 0 problems.
- [x] Watchdog timers already use `ENV=staging` and `MIN_BACKUP_SIZE_KB=1`.
- [x] **Stop the nightly `s3_verify` alert email.** `MIN_BACKUP_SIZE_KB` now defaults to 1 (a hard floor for a truncated or failed dump) in `backup.py`, `docker-compose.yml`, `env.example`, `verify_backup.sh`, the watchdog and the Makefile. The Makefile's per-env 1/10 switch is removed. The message now says "truncated or failed" instead of "near-empty dump, DB was likely empty". Takes effect on the next deploy, when the backup containers are recreated.
- [x] The report header names the env and the thresholds: `SSLV fleet status [staging] — ...` followed by `thresholds: run/backup age 26h/26h, backup floor 1 KB + 5 B/row, shrink < 50% of median`. The email subject carries `[env]` too.

## 2. Make the size check depend on the data, not a constant

`check_backup()` in `scripts/fleet_watchdog.py` now runs three separate tests, each with its own message. It reads the newest 1 + `BACKUP_HISTORY_N` objects in the same single `list-objects-v2` call as before.

- [x] **2a. Hard floor:** `size < MIN_BACKUP_SIZE_KB` (default 1 KB) → "the dump is truncated or failed". When this fires, 2b is skipped so one bad dump does not raise two problems.
- [x] **2b. Expected size from live row counts:** `size < floor + (LA+RA) × BACKUP_MIN_BYTES_PER_ROW` → "it likely does not contain the data". This uses one parameter, not the BASE/ratio pair first planned. The measured ~19 B/row (item 0) gives a 5 B/row default, about ¼ of what staging uses. Ogre (58 rows, 2.9 KB) expects ≥ 1.3 KB. The 2026-09-21 case (2.6 KB for thousands of rows) expects ≥ 25 KB for 5,000 rows.
- [x] **2c. Shrink versus history:** newest < `BACKUP_SHRINK_RATIO` (0.5) × the median of the previous backups (up to `BACKUP_HISTORY_N`=7; the buckets keep the newest 5, so 4 in practice). Skipped with fewer than 3 previous backups.
- [x] 2b is skipped when the row counts are unknown (`LA:?`). That case already raises its own "could not read table row counts" problem.
- [ ] Severity: all three still use the `newest backup` prefix, so they push as **urgent**. Splitting them into CRIT/WARN is item 6.
- [ ] Check the 5 B/row default against prod once prod runs again (item 5).

## 3. Record what went into the dump (backup side)  ✅ `dev-1.7.9.17`

- [x] `backup.py:count_db_rows()` counts `listed_ads`/`removed_ads` with `psql` just before `pg_dump`. It never raises: a failed count only skips the row checks.
- [x] The upload carries S3 metadata `env`, `city`, `listed-ads` and `removed-ads`. The row counts are left out when the count failed.
- [x] `verify_backup_in_s3(bucket, key, rows, previous)`:
  - **CRIT (raise → email + exit 1):** object missing; below the 1 KB floor; or the DB has fewer than `BACKUP_SHRINK_RATIO` × the rows of the previous backup, read from that backup's metadata. `removed_ads` is history, so the total only grows. The alert says today's dump is stored but is of the damaged DB, and to restore from the previous one.
  - **WARN (log only):** size < floor + rows × `BACKUP_MIN_BYTES_PER_ROW`.
  - Previous backups made before this change have no metadata, so the row-drop check starts with the second backup after deploy.
- [x] Watchdog `head-object` on the newest backup (CRIT):
  - the metadata `env`/`city` differs from the checked env/city (the 2026-09-21 incident);
  - live rows < ratio × dump rows: the DB lost data since the dump, restore before the next backup;
  - dump rows < ratio × live rows: not a dump of this DB.
  - The size-per-row warning uses the dump's own row count when recorded, else the live one.
  - The `bkp:` summary shows the dump's row count (e.g. `bkp:3h 2KB 57r`). A missing `r` means head-object failed (needs `s3:GetObject`) or the dump predates this change. Those checks are then skipped.
- [ ] Limitation: the backup.py row-drop alert fires once. The next night's "previous" is already the damaged dump. The watchdog's live-vs-dump check and the size-shrink warning cover the days after.

## 4. Configuration

- [x] Env and CLI settings, with defaults in `env.example`: `MIN_BACKUP_SIZE_KB=1` (the hard floor, kept under its old name), `BACKUP_MIN_BYTES_PER_ROW=5`, `BACKUP_SHRINK_RATIO=0.5`, `BACKUP_HISTORY_N=7`. The CLI flags are `--min-backup-size-kb`, `--backup-min-bytes-per-row`, `--backup-shrink-ratio` and `--backup-history`.
- [ ] Optional per-city override in `config/cities.yaml` (`backup: {min_size_kb: ..}`) for a city with unusual data. Leave it out unless calibration shows a need.
- [x] Removed the per-env `MIN_BACKUP_SIZE_KB` switch from the Makefile.
- [ ] `watchdog-install` writes only `MIN_BACKUP_SIZE_KB`. The watchdog reads the other variables from its environment, so add them to `/etc/sslv-watchdog.env` only to override a default. Hosts installed earlier already have `MIN_BACKUP_SIZE_KB=1` (staging) or `10` (prod): **re-run `make watchdog-install` on prod** to get 1.

## 5. Calibrate before release

- [ ] Add a `make backup-sizes M6_ENV=...` target (read-only). For each city it prints the last 14 backups (size, date) next to the current LA/RA counts, and the derived bytes/row.
- [ ] Run it for staging and for prod. Set `BYTES_PER_ROW` to about the observed p10, so the rule stays conservative.
- [ ] Check that the numbers would have flagged the 2026-09-21 incident: prod buckets received 2–4 KB staging dumps while prod holds thousands of rows. 2b, 2c and 3 should each fire for it.

## 6. Severity and alert routing  ✅ `dev-1.7.9.17`

- [x] Watchdog warnings are problems prefixed `warning: ` (`WARNING_PREFIX`). They are the size-per-row check (2b) and the shrink check (2c). Everything else stays critical.
- [x] Report: a city with only warnings shows `WRN` instead of `BAD`. The header says `N with problems, M with warnings only`. The exit code is 0 when there are only warnings, so the systemd unit does not fail.
- [x] ntfy: only critical problems drive alert, reminder and resolved. A **new** warning pushes once at `low` priority (`[ENV] SSLV WARNING: ...`), with no reminders and no "resolved". A cleared warning is forgotten, so it pushes again if it returns. Alerts, resolved pushes and the daily heartbeat list current warnings under `Warnings:`.
- [x] Email: warnings-only → `SSLV FLEET WARNING [env]` subject. With `--email-mode problems` that is the daily heartbeat run only; the 15-min timer does not email.
- [x] `backup.py`: SES email only for CRIT; WARN goes to `backup.log`. The alert body now says whether the dump was uploaded (failed verification) or nothing was stored.
- [x] Wording: "near-empty dump" is gone. Every message states its numbers (`2.6 KB for 5000 rows (expected >= 25.4 KB at 5 B/row)`).

## 7. Age alert: find out why before tuning anything

- [x] Answered by the 13:33 logs: the cron runs nightly and writes to `sslv-staging-*`. The 91h came from checking prod buckets from the staging host. The age threshold stays at 26h.
- [ ] Improvement: `check_backup` should also report the age of the newest backup in the **other** env's bucket when the checked env is stale. That turns "91h old" into "91h old in prod, 11h old in staging → wrong M6_ENV?".

## 8. Tests

- [ ] `tests/test_12_fleet_watchdog.py`: cover a small DB with a small dump (no alert), a large DB with a small dump (alert), shrink versus median (alert), fewer than 3 prior backups (shrink skipped), `LA:?` (fallback), metadata row mismatch (CRIT), and the header showing the env and thresholds.
- [ ] `tests/test_10_module_backup_svc.py`: metadata is uploaded, verify uses the new rules, and a 2 KB dump of a 30-row DB passes.
- [ ] `tests/test_30_make_env_guard.py`: update it for the removed per-env `MIN_BACKUP_SIZE_KB` default.
- [ ] Update `docs/staging_alert_remediation_plan.md` P1b with a pointer to this plan.

## Logs needed from the staging/preprod EC2 host

```bash
# 1. Which env does this host run, and which floor does the watchdog use?
sudo cat /etc/sslv-watchdog.env | grep -v -i token
make fleet-status M6_ENV=staging

# 2. Did the cron fire, and where did it upload? (repeat for 1-2 cities)
docker exec ogre-backup-1 tail -n 80 /var/log/cron.log
docker logs --since 96h ogre-backup-1 2>&1 | grep -Ei "upload|verif|error|stale|S3_BUCKET" | tail -n 40
docker exec ogre-backup-1 sh -c 'env | grep -E "^(ENV|CITY|S3_BUCKET|MIN_BACKUP|BACKUP_MAX)="; pgrep -a cron'

# 3. Backup history in both envs (sizes over time)
for env in prod staging; do echo "== $env"; aws s3 ls --recursive s3://sslv-$env-ogre-db-backups/db-backups/ | tail -n 10; done
aws s3 ls --recursive s3://sslv-staging-jurmala-db-backups/db-backups/ | tail -n 10

# 4. Watchdog timer history
make watchdog-status
```
