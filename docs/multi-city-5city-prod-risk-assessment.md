# Multi-City (5 Cities) Production Deployment Risk Assessment & Acceptance Plan

**Date:** 2026-07-08  
**Context:** Extending from current 3-city (ogre, sigulda, salaspils) MVP using `deploy-multi-city-ws.sh` + docker-compose with `--project-name` + per-city `.env.$city` to 5 cities in production.  
**Current Setup Review (from attached files + code exploration):**
- `deploy-multi-city-ws.sh`: Hardcoded list of 3 cities. Loops `docker-compose --project-name $instance --env-file .env.$instance up -d`
- `docker-compose.yml`: 
  - Per-city isolation via project name (containers: <city>-db-1, <city>-ws-1, <city>-ts-1; volumes/networks prefixed).
  - `CITY_MAIN_URL` and `EMAIL_CITY_TITLE` passed per city (good).
  - `S3_BUCKET` passed (from .env).
  - **Critical hardcodes:** curl service runs `/run-task/ogre`; ts likely triggers specific city.
  - DB uses project-specific volumes.
- S3/DB buckets (confirmed via `gh search code` + CLAUDE.md + scripts):
  - **DB backups injection/restore:** `S3_BUCKET` from AWS Secrets Manager secret `sslv_creds` key `s3_db_backups`.
    - Buckets (env-specific, city in naming for some): `sslv-prod-db-backups`, `sslv-staging-db-backups`, examples like `sslv-ogre-city-dev-v1-6-db-backups-YYYY-MM`.
    - Scripts: `scripts/get_last_s3_file.sh`, `scripts/load_secrets*.sh`, `src/db/get_last_db_backup.py`, `scripts/backup_pg_container_db.sh` + `upload_backup_to_s3.sh`.
  - **Lambda scraped data (file injection for ws):** Hardcoded `S3_LAMBDA_BUCKET_NAME = "lambda-ogre-scraped-data"` in `src/ws/app/wsmodules/file_downloader.py`.
    - Roadmap mentions `sslv-prod-lambda-data` / `sslv-staging-lambda-data` (per-env).
    - Per-city data likely requires city-specific buckets or prefixes in future.
  - CI/CD and setup pull per-env buckets; multi-city relies on per-city `.env.$city` exporting correct `S3_BUCKET` (and `CITY_MAIN_URL`).
- Current multi-city: Uses separate compose projects for isolation. Works for MVP with 3 cities + limit in scraper.

**Goal of this plan:** Identify most likely problems for scaling to 5 cities in production. Assess effort (Low/Med/High) and impact (Low/Med/High). Provide small, verifiable acceptance criteria for each.

## Problem List, Assessment & Acceptance Plans

### 1. Hardcoded city list in deploy script (only 3 cities defined)
- **Description:** Script and any related lists hardcode exactly 3 cities. Adding 2 more requires code change.
- **Likelihood in prod with 5 cities:** High.
- **Effort to resolve:** Low (1-2 hours: edit array, create 2 new .env files, test).
- **Impact if unresolved:** High (deployment fails or is manual for 5th/6th city; blocks scaling).
- **Acceptance / Verification Plan:**
  - Update script to list 5 cities.
  - Run `bash deploy-multi-city-ws.sh` (or equivalent).
  - Verify: `docker ps --format '{{.Names}}' | grep -E 'city1|city2|city3|city4|city5' ` shows exactly 5 groups of containers (db, ws, ts per city).
  - Check logs: each city deployed successfully without errors.
  - Cleanup with undeploy script.

### 2. Hardcoded city-specific triggers in docker-compose.yml (e.g., curl service runs only "ogre")
- **Description:** `curl` service: `curl http://ws:8000/run-task/ogre` . ts scheduler may hardcode city. Per-city compose doesn't override the trigger for non-ogre cities.
- **Likelihood:** Very High.
- **Effort to resolve:** Medium (1-3 days: make trigger configurable via env var in compose, update ts code if needed, update deploy script to pass city).
- **Impact if unresolved:** Critical (only one city gets automatic triggering/scheduling; others require manual curl or never run).
- **Acceptance / Verification Plan:**
  - For each of 5 cities: after deploy, exec into ts or use docker to trigger, verify correct city data is processed (check logs or DB for city-specific data like CITY_MAIN_URL).
  - Confirm no cross-city data leakage.
  - Test full pipeline per city independently.

### 3. Hardcoded S3 Lambda bucket name in file_downloader.py ("lambda-ogre-scraped-data")
- **Description:** Ignores per-city S3_BUCKET for lambda data download. All cities would try to pull from ogre bucket.
- **Likelihood:** Very High.
- **Effort to resolve:** Medium (2-4 days: make bucket configurable via env (like CITY_MAIN_URL), update .env per city + secrets if needed, handle prefixes if using shared buckets).
- **Impact if unresolved:** Critical (only ogre gets correct lambda scraped data; other cities fall back to slow local scrape or get wrong/missing data → incorrect reports).
- **Acceptance / Verification Plan:**
  - Set per-city S3_LAMBDA_BUCKET_NAME in .env.city (or use S3_BUCKET).
  - Deploy 2+ cities with different lambda data in their buckets.
  - After run: verify each city's `local_lambda_raw_scraped_data/` contains city-appropriate data (check file names/content or DB entries for city-specific URLs).
  - Confirm file_downloader logs show correct bucket per city.

