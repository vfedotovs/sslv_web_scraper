# M6 Phase 1: Backup & Restore Service Plan

**Branch:** `dev-1.6.1`  
**Date:** 2026-07-09  
**Context:** Multi-city (5+ cities) deployment using `docker compose --project-name <city>` for isolation.  
**Reviewed Commit:** https://github.com/vfedotovs/sslv_web_scraper/commit/3c2ebe68eb20e01efe51cc66c97dc096130b9da0

---

## 1. Review of the Reviewed Commit (3c2ebe6)

The commit introduced a new `src/backup-svc/` prototype:

**Added files:**
- `Dockerfile`: `python:3.9` + `postgresql-client` + `cron`. Copies `backup_upload.py` + cronfile. Runs `cron -f`.
- `backup_upload.py`: 
  - `pg_dump` using hardcoded `DB-USER`, `DB-NAME`, host `db`.
  - `boto3` upload with hardcoded region + bucket.
  - No error handling, no env vars, no city awareness.
- `cronfile`: Daily `0 2 * * *` run.
- `docker-compose.yml`: Separate compose file mounting an **external** `db_data` volume. Depends on `db`. Not compatible with main project.
- `todo.md`: Extremely detailed self-assessment listing almost every problem (hardcodes, missing envs, no error handling, integration gaps, testing, docs, multi-city considerations).

**Assessment of the prototype:**
- Directionally correct (sidecar + cron + pg_dump + S3 is a reasonable pattern).
- Not production-ready and **not integrated**.
- Completely unaware of multi-city (`--project-name` changes container names to `{city}-db-1` and volume names).
- No support for the manual backup injection constraint around `deploy-multi-city-ws.sh`.

**Conclusion:** We can mine ideas (Dockerfile base, cron pattern, python structure) but must start fresh for multi-city scalability. The `todo.md` in the commit is still useful as a checklist.

---

## 2. Current State (as of dev-1.6.1)

- **Isolation model**: Each city deployed via `deploy-multi-city-ws.sh` uses its own compose project → `{city}-db-1`, `{city}_db_data` volume.
- **Initial data seeding**: `src/db/Dockerfile` does `COPY *.sql /docker-entrypoint-initdb.d/`. The `make setup` flow downloads a dump via `get_last_s3_file.sh` / `src/db/get_last_db_backup.py` and places it in `src/db/`. This only works for **fresh volumes**.
- **Backup scripts**: Mostly placeholders (`scripts/backup_pg_container_db.sh` has `<container_name>` etc.). `collect_logs_v2.sh` has a one-off pg_dump. No daily automation.
- **Restore**: Manual. No robust city-aware restore script that works against a running `{city}-db-1`.
- **S3**: Uses a single `S3_BUCKET` (from Secrets Manager). Prior M6 decisions favor **per-city isolation**. Dedicated CICD buckets `sslv-prod-m6-cicd-files` and `sslv-staging-m6-cicd-files` (used by `load_secrets.sh` and `deploy-multi-city-ws.sh`) have been created and must **not** be reused for application DB backups or scraped data. Legacy `sslv-ws-m5-cicd-files` should be phased out for M6.
- **Deploy constraint** (explicit): Running `deploy-multi-city-ws.sh` (which can do `up` / rebuilds) does **not** automatically inject or manage DB backups. Injection/restore must stay a **manual operator step** before or around redeploys (especially after volume wipes with `-v`).

**Risks** (from M6 docs):
- Cross-city data corruption if scripts are not city-aware.
- Loss of data on redeploy if operators forget manual restore.
- No daily backup automation today.

---

## 3. Goals & Constraints

**Goals**
- Daily (configurable, e.g. 02:00 UTC) automated backup **per city**.
- City-isolated storage in S3 (align with prior architecture decisions).
- Reliable, scriptable manual restore path.
- Works with current `deploy-multi-city-ws.sh` + per-project model.
- Good logging, error handling, retention.
- Low operational overhead when adding cities (via `config/cities.yaml`).

**Hard Constraints**
- Backup injection / restore remains a **manual step** separate from `deploy-multi-city-ws.sh`. Do not embed automatic restore logic into the deploy script.
- Keep using the existing `docker compose --project-name` pattern.
- Prefer IAM roles on EC2 over long-lived keys where possible (use existing `load_secrets.sh` / Secrets Manager patterns for fallback).
- Postgres runs as plain `postgres:15` container (not RDS for now).

