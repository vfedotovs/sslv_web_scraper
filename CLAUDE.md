# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an SS.LV Web Scraper application that scrapes real estate apartment listings from ss.lv for multiple Latvian cities (Ogre, Sigulda, Salaspils), stores data in PostgreSQL, performs analytics, and sends daily email reports with PDF attachments.

**Live data portal:** http://propertydata.lv/

## Architecture

The application uses a multi-container Docker architecture with three core services:

### Container Services

1. **db** - PostgreSQL database
   - Stores scraped data in `listed_ads` and `removed_ads` tables
   - Health check: `pg_isready -U new_docker_user -d new_docker_db`

2. **ws** (Web Scraper Worker) - FastAPI application (port 8000)
   - Main application logic in `src/ws/app/main.py`
   - Handles scraping orchestration via `/run-task/{city}` endpoint
   - Processing pipeline executes in order:
     1. `file_downloader` - Downloads latest data from AWS Lambda S3 bucket
     2. `web_scraper` - Scrapes ss.lv locally if cloud data unavailable
     3. `data_format_changer` - Formats raw scraped data
     4. `df_cleaner` - Cleans and validates data
     5. `db_worker` - Inserts/updates PostgreSQL tables
     6. `analytics` - Generates price statistics
     7. `pdf_creator` - Creates analytics PDF
     8. `aws_mailer` - Sends email report (previously SendGrid, now AWS SES)
   - Health check: Python urllib checking `/docs` endpoint

3. **ts** (Task Scheduler) - Python scheduler (`src/ts/ts.py`)
   - Triggers daily scraping at 00:40 UTC via HTTP GET to `ws:8000/run-task/ogre`
   - Runs health check HTTP server on port 8080 (`/health` endpoint)
   - Health check: Python urllib checking `/health` endpoint

### Service Dependencies & Health Checks

Services start in dependency order using health checks:
```
db (healthy) → ws (healthy) → ts (healthy)
```

All containers use Python's built-in `urllib.request` for health checks (no curl dependency).

### Multi-City Deployment

The application supports parallel deployment for multiple cities using Docker Compose project names:
- Each city has separate `.env.{city}` file (e.g., `.env.ogre`, `.env.salaspils`)
- Containers are named: `{city}-db-1`, `{city}-ws-1`, `{city}-ts-1`
- Deploy all: `./deploy-multi-city-ws.sh` (ogre, sigulda, salaspils)
- Undeploy all: `./undeploy-multi-city.sh`

**Important:** Do NOT expose ts health check port 8080 to host when running multi-city (causes port conflicts). Health checks work within Docker network.

## Development Setup

### Prerequisites
- Docker 20.10.11+
- Docker Compose v2.2.1+
- AWS CLI and `jq` (for EC2/production setup)
- Python 3.8+

### Environment Files Required

**`.env.prod`** (or `.env.{city}` for multi-city):
```bash
POSTGRES_PASSWORD=<password>
DEST_EMAIL=user@example.com
SRC_EMAIL=user@example.com
RELEASE_VERSION=<version>
SENDGRID_API_KEY=<key>  # Legacy, now using AWS SES
AWS_ACCESS_KEY_ID=<key>
AWS_SECRET_ACCESS_KEY=<secret>
```

**`database.ini`** (auto-downloaded via Makefile setup):
```ini
[postgresql]
host=db
database=new_docker_db
user=new_docker_user
password=<password>
```

### AWS Secrets Manager Integration

Production setup uses AWS Secrets Manager for credentials:
- Secret ID: `sslv_creds`
- Contains: `s3_db_backups`, `sendgrid_api`, `dest_email`, `src_email`, `release_version`
- Scripts: `scripts/set_s3_env_from_aws_sm.sh`, `scripts/load_secrets.sh`

## Common Commands

### Using Makefile (Recommended)

The Makefile provides idempotent, validated setup with colored output:

```bash
make help                    # Show all available commands

# Setup (downloads .env.prod, database.ini, and latest DB backup from S3)
make setup                   # Idempotent - skips if already completed
make verify-setup            # Verify all setup files exist
make check-backup-age        # Warn if DB backup is old (>30 days)

# Docker operations
make build                   # Build all containers (db, ts, ws)
make up                      # Start all containers
make down                    # Stop containers and remove volumes
make clean                   # Remove all setup files and state

# Database operations
make lt                      # List table sizes (verify DB restore)
make fetch_dump DB_BACKUP_DATE=2022_11_05  # Fetch specific dated backup

# AWS operations
make create_s3_bucket        # Create new S3 bucket for DB backups
make create_s3_bucket BUCKET_NAME=custom-name AWS_REGION=us-west-2

# Testing (Note: currently not fully implemented)
make test                    # Run pytest
make test_cov                # Run pytest with coverage
```

### Makefile Features

- **Idempotency**: Setup creates `.setup_state` file to avoid re-downloading
- **Error handling**: Uses `set -e` and validates each step
- **Cleanup on failure**: Automatically removes partial files if setup fails
- **Backup validation**: Checks file size, warns about old backups
- **Consistent logging**: Color-coded output (ℹ info, ✓ success, ⚠ warning, ✗ error, ▶ step)

### Direct Docker Commands

```bash
# Single city deployment
docker-compose --env-file .env.prod up -d
docker-compose --env-file .env.prod down -v

# Multi-city deployment
./deploy-multi-city-ws.sh      # Deploy ogre, sigulda, salaspils
./undeploy-multi-city.sh       # Stop all city instances

# Check health status
docker ps                      # Shows (healthy) status
docker inspect --format='{{json .State.Health}}' <container-name> | jq
```

