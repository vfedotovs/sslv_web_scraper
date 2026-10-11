# Staging Review — `dev-1.7.9.23`

**Reviewed:** 2026-10-11 · **Host:** `staging-eu-north-1` (`i-01182e96a6d2d0e7f`) · **Deploy dir:** `/home/ec2-user/test-staging-1-7-9-23`
**Evidence:** log bundle `sslv-logs-2026-10-11T15-02-42Z.tar.gz` (collect_logs_v3 3.0.0, 72 h window, redaction self-test PASS), DB dumps in the bundle, `journalctl -u sslv-watchdog`, git history.

---

## 1. Verdict

| Question | Answer |
|---|---|
| Does `dev-1.7.9.23` **pass staging acceptance** as a build? | **Yes.** It ran 9 nightly cycles × 6 cities without a failed run. |
| Can this code be **released to production as-is**? | **No.** Nothing is broken at runtime. The blockers are release readiness: the branch has 19 merge conflicts with `main`, an EOL Python runtime and no version traceability (§3). |

The build deployed and tested on staging is exactly the branch HEAD. The host checkout is at `7a91f2d` with a clean working tree, and the deploy ran at 2026-10-02 10:24 UTC, after that commit (10:10 UTC).

---

## 2. What is working (evidence)

| Area | Result |
|---|---|
| Containers | 24/24 running for 9 days; all `ws`/`ts`/`db` report `healthy`; `restart_count: 0` |
| Nightly scrape | All 6 cities have `scrape_runs.status = success` every night from 2026-09-22 to 2026-10-11. Nothing failed after the deploy |
| TS verification | `verify_task` reports "Run verification OK" daily for every city |
| Email reports | SES `Email sent!` 9/9 days × 6 cities (2026-10-03 → 2026-10-11) |
| `7a91f2d` fixes | 1M+ prices are stored and emailed correctly (jurmala: 6 rows ≥ €1M, e.g. €1,200,000). There are 27 jurmala and 5 marupes_pag ads with 5+ rooms. No price below €5,000, which would mean a truncated price |
| Empty-scrape fix (`048565c`) | The `df_cleaner` failures on 2026-09-21 (adazu_nov, ogre) have not recurred. Empty days now log "has no rows: producing empty outputs" |
| Backups | Nightly 02:00 dump → S3 → verified with row counts; 14:00 staleness check "fresh" for all 6 cities |
| Watchdog | `sslv-watchdog.timer` runs every 15 min with 883 checks since the deploy. Its one alert (§4, item 11) resolved itself within 14 min |
| DB | No errors or warnings in Postgres stdout. No HTTP 4xx/5xx in `ws` stdout |
| Host | Disk 61 % (6.4 G free), Docker 25.0.16, Compose v5.1.3 |

---

## 3. Release blockers (P0)

These must be closed before production. Where an item already exists in
[`RELEASE_2.0.0_action_plan.md`](RELEASE_2.0.0_action_plan.md), its ID is given.

- [ ] **B-1 — Branch cannot merge into `main` cleanly; the code that staging tested is not the code that would ship.** (RELEASE plan I-1, M-3)
  - `dev-1.7.9.23` is 105 commits ahead of `main` and 76 behind. `git merge-tree` shows **19 conflicting files**, including the core pipeline: `src/ws/app/main.py`, `wsmodules/{aws_mailer,db_worker,df_cleaner,data_format_changer}.py`, `src/ts/ts.py`, `docker-compose.yml`, `Makefile`, `requirements.txt`, `src/ts/Dockerfile`, plus 7 stale `CICD-*.yml` workflows that `main` deleted.
  - `main` contains fixes this branch lacks: the OOM/DataFrame release, the fd-leak fix, the `validate_list_lengths` ValueError, email-report corrections, and the `eu-west-1` region pinning.
  - **Action:** create `release-2.0.0` from this branch, merge `main` into it, resolve the conflicts so both sides' intent is kept, and tick off the I-1 must-preserve checklist.
  - **Then redeploy the merged result to staging.** This review's acceptance applies to `7a91f2d`, not to the merge.

- [ ] **B-2 — EOL runtime in `ws` and `ts`.** (RELEASE plan D-4, M-4)
  - The branch builds on `python:3.8-slim-buster`, and the container reports `PYTHON_VERSION=3.8.17`. Python 3.8 and Debian buster are both end of life. `main` is already on `python:3.11-slim-bookworm`.
  - **Action:** take 3.11/bookworm during the merge. Rebuild and run the test suite on 3.11 before redeploying to staging.

- [ ] **B-3 — Backup image runs Python 3.9, which boto3 no longer supports.**
  - The backup logs print `PythonDeprecationWarning: Boto3 will no longer support Python 3.9 starting April 29, 2026` 150 times. That date has passed, so the backup service, the one that protects production data, gets no SDK security fixes.
  - **Action:** move the backup image to Python 3.11 too, then rerun `make e2e-backup-restore CITY=ogre M6_ENV=staging`.

- [ ] **B-4 — No release traceability.** (RELEASE plan R-2)
  - The running containers carry `RELEASE_VERSION=v1.6.0`, from a `.env.prod` dated 2026-07-10, so every email subject reads `web_scraper_v1.6.0_…`. Images are untagged (`<none>`) and carry no git SHA label. Today the only proof of what runs on a host is SSHing in and running `git log`.
  - **Action:** bring in `main`'s dynamic `RELEASE_VERSION`/`APP_ENV` injection (`16ecc33`, `49916ca`, `630ff13`). Also add an `org.opencontainers.image.revision=<sha>` label to each image so `collect_logs` and `config.txt` show the commit.