### 4. S3 DB backup bucket strategy and injection not scaled for multi-city
- **Description:** `S3_BUCKET` from shared secret `s3_db_backups`. Buckets are env-specific (sslv-prod-db-backups etc.) with occasional city in name. No per-city isolation in current multi-city .env or scripts. Backups (upload_backup_to_s3.sh) and injection (get_last_db_backup.py) may collide or pull wrong city's backup.
- **Likelihood:** High.
- **Effort to resolve:** High (3-7 days: decide architecture (per-city buckets vs shared+prefix), create/update buckets/secrets, update all backup/inject scripts + .env.city + load_secrets, update CI if needed).
- **Impact if unresolved:** Very High (data corruption, restoring wrong city's DB to another, backup overwrites, failed restores on prod).
- **Acceptance / Verification Plan:**
  - For each city: set distinct S3_BUCKET in .env.city (e.g., sslv-cityX-db-backups).
  - Manually trigger backup for one city, verify file lands in correct bucket with city prefix.
  - Simulate restore: use get_last for each city, confirm correct backup downloaded for that city's DB container.
  - Check logs in dbworker/file_downloader for correct bucket per city.

**Daily DB Backup & Manual Restore Flow for Multi-City (M6)**
- Backup scheduled inside dedicated `{city}-backup-1` container (cron, not host).
- Manual restore: `./scripts/restore_db_city.sh --city <city> [--date YYYY_MM_DD] [--prepare-init]`
- For redeploy new code without data loss: restore first if needed, then deploy.
- Troubleshooting: failed pg_dump (check password/container), wrong city (verify .env and bucket), permission (AWS creds/IAM). See M6_phase_1_backup_restore_service_plan.md for full details.

### 5. Resource contention on single host (5 DB + 5 WS + 5 TS containers)
- **Description:** All on one machine. 5 Postgres + heavy scraping + scheduling compete for CPU, RAM, disk I/O.
- **Likelihood:** High (especially during simultaneous scrapes).
- **Effort to resolve:** Medium (2-5 days: add deploy resource limits in compose, stagger schedules, monitor with docker stats/prom, split to multiple hosts if needed).
- **Impact if unresolved:** High (OOM kills, slow scrapes, DB performance issues, failed pipelines).
- **Acceptance / Verification Plan:**
  - Deploy all 5 cities.
  - Monitor during full run: `docker stats`, `free -h`, disk usage.
  - Verify all 5 pipelines complete successfully without OOM or high latency.
  - Set and test resource limits (memory/cpu) in compose.

### 6. Port conflicts (especially ts healthcheck 8080)
- **Description:** ts health port noted as conflicting in multi-city. If any port exposed, collisions.
- **Likelihood:** Medium (if ports left exposed).
- **Effort to resolve:** Low (hours: ensure no host ports for ts, document).
- **Impact if unresolved:** Medium (deploy fails or one city breaks).
- **Acceptance / Verification Plan:**
  - Deploy 5 cities.
  - `docker ps` shows no conflicting host ports.
  - Health checks pass internally for all cities.

### 7. Lack of error handling / partial failures in deploy script
- **Description:** Simple for-loop; no `set -e`, no per-city success check, continues on failure, always prints "successfully".
- **Likelihood:** High.
- **Effort to resolve:** Low (1 day: add error checking, per-city status, fail fast or report summary).
- **Impact if unresolved:** Medium (one city fails silently; prod has inconsistent state).
- **Acceptance / Verification Plan:**
  - Simulate failure for one city (bad .env).
  - Run script: verify it reports failure for that city, succeeds for others, exits non-zero if any failed.

### 8. Scheduler / trigger not per-city aware
- **Description:** ts + curl in compose hardcode "ogre". Per-city deploys won't auto-trigger correctly for other cities.
- **Likelihood:** Very High.
- **Effort to resolve:** Medium (make trigger city-aware via env in ts and compose curl).
- **Impact if unresolved:** Critical (only "ogre" (or default) city runs on schedule).
- **Acceptance / Verification Plan:**
  - Deploy 5 cities with distinct CITY_MAIN_URL.
  - Trigger per city (or via ts).
  - Verify each city's data in DB matches its CITY_MAIN_URL (e.g., different streets or titles).

### 9. Logging and observability not city-isolated
- **Description:** Logs (web_scraper.log, dbworker.log, s3_...) may mix or collide when multiple compose projects run on same host.
- **Likelihood:** Medium-High.
- **Effort to resolve:** Low-Medium (configure per-container logging drivers, prefixes, or volumes per project).
- **Impact if unresolved:** Medium (hard to debug one city's issues).
- **Acceptance / Verification Plan:**
  - Deploy 5 cities.
  - Trigger runs.
  - Verify logs are separable (e.g., by container name prefix or dedicated log files per city).

### 10. Backup/restore scripts and CI not multi-city aware
- **Description:** backup_pg_container_db.sh, upload, get_last target specific names/containers. CI workflows target single env/bucket.
- **Likelihood:** High.
- **Effort to resolve:** Medium (update scripts to accept city param, use project-name containers, per-city buckets in CI).
- **Impact if unresolved:** High (backups target wrong DB, restores corrupt data, CI deploys wrong city data).
- **Acceptance / Verification Plan:**
  - For each of 5 cities: run backup, verify file in correct S3 bucket with city identifier.
  - Restore to a test city DB, verify data matches only that city.

## Overall Recommendations
- **Priority order for fixes:** 2, 3, 4, 8, 5, 1, 7, 6, 9, 10 (based on impact).
- Total effort estimate for all: Medium-High (2-4 weeks for one dev, assuming some parallel).
- **MVP for 5 cities:** Solve 1-4 + 8 first.
- Use the acceptance plans above as checklist before declaring "production ready for 5 cities".
- Consider centralizing city config (e.g. cities.json or env list) instead of hardcodes.
- Test with exactly 5 cities (add 2 dummy if needed).

**Next:** Once this plan is reviewed, we can implement fixes one-by-one with the acceptance criteria as tests.