**Recommended High-Level Design**
- **Primary implementation**: The backup/restore logic runs **inside the dedicated backup container** (for scheduled runs) or manually from the host.
  - `scripts/backup_db_city.sh --city <slug>` (or `--all`)
  - `scripts/restore_db_city.sh --city <slug> [--date YYYY_MM_DD]`
- Container name convention: `{city}-db-1`
- S3 layout (per M6 decision + new constraint):
  - **Dedicated buckets per city per purpose** (strongly recommended). All 12 per-city buckets + 2 M6 CICD buckets have been created in eu-west-1 with public access fully blocked.
  - **Do not use** the legacy CICD bucket `sslv-ws-m5-cicd-files`, or the new M6 CICD buckets (`sslv-prod-m6-cicd-files`, `sslv-staging-m6-cicd-files`), for application data (or any buckets referenced by the `s3_db_backups` secret when those are tied to CICD artifact loading in main).
  - See "Proposed AWS S3 Bucket Naming Convention" and "Actual Buckets Created for M6 Phase 1" sections below for the exact list and scalable pattern.
- Scheduling: Implemented via a dedicated backup container (see "Containerized DB Backup Service" section below). The container includes cron + backup logic and has direct access to `{city}-db-1`.
- The reviewed `backup-svc` idea (Dockerfile + cron) will be revived/adapted as the dedicated `{city}-backup-1` service.

## Containerized DB Backup Service (Dedicated Docker Container)

**Yes — the DB backup service (including scheduling) is explicitly planned to run as a dedicated Docker container**, not as a host-level cron job on the EC2 instance.

### Why a Dedicated Container?
- Matches the updated requirement: "scheduling must be triggered inside docker container".
- Provides isolation per city (via `--project-name`).
- Allows the backup process to have direct, reliable network access to the city's `db` service.
- Reuses the pattern from the reviewed commit (`src/backup-svc` with its own `Dockerfile` + internal `cron`).
- Keeps the host clean — the EC2 only runs the main multi-city services.

### Architecture
For each city (using `docker compose --project-name <city>`):

```
[city project]
├── {city}-db-1          (postgres:15)
├── {city}-ws-1          (web scraper)
├── {city}-ts-1          (task scheduler)
└── {city}-backup-1      ← NEW: dedicated backup container
    ├── cron (inside container)
    ├── backup logic (adapted from backup_db_city.sh)
    └── direct access to {city}-db-1 network
```

