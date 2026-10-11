# SS.LV Web Scraper

| | |
| --- | --- |
| Production Deploy | [![Deploy to Production](https://github.com/vfedotovs/sslv_web_scraper/actions/workflows/main.yml/badge.svg)](https://github.com/vfedotovs/sslv_web_scraper/actions/workflows/main.yml) |
| Coverage | [![codecov](https://codecov.io/gh/vfedotovs/sslv_web_scraper/graph/badge.svg?token=Y9AQW4YEYH)](https://codecov.io/gh/vfedotovs/sslv_web_scraper) |
| Explore Ogre City apartments for sale historical data | https://propertydata.lv/data/apartments-for-sale-data/ |

## About

This application scrapes the ss.lv website daily for apartments for sale in a specific city, stores the data in a PostgreSQL database, and sends a daily email report with analytics.

## Requirements

- Docker >= 25.0
- Docker Compose >= 2.20 (plugin) or docker-compose >= 1.29 (standalone)
- AWS CLI (for loading secrets from AWS Secrets Manager)
- AWS EC2 ARM instance (aarch64) for production/staging deployment

## How to use

### 1. Clone repository

```bash
git clone https://github.com/vfedotovs/sslv_web_scraper.git
cd sslv_web_scraper
```

### 2. Load secrets from AWS Secrets Manager

```bash
source scripts/load_secrets.sh
```

This downloads `.env.prod` and `database.ini` from S3 and exports environment variables from AWS Secrets Manager.

### 3. Run setup, build and start

```bash
make setup    # downloads secrets, DB backup, copies config files
make build    # builds all containers (db, ws, ts)
make up       # starts all containers
```

### Manual setup (alternative)

If not using AWS Secrets Manager, create files manually:

**database.ini:**
```ini
[postgresql]
host=db
database=new_docker_db
user=new_docker_user
password=<your db password>
```

**.env.prod:**
```bash
DEST_EMAIL=user@example.com
SRC_EMAIL=user@example.com
POSTGRES_PASSWORD=<your db password>
AWS_ACCESS_KEY_ID=<your aws key>
AWS_SECRET_ACCESS_KEY=<your aws secret>
```

## Daily DB Backup & Manual Restore Flow for Multi-City (M6)

**Important:** Restore is **manual only**. `deploy-multi-city-ws.sh` does **not** auto-restore DBs.

### Backup (Automated)
- Scheduled inside dedicated `{city}-backup-1` container (cron at 02:00 UTC).
- Per-city bucket: `sslv-prod-{city}-db-backups`
- Key: `db-backups/YYYY/MM/DD/pg_backup_....sql.gz`
- Script: `./scripts/backup_db_city.sh --all --env prod`
- Install cron on EC2: `./scripts/add_cron.sh --env prod`

### Manual Restore
- Use `./scripts/restore_db_city.sh --city <city> [--date YYYY_MM_DD] [--prepare-init]`
- `--prepare-init`: copies to `src/db/` for fresh volume init on next deploy.
- Normal mode: pipes to running `psql` in the DB container.
- Example for redeploy without losing data:
  1. `./scripts/restore_db_city.sh --city ogre --date 2026_07_08`
  2. `docker compose --project-name ogre --env-file .env.ogre up -d`

### Troubleshooting
- Failed pg_dump: check POSTGRES_PASSWORD in .env.city, container running.
- Wrong city: verify CITY in .env and bucket name.
- Permission errors: ensure AWS creds in env or IAM role on EC2.

See `docs/M6_phase_1_backup_restore_service_plan.md` for full details.

## Log collection (multi-city)

`scripts/collect_logs_v3.sh` gathers logs, pipeline artifacts and container
state from every city into one timestamped, redacted bundle.

```bash
make collect-logs                 # all cities
make collect-logs CITY=ogre       # one city
make collect-logs-running         # only cities with containers up
make collect-logs-full CITY=ogre  # + debug DB dump + data dirs (large)
```

Or call the script directly for the full option set:

```bash
./scripts/collect_logs_v3.sh --help
./scripts/collect_logs_v3.sh --city jurmala --since 24h
./scripts/collect_logs_v3.sh --city ogre --upload-dry-run   # show destinations
./scripts/collect_logs_v3.sh --city ogre --upload-s3        # actually upload
```

`--upload-s3` writes to the **real** `sslv-{env}-{city}-scraped-data` bucket
under `log-bundles/{date}/`. Check with `--upload-dry-run` first. A multi-city
bundle is uploaded to each collected city's bucket (the same object more than
once) — the CICD buckets must never hold scraped data. Upload is refused
outright with `--no-redact`, and skipped if the self-test failed.

**Output** — `log-bundles/sslv-logs-<UTC>/` plus a matching `.tar.gz`:

| Path | Contents |
|---|---|
| `SUMMARY.txt` | **Read this first** — health matrix + last errors per city |
| `MANIFEST.txt` | Full inventory: what was collected, skipped, and why |
| `REDACTION-SELF-TEST.txt` | PASS/FAIL proof that no secret survived |
| `host/` | `docker ps`, images, disk, versions, `deploy-multi-city.log` |
| `cities/<city>/<svc>/` | `logs/`, `artifacts/`, `stdout.log`, `inspect.json`, `health.json`, `config.txt` |

Containers are matched on the compose labels `com.docker.compose.project`
(the city) and `com.docker.compose.service` — never on a name substring, so
cities can never be mixed up. Stopped containers are collected too.

**Secrets.** AWS keys, DB passwords and SendGrid keys are masked throughout,
and `.env.*` / `database.ini` are recorded by name and mtime only, never read.
A self-test then re-scans the finished bundle, including inside the `.gz`
dump. If anything survives, the run exits `3` and **no archive is created**.

Exit codes: `0` complete · `1` partial · `2` fatal · `3` a secret survived
redaction (do not share the bundle).

> `scripts/collect_logs_v2.sh` is **deprecated** — it predates multi-city and
> collects every city into the same filenames. Use v3.

## Migration from 3-city to 6+ cities (one city at a time)

To scale safely:

1. Add city to `config/cities.yaml` (e.g. add `marupes_pag`).
2. Create `.env.marupes_pag` with CITY_MAIN_URL, EMAIL_CITY_TITLE, and S3_BUCKET=sslv-prod-marupes-pag-db-backups (and other creds if needed).
3. Create the S3 bucket: `make create-m6-bucket M6_CITY=marupes-pag M6_ENV=prod M6_PURPOSE=db-backups`
4. (Optional) Create scraped-data bucket similarly.
5. Test backup for the new city: `make backup-city CITY=marupes-pag ENV=prod`
6. Deploy the new city: `./deploy-multi-city-ws.sh` (it will pick up from config)
7. Simulate volume loss (e.g. `docker compose --project-name marupes_pag down -v`), then manual restore: `./scripts/restore_db_city.sh --city marupes_pag --env prod`
8. Verify with `make verify-backup CITY=marupes_pag` (S3 age/size) and `make test-restore CITY=marupes_pag` (restores into a throwaway container; the live DB is untouched)
9. Repeat for next city. Update CI/deploy if needed for per-city.

See also `docs/M6_MVP_problem_list.md` for full risks.


## Currently available features
- [x] Scrape ss.lv website to extract advert data from Ogre city apartments for sale section
- [x] Store scraped data in PostgreSQL database tables (listed_ads, removed_ads) for tracking price trends
- [x] Daily email report with advert URLs and key data categorized by room count
- [x] Automated deployment to AWS EC2 with GitHub Actions CI/CD (production + staging)
- [x] Tests and test coverage with Codecov integration
- [x] Container health checks for db, ws, and ts services
- [x] Cron service for automated DB backups and monitoring via ntfy.sh
- [x] OOM prevention with memory usage logging and garbage collection


## Work in progress
- [ ] Add Streamlit web service to CI/CD
- [ ] Add doc coverage step in CI/CD

## Dynamic Page Count & Multi-City (M6)

The scraper no longer hard-codes "first page only".

- `scrape_website(city_slug="jurmala")` automatically discovers the number of pages (e.g. 6 for Jūrmala).
- Uses `get_total_pages()` (parses ss.lv pager) + `get_page_url()`.
- City-prefixed report files: `jurmala-raw-data-report.txt`, `data/jurmala-raw-data-report-YYYY-MM-DD.txt`
- All pipeline steps (`data_format_changer`, mailers, etc.) accept a city parameter.
- Dev control: `SCRAPE_URL_LIMIT=0` to process all ads.

### Verification (Item 10)
```bash
make verify-scrape CITY=jurmala
make verify-scrape-all
```

### Adding a city with many pages (Item 11)
1. Add to `config/cities.yaml`
2. Create `.env.<city>` with `CITY_MAIN_URL` and `EMAIL_CITY_TITLE`
3. Run `make up` (or the multi-city deploy script)
4. `curl http://localhost:8000/run-task/<city>`

See `docs/m6-dynamic-page-count-action-plan.md` for the full plan.