- [ ] **B-5 — The post-deploy verification trigger is a silent no-op.**
  - `deploy-multi-city-ws.sh:289` runs `compose run … curlimages/curl …`. `compose run` expects a **service** name; the service is called `curl`. The command errors out, and the error is hidden by `> /dev/null 2>&1 || true`.
  - Proof: the deploy log shows the "Triggering immediate /run-task" line and the next city's start in the same second, although the command has `sleep 20`. `scrape_runs` has no run at 2026-10-02 ~10:2x for any city. The first run after the deploy was the scheduled 00:40 run the next day.
  - Risk: in production a broken deploy would go unnoticed for up to 14 h, while the deploy log claims verification happened.
  - **Action:** call `curlimages/curl` with `docker run --rm --network <city>_default …`, or use `run --rm curl` with the `debug` profile. Then poll `/status` until today's run is `success` and fail the deploy if it isn't (RELEASE plan V-3).
  - **Fix:** branch `bugfix/deploy-post-deploy-trigger`. The trigger now runs inside the `ws` container through `scripts/lib/post_deploy.sh`, and the deploy fails the city if its run fails or times out. Still open: a deploy after a successful nightly run is skipped, because `/run-task` runs once per day, so the new build is not exercised until the next night.

- [ ] **B-6 — Production data migration steps must be written into the cutover runbook.** (RELEASE plan I-4, I-5, R-4)
  - Before the first 2.0.0 run in production, run `make repair-prices` with a dry run, review the output, then `APPLY=1`. Without it, 1M+ prices stored before `dev-1.7.9.23` stay truncated to 1/1000. A fresh backup must be taken first.
  - Also confirm a production restore drill passes and that the `v1.5.12` rollback procedure accounts for the new `scrape_runs` table.

---

## 4. Should fix before release (P1)

- [ ] **7. ERROR noise hides real errors.** All of today's "Recent errors" in `SUMMARY.txt` are false alarms:
  - `aws_mailer.remove_tmp_files:97 No such file or directory` appears 27–36 times per city. It tries to delete files that no longer exist (`Mailer_report.txt`, `1_rooms_tmp.txt`, `mrv2.txt`, `<city>-raw-data-report.txt`). Remove these names from the cleanup list, or log a missing file as `DEBUG`.
  - `analytics.split_dataframe_by_column:234 Loaded DataFrame is empty` is an `ERROR` on days with no new ads, which is normal. Lower it to `INFO`.
  - Done when a clean nightly cycle produces **zero** `ERROR` lines, so the watchdog and `SUMMARY.txt` show only real problems.
- [ ] **8. Long-lived AWS keys in the `ws` container env.** `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` are passed to the containers (redacted in the bundle), while the host uses its IAM role for S3. Use the instance role for SES/S3 from inside the containers too, or keep the keys in Secrets Manager as `main` does (pinned to `eu-west-1`). Then rotate the current keys.
- [ ] **9. Rerun the staging soak after the merge.** (RELEASE plan V-6) Redeploy the merged `release-2.0.0` build and require **3 consecutive clean nightly cycles**: 6 scrapes, 6 emails, 6 verified backups, no watchdog alerts. Run `make watchdog-drill M6_ENV=staging` once to show alerts still fire.
- [ ] **10. Memory check on 3.11.** (RELEASE plan V-7) The base image and pandas memory profile change with the merge. Compare against `docs/M6_memory_usage_assesment.md`; the containers have no memory limits yet.

---

## 5. Nice to have (P2)

- [ ] **11. Transient watchdog S3 failure.** On 2026-10-11 at 12:32 UTC the watchdog could not list `s3://sslv-staging-sigulda-db-backups` (`aws s3api list-objects-v2` failed). It sent an ntfy ALERT, then RESOLVED at 12:46. The cause is not in the log because the command output is truncated. Log the full stderr, and retry once before alerting.
- [ ] **12. First import on large cities.** Jurmala's first runs in September were capped by the old URL limit; it took 5 nights for `listed_table_rows` to reach `urls_discovered`. `SCRAPE_URL_LIMIT` is now 500 (`45c9111`). Before the production cutover, confirm no production city lists more than 500 ads, or the first-night report will be partial.
- [ ] **13. Host housekeeping.** There are 12 unused `<none>` `ws` images (they share layers, so little real space), 10 orphaned `2026050x/2026070x-deploy_*` volumes (~240 MB) and an unused `agentic-dev:grok-latest` image (571 MB). Prune them after the release redeploy. Most running containers also point at untagged images because each city's build re-tags `:latest`, which ties into B-4.
- [ ] **14. Staging env file naming.** Staging deploys use a file called `.env.prod`, downloaded from the staging bucket. It works, but it is the same name that caused confusion in the 2026-09-21 bucket incident. Renaming it to `.env.<M6_ENV>` would make the host's environment obvious.

---

## 6. Suggested sequence

1. **B-1 + B-2 + B-3 + B-4**: build `release-2.0.0` by merging `main` into this branch on Python 3.11, with versioning and image labels. Get CI green.
2. **B-5 + item 7**: fix the deploy trigger and the log noise on the release branch.
3. Redeploy to staging; run **item 9** (3-night soak, watchdog drill, backup/restore e2e) and **item 10**.
4. Write the production runbook with **B-6**: backup, `repair-prices`, per-city cutover, rollback.
5. PR `release-2.0.0` → `main`, tag `v2.0.0`, release to production one city first (RELEASE plan R-1 … R-5).