The backup container:
- Runs its own cron (e.g. daily at 02:00).
- Executes the backup (pg_dump → gzip → S3 upload to the city's `*-db-backups` bucket).
- Can be included in the main `docker-compose.yml` (as an optional service) or deployed via the same `deploy-multi-city-ws.sh` pattern.

### Implementation Approach
1. Revive / adapt `src/backup-svc/`:
   - Use the existing `Dockerfile` (python + postgresql-client + cron).
   - Add the city-aware backup logic (from `scripts/backup_db_city.sh` or a container-optimized version).
   - Configure cron inside the container (via `cronfile` or entrypoint).
2. Make it multi-city aware:
   - Accept `CITY` / `ENV` env vars.
   - Derive container name `{CITY}-db-1`.
   - Derive S3 bucket: `sslv-{ENV}-{CITY}-db-backups`.
3. Integration:
   - Add `backup` service to `docker-compose.yml` (with `depends_on: db`).
   - Deploy it together with the city using the existing multi-city deploy script (or a small extension).
4. Manual fallback:
   - The host scripts (`backup_db_city.sh`, `restore_db_city.sh`) remain available for one-off runs from the EC2 shell.

### Benefits vs Host Cron
- Consistent with "inside Docker" requirement.
- Easier to version, log, and monitor the backup process.
- Can share the same network/credentials as the city services.
- Scales naturally with the per-city compose projects.

---

## Proposed AWS S3 Bucket Naming Convention (Multi-City Scalability)

### Core Constraints
- **Never reuse CICD buckets** for application data. The following are off-limits for DB backups and scraped reports:
  - Legacy: `sslv-ws-m5-cicd-files`
  - New dedicated M6 CICD buckets (use these only for deployment files):
    - `sslv-staging-m6-cicd-files`
    - `sslv-prod-m6-cicd-files`
  - Any bucket currently referenced via the `s3_db_backups` key in Secrets Manager **if** it is also used for CICD artifact loading in the production `main` branch.
- Buckets must support strong per-city isolation.
- Easy to add new cities without touching existing ones.
- Clear separation between **deployment artifacts** (CICD) and **operational data** (DB backups + scraped reports).

### Recommended Bucket Naming Pattern

**Format:**
```
sslv-{env}-{city-slug}-{purpose}
```

**Components:**
- `{env}`: `prod` | `staging` | `dev`
- `{city-slug}`: exact value from `config/cities.yaml` (lowercase with underscores preserved where used):
  - `salaspils`, `sigulda`, `marupes_pag`, `adazu_nov`, `ogre`, `jurmala`
- `{purpose}`: `db-backups` | `scraped-data`

**Production Examples (all 12 per-city buckets created):**
- `sslv-prod-salaspils-db-backups`
- `sslv-prod-salaspils-scraped-data`
- `sslv-prod-sigulda-db-backups`
- `sslv-prod-sigulda-scraped-data`
- `sslv-prod-marupes-pag-db-backups`
- `sslv-prod-marupes-pag-scraped-data`
- `sslv-prod-adazu-nov-db-backups`
- `sslv-prod-adazu-nov-scraped-data`
- `sslv-prod-ogre-db-backups`
- `sslv-prod-ogre-scraped-data`
- `sslv-prod-jurmala-db-backups`
- `sslv-prod-jurmala-scraped-data`

**Development / Test Examples:**
- `sslv-dev-ogre-db-backups`
- `sslv-staging-adazu-nov-scraped-data`

**Dedicated CICD / Deployment Buckets (created for M6, separate from app data):**
- `sslv-staging-m6-cicd-files` — for staging deployment secrets, .env files, and CI/CD artifacts
- `sslv-prod-m6-cicd-files` — for production deployment secrets, .env files, and CI/CD artifacts

These replace the legacy `sslv-ws-m5-cicd-files` for M6 deployments and must only be used for deployment-related files (not DB backups or scraped data).

### Recommended Object Key Structure (inside each bucket)

**For DB Backups** (used by the new Phase 1 backup service):
```
db-backups/{YYYY}/{MM}/{DD}/pg_backup_{YYYY_MM_DD_HHMMSS}.sql.gz
```

Examples:
- `db-backups/2026/07/09/pg_backup_2026_07_09_020000.sql.gz`

Alternative (simpler daily snapshot):
```
db-backups/{YYYY_MM_DD}.sql.gz
```

**For Scraped Data** (raw reports):
```
scraped-data/{YYYY-MM-DD}/raw-report.txt
```

### Why This Convention Scales Well

| Benefit | Explanation |
|---------|-------------|
| **Strong isolation** | Each city has its own bucket(s) → IAM policies, lifecycle rules, and access can be scoped per city |
| **No CICD contamination** | Explicitly different from `*-cicd-files` and CICD-tied backup buckets used in main |
| **Easy onboarding** | Adding a 7th city = create 1-2 new buckets + add entry to `cities.yaml` + `.env.{city}` |
| **Cost & retention control** | Lifecycle policies (e.g. delete after 90 days) can be set independently per bucket |
| **Auditability** | Bucket names clearly indicate environment, city, and data type |
| **Future Lambda / events** | S3 event notifications stay isolated per city |

### Bucket Strategy Options

1. **Recommended (Strong Isolation)**: Two buckets per city (`-db-backups` + `-scraped-data`)
2. **Fewer buckets**: One combined bucket `sslv-prod-{city}-data` with strict prefixes (`db-backups/` and `scraped-data/`). Acceptable if IAM is carefully managed.
3. **Avoid**: Reusing the existing `sslv-...-db-backups-2025-11` style buckets, the legacy `sslv-ws-m5-cicd-files`, or the new M6 CICD buckets (`sslv-prod-m6-cicd-files`, `sslv-staging-m6-cicd-files`) for application data if they are currently wired into CICD flows in `main`.

### Actual Buckets Created for M6 Phase 1

All buckets were created in **eu-west-1** with public access fully blocked.

**Per-City Application Data Buckets (12 total — 6 cities × 2):**

- `sslv-prod-salaspils-db-backups`
- `sslv-prod-salaspils-scraped-data`
- `sslv-prod-sigulda-db-backups`
- `sslv-prod-sigulda-scraped-data`
- `sslv-prod-marupes-pag-db-backups`
- `sslv-prod-marupes-pag-scraped-data`
- `sslv-prod-adazu-nov-db-backups`
- `sslv-prod-adazu-nov-scraped-data`
- `sslv-prod-ogre-db-backups`
- `sslv-prod-ogre-scraped-data`
- `sslv-prod-jurmala-db-backups`
- `sslv-prod-jurmala-scraped-data`

**Dedicated CICD Buckets (2 total — for deployment secrets and files only):**

- `sslv-staging-m6-cicd-files`
- `sslv-prod-m6-cicd-files`

These CICD buckets are used by `deploy-multi-city-ws.sh` (via `CICD_FILES_BUCKET`) and `load_secrets.sh` to source `.env.*` files, `database.ini`, and other deployment artifacts. They must **never** be used for DB backups or scraped data.

### Implementation Notes for the Plan

- All 14 buckets (12 per-city + 2 M6 CICD) have already been created in eu-west-1 with public access fully blocked.
- Item #1 (Formalize S3 conventions) is implemented: naming is documented below + Makefile support added (`make create_m6_bucket CITY=xxx ENV=prod PURPOSE=db-backups` or `make create_s3_bucket BUCKET_NAME=sslv-prod-xxx-db-backups`). See updated Makefile, CLAUDE.md and M6_MVP_problem_list.md.
- Each city's `.env.{city}` (or Secrets) should point to its own DB backup bucket (not a shared one).
- The backup script (`backup_db_city.sh`) must construct the bucket name from city + env, or take it directly from environment.
- Update `deploy-multi-city-ws.sh` and related scripts to default `CICD_FILES_BUCKET` to the new M6 CICD buckets (`sslv-prod-m6-cicd-files` for prod, `sslv-staging-m6-cicd-files` for staging).
- Use `make create_m6_bucket CITY=<city> ENV=prod PURPOSE=db-backups` (or scraped-data) to create future buckets following the convention.
- Additional helpers added to Makefile:
  - `make list_m6_buckets` – prints all expected M6 bucket names (all envs/cities/purposes).
  - `make list_existing_m6_buckets` – shows which M6 buckets actually exist in your AWS account.
  - `make tag_existing_bucket BUCKET_NAME=sslv-prod-xxx-db-backups` (or M6_ vars) – reapplies correct M6 tags.
  - `make check_m6_bucket BUCKET_NAME=...` – verifies public access block, versioning, location, and lifecycle.
  - `make create_all_m6_buckets ENV=prod` – bulk-create all 12 buckets for an environment (use with caution).
- **Scheduling note**: The DB backup service (including cron) is implemented as a dedicated Docker container (`{city}-backup-1`). See the new "Containerized DB Backup Service" section above. Host scripts are only for manual/one-off use.

---

## 4. Actionable Item Plan

Items are ordered by recommended implementation sequence.  
**Effort**: Low (< 0.5 day), Medium (0.5-2 days), High (2-5+ days)  
**Impact**: Low / Medium / High (on data durability, ops, scalability, risk reduction)

| # | Item | Description | Effort | Impact | Order / Phase | Dependencies / Notes |
|---|------|-------------|--------|--------|---------------|----------------------|
| 1 | Formalize S3 conventions & update docs | Decide & document exact S3 bucket naming + key patterns for DB backups. Must use **separate buckets** from CICD artifacts (use the new `sslv-prod-m6-cicd-files` / `sslv-staging-m6-cicd-files`). Align with raw-report paths. Update `M6_MVP_problem_list.md`, `CLAUDE.md`, `M6_phase_1_backup_restore_service_plan.md`. All 14 buckets (12 per-city + 2 CICD) have been created. | Low | High | 1 (Foundation) | Use prior M6 decisions + explicit "no CICD bucket reuse" constraint. Get sign-off on bucket strategy. |
| 2 | Create robust city-aware backup script | ✅ Done - `scripts/backup_db_city.sh` supports --city/--all, config parsing, docker exec pg_dump + gzip + aws s3 cp to per-city bucket, error handling & logging. | Medium | High | 2 (Core) | Done |
| 3 | Create city-aware restore / injection script | ✅ Done - `scripts/restore_db_city.sh` with --date / latest, --prepare-init mode, running psql restore. | Medium | High | 3 (Core) | Done |
| 4 | Add scheduling / daily automation | ✅ Done - Dedicated `{city}-backup-1` container added to docker-compose.yml (build: ./src/backup-svc with Dockerfile + internal cron + backup.py). Per-city via project name. Host scripts only for manual use. Revived backup-svc pattern. | Low-Medium | High | 4 | Done |
| 5 | Update supporting scripts & Makefile | ✅ Done - Made get_last_s3_file.sh and get_last_db_backup.py city-aware (--city/--all/--env, reads cities.yaml or .env). Updated fetch_dump. Added Makefile targets: backup-city, restore-city, backup-all, restore-all, etc. | Medium | Medium | 5 | Done |
| 6 | Light integration & safety in deploy tooling | ✅ Done - Added comments (no auto-restore), non-fatal pre-deploy backup age check, improved logging in deploy-multi-city-ws.sh. Updated README with flow section. | Low | Medium | 5-6 | Done |
| 7 | Retention, compression, and cleanup policy | ✅ Done - Added S3 prune keep-last-5 in backup_db_city.sh. Gzip present. S3 lifecycle in Makefile. | Low-Medium | Medium | 6 | Done |
| 8 | Documentation & operational runbooks | ✅ Done - Updated CLAUDE.md, README, docs/multi-city-5city-prod-risk-assessment.md with "Daily DB Backup & Manual Restore Flow for Multi-City", examples, troubleshooting. | Low | High | 6-7 | Done |
| 9 | Basic verification & health of backups | ✅ Done - After backup: size check (>1KB threshold), `aws s3 ls` verify in backup_db_city.sh. Added `verify-backup` and `test-restore` Makefile targets (lists tables after restore as verification step). | Medium | High | 7 | Done |
| 10 | Optional: Revive & improve backup-svc (future) | ✅ Done - Revived src/backup-svc/ (Dockerfile + cron + city-aware backup.py with CITY/ENV support and fallback). Added to docker-compose.yml with profiles: ["backup"]. Per-city via --project-name. Updated docs. | High | Medium | 8+ (Optional) | Done |
| 11 | Testing, CI, and migration | ✅ Done - Added tests/test_m6_backup_restore.py (mocked help/args/E2E sim with pytest). Added migration steps to README.md (one city at a time). Added `e2e-backup-restore` and `test-restore` Makefile targets (backup → vol loss sim → restore → verify tables). | Medium-High | High | Parallel / after core | Done |
| 12 | Observability & notifications (stretch) | Log backup success/failure to a central place (or CloudWatch). Optional: simple SNS/email on failure (reuse sendgrid? or native). | Medium | Low-Medium | Later | Nice to have once core reliability is there. |

**Recommended Implementation Order (summary)**

**Phase 1 (MVP - get daily backups working safely)**
1 (done) → 2 (done) → 3 (done) → 4 (done)

**Phase 2 (Usability & deploy safety)**
5 (done) → 6 (done) → 7 (done) → 8 (done)

**Phase 3 (Confidence & optional advanced)**
9 (done) → 11 (done) → 10 (done, optional) → 12

---

## 5. Key Risks & Mitigations

- **Wrong city data restored**: City-aware scripts + strict naming + manual step (operator must specify city) + good docs.
- **Backup runs while DB is being written**: pg_dump is safe for this workload (consistent snapshot at start). Still, run at quiet time (e.g. 2am after scrape?).
- **Credential management on EC2**: Prefer instance role with S3 + minimal perms. Fall back to env from `load_secrets.sh`.
- **Volume vs running DB**: Clarify in docs when to use init-time SQL vs running psql restore.
- **Deploy script changing container names**: Always derive name as `${CITY}-db-1`.
- **Cost**: Lifecycle policies (already prototyped in Makefile) + gzip.

---

## 6. Deliverables per Phase

- ✅ `scripts/backup_db_city.sh` and `restore_db_city.sh` (manual or inside container)
- ✅ Dedicated `{city}-backup-1` container (src/backup-svc + docker-compose)
- ✅ Pre-deploy safety check, improved logging in deploy script (item 6)
- ✅ Retention/prune in backup script (item 7)
- ✅ Full docs with flow, examples, troubleshooting (item 8)
- Makefile helpers
- All 14 buckets ready (public blocked)
- Host scripts for manual only
- ✅ Basic verification (size/S3) in backup, test-restore with table list in Makefile/restore script (item 9)
- ✅ Backup-svc revived as dedicated container with profiles and city-aware logic (item 10)
- ✅ Basic mocked tests (pytest), migration doc in README, E2E Makefile target (item 11)

---

## 7. Next Steps After This Plan

1. Review & agree on this plan (especially the updated scheduling requirement: **inside Docker container**, not host cron on EC2).
2. Implement in small PRs on `dev-1.6.1` (items 1-11 completed).
3. Item 11 done: basic mocked tests, migration docs, E2E simulation target.
4. Test end-to-end on a non-prod city first.
5. Update `M6_MVP_problem_list.md` with status (mark related risks as mitigated once done).

This plan directly addresses the reviewed incomplete backup-svc commit while respecting the multi-city architecture and the critical constraint around `deploy-multi-city-ws.sh`.