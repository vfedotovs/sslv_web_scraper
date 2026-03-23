# Integration & End-to-End Test Diagrams

This document contains test diagrams for planned integration and E2E tests.
**No test code has been implemented yet** — these are design references only.

---

## Integration Tests

### 1. Web Scraper → Formatter Integration

```
┌─────────────────┐     writes file      ┌──────────────────────┐
│  web_scraper.py  │ ──────────────────► │  data/                │
│  scrape_website()│                      │  Ogre-raw-data-      │
└─────────────────┘                      │  report-YYYY-MM-DD.txt│
                                          └──────────┬───────────┘
                                                     │ reads file
                                                     ▼
                                          ┌──────────────────────┐
                                          │ data_format_changer.py│
                                          │ cloud_data_formater_ │
                                          │ main()               │
                                          └──────────┬───────────┘
                                                     │ writes
                                                     ▼
                                          ┌──────────────────────┐
                                          │ data/formated_data/   │
                                          │ *.csv                 │
                                          └──────────────────────┘
```

**What to verify:**
- Raw data file written by scraper is parseable by formatter
- Output CSV has expected columns and row count
- Date formats are consistent between modules

---

### 2. Formatter → Cleaner Integration

```
┌──────────────────────┐    reads CSV     ┌─────────────────┐
│ data_format_changer.py│ ─────────────► │  df_cleaner.py   │
│ (output CSV)          │                 │  df_cleaner_main()│
└──────────────────────┘                 └────────┬─────────┘
                                                   │ writes
                                                   ▼
                                          ┌─────────────────┐
                                          │ Cleaned DataFrame│
                                          │ (saved to CSV)   │
                                          └─────────────────┘
```

**What to verify:**
- Cleaner handles all column types from formatter output
- NaN/missing values are handled correctly
- Price and area columns are numeric after cleaning
- No data rows lost unexpectedly

---

### 3. Cleaner → DB Worker → PostgreSQL Integration

```
┌─────────────────┐   cleaned CSV    ┌─────────────────┐
│  df_cleaner.py   │ ──────────────► │  db_worker.py    │
│  (output)        │                  │  db_worker_main()│
└─────────────────┘                  └────────┬─────────┘
                                               │
                          ┌────────────────────┼────────────────────┐
                          │                    │                    │
                          ▼                    ▼                    ▼
                  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
                  │ listed_ads   │   │ removed_ads  │   │  INSERT /    │
                  │ table        │   │ table        │   │  UPDATE ops  │
                  └──────────────┘   └──────────────┘   └──────────────┘
```

**What to verify:**
- New ads inserted into `listed_ads` table
- Removed ads moved to `removed_ads` table
- No duplicate entries on re-run
- Database connection via `database.ini` works correctly
- Transaction rollback on failure

---

### 4. Cleaner → Analytics Integration

```
┌─────────────────┐   cleaned data   ┌─────────────────┐
│  df_cleaner.py   │ ──────────────► │  analytics.py    │
│  (output)        │                  │  analytics_main()│
└─────────────────┘                  └────────┬─────────┘
                                               │ generates
                                               ▼
                                      ┌─────────────────┐
                                      │ Analytics report │
                                      │ (categorized by  │
                                      │  room count)     │
                                      └─────────────────┘
```

**What to verify:**
- Analytics correctly categorizes ads by room count
- Report contains all expected sections
- Statistics (avg price, count) are mathematically correct
- Empty categories handled gracefully

---

### 5. S3 → File Downloader Integration

```
┌─────────────────┐   downloads      ┌────────────────────────┐
│  AWS S3 Bucket   │ ──────────────► │  file_downloader.py     │
│  (lambda output) │                  │  download_latest_       │
└─────────────────┘                  │  lambda_file()          │
                                      └────────────┬───────────┘
                                                   │ saves to
                                                   ▼
                                      ┌────────────────────────┐
                                      │ local_lambda_raw_       │
                                      │ scraped_data/           │
                                      │ Ogre-raw-data-report-  │
                                      │ YYYY-MM-DDTHH-MM-SS.txt│
                                      └────────────────────────┘
```

**What to verify:**
- S3 client created and destroyed per call (no connection leak)
- File downloaded with correct naming convention
- Handles missing bucket / missing file gracefully
- Memory released after download (gc.collect works)

---

### 6. Full Pipeline → AWS Mailer Integration

```
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ df_cleaner   │   │ db_worker    │   │ analytics    │
│ (output)     │   │ (DB state)   │   │ (report)     │
└──────┬───────┘   └──────┬───────┘   └──────┬───────┘
       │                  │                   │
       └──────────────────┼───────────────────┘
                          │ all outputs feed
                          ▼
                 ┌─────────────────┐      sends via     ┌──────────┐
                 │  aws_mailer.py   │ ────────────────► │ AWS SES  │
                 │  aws_mailer_main │                    └──────────┘
                 └─────────────────┘
```

