# Staging Alert Remediation Plan

**Branch:** `dev-1.7.9.13` · **Date:** 2026-09-21 · **Source:** `make fleet-status M6_ENV=staging` after deploying `dev-1.7.9.12`

## What the alert is saying

10 problems across 6 cities, but only **two root causes** — and the watchdog itself is working correctly: every line is a real problem it was built to catch.

| # | Problem | Cities | Root cause | Severity |
|---|---|---|---|---|
| 1 | `could not list s3://sslv-staging-<city>-db-backups (NoSuchBucket)` | **all 6** | The staging backup buckets were never created, so **staging has no backups at all** | **P0 — data loss risk** |
| 2 | `last run FAILED at stage df_cleaner: 0` + `last successful run is 36h old` | adazu_nov, ogre | `df_cleaner` crashes when a run finds **zero new ads** | **P0 — pipeline down for 2 cities** |

Everything else in the report is healthy: `ctr:4/4` for all 6 cities (24 containers), the other 4 cities scraped 12h ago, and the host line was clean.

### Cause 1 — missing staging backup buckets

`NoSuchBucket` means the bucket does not exist, rather than existing in another region (that fails with `PermanentRedirect`, which the watchdog reports separately since `fef9655`). The nightly backup job in each `<city>-backup-1` container has therefore been failing every night at 02:00 UTC, and `make test-restore` / `verify-backup` cannot pass.

**Watch the region:** the backup service and the watchdog default to **eu-west-1** (`backup.py:55`, `fleet_watchdog.py --aws-region`), but the Makefile's `AWS_REGION` defaults to **us-east-1**. Creating the buckets with the default would swap `NoSuchBucket` for `PermanentRedirect`, so pass `AWS_REGION=eu-west-1` (and see the P1 item on aligning the defaults).

### Cause 2 — `df_cleaner` crash on a night with no new ads

`df_cleaner.py:87` does:

```python
df = df_name["Size_sq_m"].str.split(" ", n=1, expand=True)
df_name["Size_sqm"] = df[0]
```

On an **empty** data frame, `str.split(expand=True)` returns a frame with **no columns**, so `df[0]` raises `KeyError: 0` — and `str(KeyError(0))` is exactly `"0"`, the error text in the alert. Reproduced locally with pandas:

```
empty frame -> split columns: []
df[0] raises KeyError, str(e) = '0'
```

The same pattern repeats at lines 106, 111 and 124 (`new[0]`, `new[1]`, `no_euro_symb[0]`), so a price string without `(` would fail the same way with `"1"`.

**Why only two cities:** the four healthy cities found 1–2 new ads; adazu_nov and ogre found none that night. **A night with no new ads is normal** — `alert_mailer` even tracks a zero-new streak as an expected condition — so this is a bug in the pipeline, not bad data.

---

## Action plan

### P0-0 — Incident 2026-09-21: the staging backup wrote into the PROD buckets

`make backup-all M6_ENV=staging` uploaded the six **staging** databases to
`s3://sslv-prod-<city>-db-backups/` and then pruned those buckets to the newest
5 objects — the log shows `(env: prod)` and 13 `Pruned old backup key` lines for
jurmala alone (2026-07-26 … 2026-08-07).

**Cause:** `backup_db_city.sh` sourced `.env.<city>` with `set -a` for DB
credentials. Those files still carry the single-city M5 values `ENV=prod` and
`S3_BUCKET=sslv-prod-<city>-db-backups`, which overwrote the script's own `ENV`
and redirected every upload. `verify_backup.sh` does not source them, which is
why it kept reporting the (empty or missing) staging buckets — the mismatch that
exposed this. `restore_db_city.sh` had the same flaw, where it would have pulled
a **prod** dump into a live staging DB.

