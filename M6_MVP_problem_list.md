# M6_MVP_problem_list.md
## Multi-City (5 Cities) Production Deployment Risk Assessment & Acceptance Plan

**Date:** 2026-07-08  
**Context:** Extending from current 3-city (ogre, sigulda, salaspils) MVP using `deploy-multi-city-ws.sh` + docker-compose with `--project-name` + per-city `.env.$city` to 5 cities in production.  

### Current Setup Review (from attached files + code exploration)

**deploy-multi-city-ws.sh:**
```bash
#!/bin/bash
# Deploy instances
instances=("ogre" "sigulda" "salaspils")

for instance in "${instances[@]}"; do
  echo "Deploying $instance city web scraper instance... "
  docker-compose --project-name $instance --env-file .env.$instance up -d
done

echo "All cilty web scraper container instances deployed successfully..."
```

**docker-compose.yml key points:**
- Services: `db`, `ws`, `ts`, `curl`
- Uses `CITY_MAIN_URL` and `EMAIL_CITY_TITLE` per city (good for multi-city)
- `S3_BUCKET` passed via env
- Hardcoded: `curl` service always does `curl http://ws:8000/run-task/ogre`
- DB volume: `db_data` (becomes `<project>_db_data` with --project-name)
- Network: `postgresql` (project-prefixed)
- No resource limits
- Ports mostly commented out (good for multi-city to avoid conflicts)

**S3 Buckets for DB injection and backup (confirmed via `gh search code` + CLAUDE.md + scripts):**

- **DB backups** (pg_dump files for restore/injection):
  - Loaded via `S3_BUCKET` from AWS Secrets Manager secret `sslv_creds` → key `s3_db_backups`
  - **Decision**: One bucket per city (e.g. `sslv-prod-ogre-scraped-data`, `sslv-prod-sigulda-scraped-data`, etc.).
  - Scripts: `scripts/get_last_s3_file.sh`, `scripts/load_secrets*.sh`, `src/db/get_last_db_backup.py`, `scripts/backup_pg_container_db.sh`, `scripts/upload_backup_to_s3.sh` will be updated to use per-city buckets.

- **Lambda scraped data** (file injection for ws):
  - Currently **hardcoded** in `src/ws/app/wsmodules/file_downloader.py`: `S3_LAMBDA_BUCKET_NAME = "lambda-ogre-scraped-data"`
  - Roadmap mentions `sslv-prod-lambda-data` / `sslv-staging-lambda-data` (per-env)
  - In multi-city this is a major gap — only ogre data will be downloaded unless fixed per-city.
  - **Decision**: When using per-city buckets, each city will have its own dedicated bucket for scraped data (e.g. `sslv-prod-{city}-scraped-data`). Lambda (when implemented later) will use the city-specific bucket.

- In multi-city: `.env.$city` will export its own `S3_BUCKET` (dedicated bucket per city).
- CI/CD and setup will need to support per-city buckets.

**Current multi-city approach:** Separate Docker Compose projects per city for isolation. Works for MVP (3 cities) + URL limit in scraper.

---

## Problem List, Effort, Impact & Acceptance Plans

### 1. Hardcoded city list in deploy script (only 3 cities)
- **Description:** Script hardcodes exactly 3 cities. Cannot deploy 5 without code change.
- **Likelihood in 5-city prod:** High.
- **Effort to resolve:** Low (1-2 hours: extend list + create 2 new `.env.*` files + test).
- **Impact if unresolved:** High (deployment blocks for additional cities; scaling fails).
- **Acceptance / Verification Plan:**
  - Update script to 5 cities.
  - Run deploy script.
  - Verify: `docker ps --format '{{.Names}}' | grep -E 'ogre|sigulda|salaspils|city4|city5'` shows 5 complete sets of containers.
  - Each city logs "Deploying X city..." and final success message.
  - Run undeploy and confirm clean removal.

### 2. Hardcoded city in docker-compose.yml (curl service + ts trigger)
- **Description:** `curl` service hardcodes `ogre`: `curl http://ws:8000/run-task/ogre`. ts scheduler also appears ogre-centric.
- **Likelihood:** Very High.
- **Effort to resolve:** Medium (1-3 days: make trigger city-aware via env var, update ts if needed, adjust deploy script).
- **Impact if unresolved:** Critical (only one city gets automatic triggering; others never run or require manual intervention).
- **Acceptance / Verification Plan:**
  - Deploy 5 cities with distinct `CITY_MAIN_URL` in each `.env.*`.
  - Trigger pipeline for each city (or via ts).
  - Verify each city's processed data in its DB matches its `CITY_MAIN_URL` (different streets/titles).
  - Confirm no cross-city data leakage.