**What to verify:**
- Email contains data from all pipeline stages
- SES client handles auth correctly
- Email sent to DEST_EMAIL with correct subject/body
- Graceful failure if SES credentials missing

---

### 7. Task Scheduler → WS Health Check Integration

```
┌─────────────────┐                    ┌─────────────────┐
│  ts.py           │  HTTP GET          │  ws (FastAPI)    │
│  Task Scheduler  │ ──────────────►   │  /health         │
│  (port 8080)     │  localhost:8000    │  (port 8000)     │
└────────┬─────────┘                    └────────┬─────────┘
         │                                       │
         │  triggers at 00:40 UTC                │
         ▼                                       ▼
┌─────────────────┐                    ┌─────────────────┐
│  GET /run-task/  │  ──────────────►  │  Pipeline runs   │
│  ogre            │                    │  (full job)      │
└─────────────────┘                    └─────────────────┘
```

**What to verify:**
- TS health server responds on port 8080
- WS /health endpoint returns 200 OK
- TS successfully triggers /run-task/ogre
- Docker HEALTHCHECK passes for both containers

---

## End-to-End Tests

### E2E-1. Full Pipeline — Cloud Path (Lambda File Exists)

```
┌───────┐   ┌──────────────┐   ┌───────────────┐   ┌────────────┐
│  S3   │──►│file_downloader│──►│check_today_   │──►│cloud_data_ │
│bucket │   │download_latest│   │cloud_data_    │   │formater_   │
└───────┘   │_lambda_file() │   │file_exist()=T │   │main()      │
            └──────────────┘   └───────────────┘   └─────┬──────┘
                                                          │
            ┌──────────────┐   ┌───────────────┐         │
            │  aws_mailer_ │◄──│ analytics_    │◄──┬─────┘
            │  main()      │   │ main()        │   │
            └──────┬───────┘   └───────────────┘   │
                   │                                │
                   ▼                           ┌────┴───────┐
            ┌──────────────┐                   │df_cleaner_ │
            │  Email sent  │                   │main()      │
            │  via AWS SES │                   └────┬───────┘
            └──────────────┘                        │
                                               ┌────▼───────┐
                                               │db_worker_  │
                                               │main()      │
                                               └────────────┘

Response: "FAST_API: scrape Ogre city apartments task using cloud ws file run completed"
```

**What to verify:**
- Complete pipeline executes without errors
- Each stage receives valid input from previous stage
- gc.collect() called between stages (memory stays bounded)
- Final email contains today's data
- Response message matches expected string

---

### E2E-2. Full Pipeline — Local Scrape Path (No Lambda File)

```
┌──────────────┐   ┌───────────────┐   ┌───────────────┐
│file_downloader│──►│check_today_   │──►│check_lst_run_ │
│(no file found)│   │cloud_data_    │   │state()=False  │
└──────────────┘   │file_exist()=F │   └───────┬───────┘
                    └───────────────┘           │
                                                ▼
┌──────────────┐   ┌───────────────┐   ┌───────────────┐
│  aws_mailer_ │◄──│ analytics_    │◄──│scrape_website()│
│  main()      │   │ main()        │   └───────┬───────┘
└──────┬───────┘   └───────┬───────┘           │
       │                   │              ┌────▼───────────┐
       ▼                   │              │cloud_data_     │
┌──────────────┐           │              │formater_main() │
│  Email sent  │           │              └────┬───────────┘
│  via AWS SES │      ┌────┴───────┐          │
└──────────────┘      │db_worker_  │     ┌────▼───────┐
                      │main()      │◄────│df_cleaner_ │
                      └────────────┘     │main()      │
                                          └────────────┘

Response: "FAST_API: scrape Ogre city apartments task using local scrape job was completed"
```

**What to verify:**
- Falls through to local scrape when no cloud file exists
- scrape_website() produces valid raw data file
- Full pipeline completes end-to-end
- Response message matches expected string

---

### E2E-3. Duplicate Run Protection

```
                    First run today
                    ┌──────────────────────┐
                    │ GET /run-task/ogre    │
                    │ (completes normally)  │
                    └──────────┬───────────┘
                               │ creates
                               ▼
                    ┌──────────────────────┐
                    │ data/Ogre-raw-data-  │
                    │ report-YYYY-MM-DD.txt│
                    └──────────────────────┘

                    Second run same day
                    ┌──────────────────────┐
                    │ GET /run-task/ogre    │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ check_lst_run_state() │
                    │ returns True          │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ EXIT: "already run    │
                    │ in last 24H"          │
                    └──────────────────────┘
```