### Testing the Application

```bash
# Trigger scraping manually
curl http://localhost:8000/run-task/ogre

# Check health endpoints
curl http://localhost:8000/docs    # ws FastAPI docs
curl http://localhost:8080/health  # ts health (if port exposed)

# Monitor logs
docker logs -f <container-name>
```

## Testing

Tests are located in `tests/` directory and follow module naming:
- `test_01_module_web_scraper.py`
- `test_02_module_data_formater.py`
- `test_03_module_df_cleaner.py`
- `test_04_module_db_worker.py`
- `test_05_module_analytics.py`
- `test_06_module_pdf_creator.py`
- `test_07_module_aws_mailer.py`

**Run tests:**
```bash
# Local
pytest -v
coverage run -m pytest

# CI runs on branches: dev-1.4*.*
# Workflow: .github/workflows/CI.yml
```

## Code Organization

```
src/
├── db/          # PostgreSQL Dockerfile and init scripts
├── ts/          # Task scheduler service
│   ├── ts.py    # Main scheduler with health check server
│   └── Dockerfile
├── ws/          # Web scraper worker (FastAPI)
│   ├── app/
│   │   ├── main.py              # FastAPI entry point
│   │   └── wsmodules/           # Processing modules
│   │       ├── web_scraper.py   # ss.lv scraper
│   │       ├── data_format_changer.py
│   │       ├── df_cleaner.py
│   │       ├── db_worker.py     # PostgreSQL operations
│   │       ├── analytics.py
│   │       ├── pdf_creator.py
│   │       ├── aws_mailer.py    # Email via AWS SES
│   │       └── file_downloader.py  # S3 operations
│   └── Dockerfile
└── web/         # Streamlit data explorer (optional)

scripts/
├── set_s3_env_from_aws_sm.sh   # Load S3 bucket from Secrets Manager
├── load_secrets.sh              # Download .env.prod and database.ini from S3
└── get_last_s3_file.sh         # Download latest DB backup
```

## Database Schema

Primary tables in PostgreSQL:
- **`listed_ads`** - Currently active listings
- **`removed_ads`** - Historical data for price trend analysis

Database credentials (production):
- User: `new_docker_user`
- Database: `new_docker_db`
- Host: `db` (within Docker network)

## Key Configuration Details

### S3 Buckets
- **CICD files:** `sslv-ws-m5-cicd-files` (contains .env.prod, database.ini)
- **DB backups:** Pattern `{project}-{env}-{version}-db-backups-{date}`
  - Example: `sslv-ogre-city-dev-v1-6-db-backups-2025-11`
- **Lambda scraped data:** Downloaded to `local_lambda_raw_scraped_data/`

### File Patterns
- DB backups: `pg_backup_YYYY_MM_DD.sql`
- Raw scraped data: `{City}-raw-data-report-YYYY-MM-DD.txt`
- Cloud scraper data: `Ogre-raw-data-report-YYYY-MM-DDTHH-MM-SS.txt`

### Daily Task Logic (in `main.py`)
1. Check for today's cloud scraper file from AWS Lambda S3
2. If cloud file exists → use it for processing
3. If no cloud file → check if local scrape ran today (prevents duplicate runs)
4. If not run today → scrape locally and process

## CI/CD

GitHub Actions workflows in `.github/workflows/`:
- **CI.yml** - Runs pytest and coverage on `dev-1.4*.*` branches when `.py` files change
- **CICD-*.yml** - Various deployment pipelines to AWS EC2 for different environments/architectures

## Important Notes

### Email Service Migration
- **Old:** SendGrid (`sendgrid_mailer.py`) - commented out in main.py
- **New:** AWS SES (`aws_mailer.py`) - currently active
- Environment variable `SENDGRID_API_KEY` still required for backward compatibility

### Health Check Implementation
- All health checks use Python's built-in `urllib.request` (no curl dependency)
- ts service runs lightweight HTTP server (http.server.HTTPServer) on port 8080
- Health check port should NOT be exposed to host in multi-city deployments

### Gitignore Patterns
- SQL files: `pg_*.sql` (not `*.sql` to avoid excluding test fixtures)
- Sensitive files: `.env.prod`, `database.ini`, `.setup_state`
- All `.txt`, `.csv`, `.pdf`, `.log` files (except whitelisted test files)

### Branch Strategy
Current development branch: `dev-1.6.0`
Main branch: `main`

## Troubleshooting

**Port conflict errors (port 8080 already allocated):**
- Comment out `ports: - "8080:8080"` in docker-compose.yml for ts service
- Health checks work without external port exposure

**Setup fails to download from S3:**
- Ensure AWS CLI configured: `aws configure`
- Check AWS Secrets Manager access: `aws secretsmanager get-secret-value --secret-id sslv_creds`
- Verify jq installed: `brew install jq` (macOS)

**Database connection errors:**
- Wait for db health check: `docker ps` shows "(healthy)" status
- Check database.ini copied to `src/ws/database.ini`
- Verify environment variables in container: `docker exec <container> env`

**Old DB backup warnings:**
- Normal if backup is >30 days old
- Fetch newer backup: `make fetch_dump DB_BACKUP_DATE=YYYY_MM_DD`
- Or create new: Use `make create_s3_bucket` for new backup bucket