### 3. Hardcoded S3 Lambda bucket in file_downloader.py
- **Description:** `S3_LAMBDA_BUCKET_NAME = "lambda-ogre-scraped-data"` — ignores per-city configuration.
- **Likelihood:** Very High.
- **Effort to resolve:** Medium (2-4 days: make configurable via env like `CITY_MAIN_URL`, update `.env.*` files, ensure per-city buckets or prefixes exist).
- **Impact if unresolved:** Critical (non-ogre cities get no lambda data or wrong data → fall back to slow local scrape or broken reports).
- **Acceptance / Verification Plan:**
  - Configure different lambda buckets (or prefixes) per city.
  - Deploy/run 2+ cities.
  - Verify each city's `local_lambda_raw_scraped_data/` contains city-appropriate data.
  - Check logs show correct bucket per city.
  - Confirm downstream DF/DB has correct per-city listings.

### 4. S3 DB backup bucket strategy not ready for multi-city
- **Description:** Shared `s3_db_backups` secret + env-specific buckets. No per-city isolation. Backup files may collide or restores pull wrong city's data.
- **Likelihood:** High.
- **Effort to resolve:** High (3-7 days: decide per-city buckets vs shared+prefixes, create buckets, update secrets, scripts, `.env.*` files, CI).
- **Impact if unresolved:** Very High (data corruption, wrong DB restore, backup overwrites, failed production restores).
- **Acceptance / Verification Plan:**
  - Assign distinct backup buckets per city in `.env.*`.
  - Trigger backup for each city.
  - Verify backup files land in correct bucket with city identifier.
  - For each city: fetch its backup and restore to a test DB; confirm data matches only that city.
  - Check `get_last_db_backup` and upload scripts log the correct bucket.

### 5. Resource contention on single host (5 DB + 5 WS + 5 TS)
- **Description:** 5 full stacks compete for CPU, RAM, disk I/O, especially during simultaneous scraping.
- **Likelihood:** High.
- **Effort to resolve:** Medium (2-5 days: add resource limits in compose, stagger schedules via ts, monitor, consider multi-host if needed).
- **Impact if unresolved:** High (OOM kills, slow or failed scrapes, DB performance issues, pipeline timeouts).
- **Acceptance / Verification Plan:**
  - Deploy all 5 cities on target host.
  - Trigger full pipeline for all cities.
  - Monitor: `docker stats`, `free -h`, disk I/O, container logs for OOM or high latency.
  - All 5 pipelines must complete successfully within expected time.
  - Document resource usage per city.

### 6. Port conflicts (ts healthcheck port 8080)
- **Description:** ts port conflicts noted in CLAUDE.md for multi-city. Any exposed ports will collide.
- **Likelihood:** Medium (if ports are exposed in prod).
- **Effort to resolve:** Low (hours: keep ports internal only, document).
- **Impact if unresolved:** Medium (deploy fails or containers fail to start).
- **Acceptance / Verification Plan:**
  - Deploy 5 cities.
  - `docker ps` shows no host port conflicts.
  - Internal health checks pass for all `ts` containers.

### 7. No error handling or partial failure handling in deploy script
- **Description:** Simple loop with no `set -e`, no per-city success tracking, always prints success message.
- **Likelihood:** High.
- **Effort to resolve:** Low (1 day: add error checking, per-city status reporting, proper exit code).
- **Impact if unresolved:** Medium (one city fails silently; production has mixed success state).
- **Acceptance / Verification Plan:**
  - Break one city's `.env.*` (e.g. bad password).
  - Run deploy script.
  - Script must report failure for that city, success for others, and exit non-zero.

### 8. Scheduler / trigger logic not per-city
- **Description:** ts + compose curl hardcode "ogre". Per-city deploys will not schedule correctly for other cities.
- **Likelihood:** Very High.
- **Effort to resolve:** Medium (make city configurable in ts and compose, update deploy script).
- **Impact if unresolved:** Critical (scheduling only works for default city).
- **Acceptance / Verification Plan:**
  - See item 2 verification (trigger + data match per city).