**What to verify:**
- First run completes and creates state file
- Second run same day is blocked by check_lst_run_state()
- No duplicate database entries
- Correct response message on duplicate run

---

### E2E-4. DB State Tracking Over Multiple Days

```
     Day 1                    Day 2                    Day 3
┌────────────┐          ┌────────────┐          ┌────────────┐
│ Scrape: 50 │          │ Scrape: 48 │          │ Scrape: 52 │
│ ads found  │          │ ads found  │          │ ads found  │
└─────┬──────┘          └─────┬──────┘          └─────┬──────┘
      │                       │                       │
      ▼                       ▼                       ▼
┌────────────┐          ┌────────────┐          ┌────────────┐
│ listed_ads │          │ listed_ads │          │ listed_ads │
│ = 50       │          │ = 48       │          │ = 52       │
│ removed=0  │          │ removed=2  │          │ removed=0  │
└────────────┘          │ (2 gone)   │          │ (4 new)    │
                         │ new = 0    │          └────────────┘
                         └────────────┘
```

**What to verify:**
- Ads present Day 1 but missing Day 2 move to `removed_ads`
- New ads on Day 3 are inserted into `listed_ads`
- `removed_ads` accumulates over time (never cleared)
- Ad counts are consistent across tables

---

### E2E-5. Cron Backup Pipeline

```
┌──────────┐   scheduled    ┌──────────────────┐
│  cron    │ ─────────────► │ backup_db.sh      │
│  service │                 │ pg_dump → .sql    │
└──────────┘                └────────┬─────────┘
                                      │
                                      ▼
                             ┌──────────────────┐    upload     ┌──────────┐
                             │upload_backup_     │ ────────────►│  AWS S3  │
                             │to_s3.sh           │              │ $S3_BUCKET│
                             └────────┬─────────┘              └──────────┘
                                      │
                                      ▼
                             ┌──────────────────┐   notify     ┌──────────┐
                             │ ntfy.sh notify   │ ────────────►│ ntfy.sh  │
                             │ (success/fail)   │              │ service  │
                             └──────────────────┘              └──────────┘
```

**What to verify:**
- pg_dump creates valid SQL backup
- Upload uses S3_BUCKET env var (not hardcoded)
- Notification sent on success and failure
- Backup file is restorable

---

### E2E-6. Container Health & Startup Order

```
     docker compose up
            │
            ▼
    ┌───────────────┐
    │   db service   │
    │  (PostgreSQL)  │
    │  HEALTHCHECK:  │
    │  pg_isready    │
    └───────┬───────┘
            │ healthy
            ▼
    ┌───────────────┐
    │   ws service   │
    │  (FastAPI)     │
    │  HEALTHCHECK:  │
    │  curl /health  │
    │  depends_on:   │
    │  db: healthy   │
    └───────┬───────┘
            │ healthy
            ▼
    ┌───────────────┐
    │   ts service   │
    │  (Scheduler)   │
    │  HEALTHCHECK:  │
    │  urllib :8080   │
    │  depends_on:   │
    │  ws: healthy   │
    └───────┬───────┘
            │ healthy
            ▼
    ┌───────────────┐
    │  cron service  │
    │  depends_on:   │
    │  db: healthy   │
    └───────────────┘
```

**What to verify:**
- Containers start in correct order: db → ws → ts, db → cron
- Each HEALTHCHECK passes within configured timeout
- Services wait for dependencies to be healthy before starting
- Failure in db prevents ws/ts/cron from starting

---

## Test Priority Recommendations

| Priority | Test | Type | Complexity | Value |
|----------|------|------|------------|-------|
| 1 | Cleaner → DB Worker → PostgreSQL | Integration | Medium | High — catches DB schema/data issues |
| 2 | Full Pipeline Cloud Path (E2E-1) | E2E | High | High — validates the primary daily flow |
| 3 | Duplicate Run Protection (E2E-3) | E2E | Low | High — prevents data corruption |
| 4 | Web Scraper → Formatter | Integration | Low | Medium — catches format changes from ss.lv |
| 5 | Container Health & Startup (E2E-6) | E2E | Medium | Medium — validates Docker orchestration |
| 6 | Formatter → Cleaner | Integration | Low | Medium — catches data type issues |
| 7 | S3 → File Downloader | Integration | Medium | Medium — validates cloud integration |
| 8 | DB State Over Multiple Days (E2E-4) | E2E | High | Medium — validates long-term tracking |
| 9 | Full Pipeline → AWS Mailer | Integration | Medium | Low — mailer rarely changes |
| 10 | Cron Backup Pipeline (E2E-5) | E2E | Medium | Low — backup is independent of main flow |
| 11 | TS → WS Health Check | Integration | Low | Low — simple HTTP check |
| 12 | Full Pipeline Local Scrape (E2E-2) | E2E | High | Low — cloud path is primary |