**Code fix (done on `dev-1.7.9.13`):** the bucket is always derived from `--env`
plus the city; `S3_BUCKET` from the env file is ignored with a warning; `--env`
survives the sourcing; an explicit `--bucket` must still match the env, and a
mismatch is refused. Covered by `tests/test_28_backup_restore_env_isolation.py`
(6 of its 7 tests fail against the old scripts).

**Still to do on the host:**

- [ ] Stop the nightly job on the staging host before 02:00 UTC — its containers
      take `S3_BUCKET` from the same `.env.<city>` files (`docker-compose.yml:126`),
      so they have been writing staging data into the prod buckets every night:
      `docker stop $(docker ps -q --filter name='-backup-1')`
- [ ] Fix the staging `.env.<city>` files in `sslv-staging-m6-cicd-files`: set
      `S3_BUCKET=sslv-staging-<city>-db-backups` (or drop the line so the
      convention applies) and `ENV=staging`, then redeploy. The container fix is
      config; the script fix above does not reach the nightly job.
- [ ] Assess the prod buckets. Staging dumps are tiny (2.6–4.2 KB) next to real
      prod dumps:
      `aws s3 ls s3://sslv-prod-<city>-db-backups/db-backups/ --recursive --human-readable | tail`
- [ ] Recover the pruned prod objects. `create-s3-bucket` enables versioning, so
      they should sit behind delete markers:
      `aws s3api list-object-versions --bucket sslv-prod-<city>-db-backups --prefix db-backups/ --query 'DeleteMarkers[?IsLatest].[Key,VersionId]' --output text`
      then delete the marker for each object to restore it.
- [ ] Once prod is whole again, delete the staging dumps uploaded into the prod
      buckets on 2026-09-21 ~17:25.
- [ ] Check how far back this goes: if the nightly job has been doing this since
      the staging fleet was deployed, prod retention (newest 5) may have been
      dropping genuine backups for weeks. Compare object sizes per day.
- [ ] Confirm the prod host's own backups are unaffected (it has its own
      `.env.<city>` files naming the same buckets, which is correct there).

### P0-1 — Create the six staging backup buckets (about 10 minutes)

- [x] Confirm the region the prod buckets use, and match it — **confirmed 2026-09-21: `eu-west-1`**, matching `backup.py` and the watchdog:
  ```bash
  aws s3api get-bucket-location --bucket sslv-prod-ogre-db-backups   # -> "eu-west-1"
  ```
- [ ] Create all six, using the **city slug** (`marupes-pag`, not `marupes_pag`):
  ```bash
  for c in salaspils sigulda marupes-pag adazu-nov ogre jurmala; do
    make create-m6-bucket M6_ENV=staging M6_CITY=$c M6_PURPOSE=db-backups AWS_REGION=eu-west-1
  done
  ```
  Each bucket gets public access blocked, versioning and a 90-day lifecycle rule.
- [ ] Verify: `make list-existing-m6-buckets` shows 6 staging buckets, and `make check-m6-bucket BUCKET_NAME=sslv-staging-ogre-db-backups` shows the region and lifecycle.
- [ ] Take the first backups now rather than waiting for 02:00 UTC:
  ```bash
  make backup-all M6_ENV=staging
  make verify-backup M6_ENV=staging      # expect 6 x OK
  ```
- [ ] Prove one restores, without touching the live DB:
  ```bash
  make test-restore CITY=ogre M6_ENV=staging
  ```
- [ ] Check the backup containers are healthy again, now that the target exists:
  ```bash
  docker logs ogre-backup-1 --tail 50
  ```
- [ ] Confirm the watchdog clears: `make fleet-status M6_ENV=staging` should report no `bkp:` problems, and ntfy should send a "RESOLVED" push.

### P0-2 — Fix `df_cleaner` on empty input (about half a day)

