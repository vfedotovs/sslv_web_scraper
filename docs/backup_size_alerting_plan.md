# Backup size alerting: fewer false positives — implementation plan

Branch: `dev-1.7.9.16` · Source: `make fleet-status` on the preprod host, 2026-09-26 13:22 UTC

## 0. What the 2026-09-26 report actually says

| Signal | Verdict | Why |
|---|---|---|
| `bkp: 2KB` / `5KB` < 10 KB | **False positive** | The DBs hold 24–318 listed + 6–16 removed rows. A gzip'd `pg_dump --clean` of that is 2–5 KB. A fixed 10 KB floor can only work for a large prod DB. |
| `bkp: 91h` > 26h | **Probably real — needs checking before it is tuned** | Every city's newest object is from 2026-09-22 18:33–18:34 UTC, 4 s apart. That looks like one manual `backup-all` run, not the 02:00 cron. The daily cron has not written to **these** buckets since then. |
| Buckets are `sslv-prod-*` | **Possibly the wrong env** | `fleet-status` defaults to `M6_ENV=prod`. The host folder is `prepord-test-branch-*`, and LA:24 looks like a fresh DB, not prod history. If this host is staging, the report checked prod buckets that this host never writes to. No `host_env_warn` line appeared, so `/etc/sslv-watchdog.env` is either missing or says `ENV=prod`. |

**Conclusion:** the size floor needs to change (items 1–6), but the age alert is not a false positive. Confirm which env this host runs (item 7, logs below) before changing anything about age.

## 1. Quick fix: stop the noise now (no code change)

- [ ] On the preprod/staging host, run `make fleet-status M6_ENV=staging`. This picks up `MIN_BACKUP_SIZE_KB=1` from the existing Makefile per-env default.
- [ ] If the watchdog timers are installed, check the floor they use: `sudo cat /etc/sslv-watchdog.env`. If it is wrong, run `make watchdog-install M6_ENV=staging NTFY_TOPIC_URL=...` again.
- [ ] Print the env and the thresholds in the report header, e.g. `SSLV fleet status — env=prod floor=10KB max-age=26h — ...`. Today you cannot tell from the output which buckets were checked (`scripts/fleet_watchdog.py:824`).

## 2. Make the size check depend on the data, not a constant

Replace the single `size < MIN_BACKUP_SIZE_KB` test in `check_backup()` (`scripts/fleet_watchdog.py:348`) with three separate tests, each with its own message:

- [ ] **2a. Hard floor (CRIT):** alert when `size < 1 KB`. A gzip'd `--clean` dump with schema and no rows is about 1 KB, so anything smaller is truncated or failed. Keep `MIN_BACKUP_SIZE_KB` as this floor, default it to 1 for every env, and remove the 10 KB prod default.
- [ ] **2b. Expected size from live row counts (WARN):** the watchdog already reads `LA`/`RA` per city (`fleet_watchdog.py:569-572`). Compute `expected = BASE_BYTES + (LA+RA) × BYTES_PER_ROW`, starting with BASE≈1.5 KB and ≈40 B/row compressed (calibrate in item 5). Alert only when `size < expected × 0.3`. A DB with 30 rows then expects about 2.7 KB and a 2 KB dump passes. A DB with 5,000 rows expects about 200 KB, so a 2 KB dump still alerts.
- [ ] **2c. Shrink versus history (WARN):** list the last N=7 backups (one `list-objects-v2` call, which the function already makes). Alert when the newest is < 50% of their median. This catches "DB got wiped" whatever the absolute size. Skip this test when there are fewer than 3 prior backups.
- [ ] Skip 2b when the row counts are unavailable (`LA:?`) and fall back to 2a+2c. Never alert just because a count is unknown.

## 3. Record what went into the dump (backup side)

- [ ] In `backup.py:backup_postgres()`, run `SELECT count(*)` on `listed_ads` and `removed_ads` before `pg_dump`.
- [ ] Upload with `ExtraArgs={"Metadata": {"listed-ads": ..., "removed-ads": ..., "env": ..., "city": ...}}` (`backup.py:193`).
- [ ] Change `verify_backup_in_s3()` to use the same rules as 2a/2b instead of the fixed floor. Also fail the backup when the row counts are 0 but the live DB was not expected to be empty.
- [ ] Watchdog: when `head-object` metadata is present, compare the row counts in the dump with the live counts. For example, dump rows < 50% of live rows → "backup does not contain the data". This is the most exact test and it does not depend on size at all.

## 4. Configuration

- [ ] New env and CLI settings with defaults in `env.example`:
  `BACKUP_HARD_FLOOR_KB=1`, `BACKUP_BYTES_PER_ROW=40`, `BACKUP_EXPECTED_RATIO=0.3`, `BACKUP_SHRINK_RATIO=0.5`, `BACKUP_HISTORY_N=7`.
- [ ] Optional per-city override in `config/cities.yaml` (`backup: {min_size_kb: ..}`) for a city with unusual data. Leave it out unless calibration shows a need.
- [ ] `watchdog-install` writes the new variables to `/etc/sslv-watchdog.env`. Remove the per-env `MIN_BACKUP_SIZE_KB` switch from `Makefile:47`, because the data-based check makes it redundant.

## 5. Calibrate before release

- [ ] Add a `make backup-sizes M6_ENV=...` target (read-only). For each city it prints the last 14 backups (size, date) next to the current LA/RA counts, and the derived bytes/row.
- [ ] Run it for staging and for prod. Set `BYTES_PER_ROW` to about the observed p10, so the rule stays conservative.
- [ ] Check that the numbers would have flagged the 2026-09-21 incident: prod buckets received 2–4 KB staging dumps while prod holds thousands of rows. 2b, 2c and 3 should each fire for it.

## 6. Severity and alert routing

- [ ] Split the problems into `CRIT` and `WARN`. CRIT: hard floor, missing, stale, row mismatch. WARN: below expected, shrink.
- [ ] ntfy: CRIT uses the current priority and reminders. WARN gets low priority, no 6h reminders, and appears in the daily heartbeat digest.
- [ ] `backup.py` SES alert: send email only for CRIT. Log WARN to `backup.log`.
- [ ] Wording: stop saying "likely a near-empty dump" unless 2a or 3 fired. For 2b/2c, state the numbers, e.g. "2 KB for 31 rows, expected ≥ 0.8 KB".

## 7. Age alert: find out why before tuning anything

- [ ] Collect the logs listed below and find out why the 02:00 cron has written nothing since 2026-09-22. Possible causes: cron not running in the container, backups going to `sslv-staging-*` while prod buckets are checked, the host env guard, or an auth failure.
- [ ] If this host is staging and its cron writes to staging buckets, the fix is item 1 (the env) and the age threshold stays at 26h.
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