### 9. Logging and observability not isolated per city
- **Description:** Multiple cities writing to similar log files or stdout on the same host.
- **Likelihood:** Medium-High.
- **Effort to resolve:** Low-Medium (use container names in logs, per-project log drivers, or separate log paths).
- **Impact if unresolved:** Medium (difficult to debug a single city's issues in production).
- **Acceptance / Verification Plan:**
  - Deploy 5 cities and run pipelines.
  - Confirm logs are clearly attributable to specific cities (e.g. via container name or log prefix).

### 10. Backup/restore and CI/CD not multi-city aware
- **Description:** Backup scripts target container names; CI workflows are single-env. No city parameter.
- **Likelihood:** High.
- **Effort to resolve:** Medium (parameterize scripts, update CI for per-city or matrix builds).
- **Impact if unresolved:** High (backups target wrong DB, restores corrupt data, CI cannot deploy specific cities reliably).
- **Acceptance / Verification Plan:**
  - For each of 5 cities: run backup → verify file in correct S3 bucket.
  - Simulate restore for one city → verify only that city's data is restored.
  - Trigger CI for a specific city (if matrix added) and confirm correct deployment.

## Summary Recommendations

**Priority order (by impact):** 2, 3, 4, 8, 5, 1, 7, 6, 9, 10.

**Estimated total effort for all items:** Medium-High (roughly 2-4 weeks for one developer, with some items parallelizable).

**Suggested MVP slice for 5 cities:** Solve items 1, 2, 3, 4, and 8 first.

**Verification approach:** Use the per-problem acceptance plans above as an executable checklist. Run on a staging-like environment (dev-1.5.13 or equivalent) before promoting to production.

**Additional notes:**
- Prefer per-city buckets (or strong prefixes) for both DB backups and lambda data to avoid collisions.
- Consider centralizing city configuration (e.g. a `cities.json` or list in one place) instead of multiple hard-coded locations.
- The current "per compose project" model provides good isolation but increases operational surface (5 DBs, 5 schedulers, etc.).

This plan was created after reviewing `deploy-multi-city-ws.sh`, `docker-compose.yml`, S3 bucket configuration via code and `gh search`, and the multi-city history in the repo.

---

# Scalable Architecture Proposal for 5+ Cities (Current Phase - No Lambda)

**Goal:** Design a scalable way to scrape data for 5 or more cities and reliably back up scraped data + DB dumps to AWS S3, while keeping Lambda as a low-priority item (to be done much later).

## Current Limitations (for 5+ cities)
- Hardcoded city lists
- Hardcoded "ogre" in compose triggers
- Hardcoded lambda bucket (irrelevant for now)
- No automatic upload of locally scraped data to S3
- DB backups and lambda data strategy not generalized
- All services on one host with no resource controls
- Scheduler/trigger not easily multi-city

## Recommended Scalable Architecture (Current Phase)

### 1. Configuration-Driven Cities
- Introduce a central config file: `config/cities.yaml`
- Example structure:
  ```yaml
  cities:
    ogre:
      name: ogre
      display_name: "Ogre"
      main_url: "https://www.ss.lv/lv/real-estate/flats/ogre-and-reg/ogre/sell/"
      email_title: "Ogre City Apartments for sale"
      s3_prefix: "ogre"
    sigulda:
      name: sigulda
      ...
    # add more cities here
  ```
- Each city can still have its own `.env.{city}` for secrets (passwords, keys).
- `S3_BUCKET` can be the same bucket for all (with prefixes) or different per city.

### 2. Deployment Layer (Enhance Existing)
- Update `deploy-multi-city-ws.sh` to read from `cities.yaml` instead of hardcoded array.
- Support:
  - Deploy all cities
  - Deploy specific cities: `./deploy-multi-city-ws.sh ogre sigulda riga`
- Keep using `--project-name $city` for isolation (this is the right pattern).
- Add resource limits in `docker-compose.yml` (memory, cpus) per service.

### 3. Scraping Data (Local, No Lambda)
- Each city's `ws` container runs local scraping using `CITY_MAIN_URL` from env.
- After successful scrape in `extract_data_from_url`:
  - **Only upload the raw report** to S3 (processed DF and PDF are **not** uploaded per city).
  - Upload path (using per-city bucket):
    ```
    s3://sslv-prod-{city}-scraped-data/scraped-data/{YYYY-MM-DD}/raw-report.txt
    ```
- This replaces the role of Lambda data upload for the current phase.
- The `file_downloader` can be made optional or city-aware later when Lambda is implemented.

### 4. Backing Up to AWS S3 (Scraped Data + DB)
**Two separate backup paths:**

**A. Scraped Raw Data Upload (new responsibility in current phase)**
- Done inside the `ws` container after scraping (or as a post-step in the pipeline).
- **Only raw reports are uploaded** (DF and PDF are not uploaded per city).
- Use dedicated per-city bucket (as decided).
- This gives us a durable backup of what was scraped, independent of the DB.

**B. DB Backups (per city)**
- Enhance `scripts/backup_pg_container_db.sh` and `upload_backup_to_s3.sh` to accept a city parameter.
- Container name becomes `{city}-db-1` thanks to project name.
- Upload path (using per-city bucket):
  ```
  s3://sslv-prod-{city}-scraped-data/db-backups/{YYYY_MM_DD}.sql
  ```
- Can be triggered by a per-city cron or a lightweight sidecar container.

**S3 Strategy Recommendation (Current Phase):**
- Use **one dedicated bucket per city** for strong isolation (decision applied):
  - `sslv-prod-ogre-scraped-data`
  - `sslv-prod-sigulda-scraped-data`
  - etc.
- Upload paths (only raw reports + DB backups):
  - Raw reports: `s3://sslv-prod-{city}-scraped-data/scraped-data/{date}/raw-report.txt`
  - DB backups: `s3://sslv-prod-{city}-scraped-data/db-backups/{date}.sql`
- Each city’s `.env.{city}` will contain its own `S3_BUCKET`.
- This avoids any risk of cross-city data leakage or naming collisions.

### 5. Scheduler (ts)
- Decision: **One `ts` container per city** (simplest, matches current per-compose-project model).
- Each city’s `ts` will know its city via environment variables (e.g. `CITY=ogre`).
- This keeps isolation clean and avoids a single point of failure for scheduling across all cities.

### 6. Resource & Horizontal Scaling
- Start with all cities on one host using resource limits in compose.
- When limits are hit:
  - Split cities across multiple hosts (e.g. Host A: ogre+sigulda, Host B: others).
  - Use the same deploy script with different Docker contexts or run compose files on different machines.
- This gives a clear path to horizontal scaling without rewriting everything.

### 7. Observability
- Container names already contain the city → easy filtering.
- Add `city` as a tag/prefix in logs where possible.
- Consider adding a small health/report endpoint per city that includes last scrape time and view count stats.

### 8. Deferring Lambda Cleanly
- Keep the current local-scrape + S3-upload path as the primary.
- When Lambda is implemented later:
  - It can be triggered by S3 events on the per-city bucket (e.g. `sslv-prod-{city}-scraped-data`).
  - Or poll the city-specific bucket.
  - The `file_downloader` logic can then be enabled per city to download from its dedicated bucket instead of (or in addition to) local scrape.
- No big rewrites needed.

### Migration from Current 3-City Setup (Low Risk)
1. Introduce `config/cities.yaml` with current 3 cities.
2. Update deploy script to read the config.
3. Make docker-compose fully env-driven (fix the ogre hardcode in curl/ts).
4. Add upload step after local scrape in the ws pipeline (**only raw reports**).
5. Parameterize backup scripts with city.
6. Create a dedicated S3 bucket for each city (e.g. `sslv-prod-ogre-scraped-data`).
7. Add 2 new cities to the config + create their `.env.*` files + their dedicated S3 buckets.
8. Deploy and validate one city at a time.

### Benefits of This Approach for 5+ Cities
- Easy to add a 6th or 10th city (just config + .env file + its dedicated S3 bucket).
- Strong isolation: each city has its own S3 bucket, own compose project, and own ts container.
- Good isolation via compose projects.
- No dependency on Lambda for the scraping + backup loop.
- Natural path to run on multiple hosts later.
- Backups are per-city and versioned by date.
- Only raw reports are stored in S3 (keeps storage lean and avoids uploading large DF/PDF files).

### Decisions Made (2026-07-08)

- **S3 bucket strategy**: One bucket **per city**.
- **Task Scheduler (ts)**: One `ts` container **per city**.
- **S3 uploads**: Upload **only raw reports**. Do **not** upload the processed DF or PDF per city.

These decisions have been incorporated into the architecture proposal above. The proposal directly addresses the highest-impact problems listed in this document (items 1, 2, 3, 4, 8, 10) while keeping the architecture simple enough for the current phase.
PLANEOF
echo "Scalable architecture proposal appended to M6_MVP_problem_list.md"
