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

Then run:
```bash
make build
make up
```

## Make targets

```
help                 This help message
precheck             Checks OS, architecture and if required exports are present
setup                Loads secrets and pulls DB backup file
build                Builds all containers (ts, ws, db)
up                   Starts all containers
down                 Stops all containers
clean                Removes setup and DB files and folders
lt                   Lists table sizes to test if DB dump was restored correctly
test                 Runs pytests locally
test_cov             Runs pytest coverage
```

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