- [ ] Get the real traceback to confirm the line: `make collect-logs CITY=ogre` and look for `df_cleaner` in the `ws` log, or `docker logs ogre-ws-1 | grep -A20 df_cleaner`.
- [ ] **Fix:** treat an empty frame as a valid, empty result instead of an error. Either return early in `df_cleaner_main` when the input has no rows, or make each split tolerant (e.g. `split.get(0, pd.Series(dtype=str))` / `reindex(columns=[0, 1])`) at lines 87, 106, 111 and 124. The same guard also covers a price without `(`, which would fail with `"1"`.
- [ ] Decide what an empty run should record: a `success` with `new_ads = 0`, not a failure. `alert_mailer` already alerts on a zero-new **streak**, which is the right place for that signal.
- [ ] **Regression tests:** `df_cleaner` with (a) an empty frame, (b) one row whose `Price` has no `(`, (c) a normal row. These are pure-pandas tests and need no containers.
- [ ] Re-run the two failing cities and confirm they go green:
  ```bash
  docker exec ogre-ws-1 python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/run-task/ogre', timeout=600)"
  make fleet-status M6_ENV=staging
  ```
- [ ] **Check the M8 branch first:** `dev-1.8.5` rewrites `df_cleaner` without pandas. Whichever lands first, the other needs the same guard — the bug is in the logic, not in pandas.

### P1 — Close the gaps this incident exposed

- [ ] **Stop shipping `S3_BUCKET` in `.env.<city>` at all.** It is a legacy single-city variable; the bucket is derivable from env + city everywhere. While it exists, every consumer has to defend against it.
- [ ] **Align the region defaults.** `AWS_REGION ?= us-east-1` in the Makefile contradicts `eu-west-1` everywhere else. Change the default to `eu-west-1` so a bucket can't be created in the wrong region again.
- [ ] **Add a deploy pre-flight check for the backup buckets.** `_deploy-precheck` verifies the CICD bucket but not the per-city backup buckets, which is why a fleet deployed with nowhere to back up to. A `head-bucket` per city, as a warning, would have caught this on day one.
- [ ] **Alert on a failing backup job, not only on a stale bucket.** Today a backup container that fails every night is invisible until the newest object is 26h old. `backup.py` writes no success marker and the `backup` service has no healthcheck, so "running" is its only health signal (M6 item A1): have the job write a marker on success and add a healthcheck that fails when the marker is older than `BACKUP_MAX_AGE_HOURS`.
- [ ] **Decide whether staging needs `scraped-data` buckets** (`make list-m6-buckets` lists them as expected); nothing alerts on them today.

### P2 — Before production deployment

Treat these as the gates for promoting this branch series:

- [ ] `make fleet-status M6_ENV=staging` is clean for **7 consecutive days**, including the daily 06:35 heartbeat.
- [ ] `make watchdog-drill M6_ENV=staging` passes all 8 drills, and the pushes actually arrive on your phone (the P3 item still open in `docs/critical_monitoring_ntfy_plan.md`).
- [ ] A restore rehearsal passes for **every** city, not just one: `make test-restore M6_ENV=staging` (no `CITY=`).
- [ ] The prod watchdog uses its **own ntfy topic**, not the guessable staging one — `make watchdog-install M6_ENV=prod NTFY_TOPIC_URL=...` (the Makefile refuses the staging topic for prod).
- [ ] Prod's six `db-backups` buckets are confirmed to exist, in the same region, with lifecycle rules — the check that was missing on staging.
- [ ] Memory headroom on the host is addressed: swap added, or `TASK_TIME`/backup times staggered (see the earlier memory review).
- [ ] CI runs on this branch line: `CI.yml` only triggers on `dev-1.4*.*`, so none of the `dev-1.7.9.x` commits have been tested by GitHub Actions.

---

## Summary

| Question | Answer |
|---|---|
| Is the monitoring wrong? | No. Every alert is a real problem, and the two `df_cleaner` cities would have gone unnoticed for a day without it. |
| Is staging safe to promote today? | No. No backups exist, and the pipeline fails whenever a city finds no new ads. |
| How far is it? | Two P0 fixes, both small: creating the buckets is minutes; the `df_cleaner` guard is a few lines plus tests. |
