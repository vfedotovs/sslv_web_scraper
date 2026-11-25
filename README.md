# SS.LV Web Scraper

| | |
| --- | --- |
| Tests / production deploy | [![Test and deploy to production](https://github.com/vfedotovs/sslv_web_scraper/actions/workflows/main.yml/badge.svg)](https://github.com/vfedotovs/sslv_web_scraper/actions/workflows/main.yml) |
| Coverage | [![codecov](https://codecov.io/gh/vfedotovs/sslv_web_scraper/graph/badge.svg?token=Y9AQW4YEYH)](https://codecov.io/gh/vfedotovs/sslv_web_scraper) |
| Historical data | https://propertydata.lv/data/apartments-for-sale-data/ |

## About

Every night the scraper reads the ss.lv "apartments for sale" listings for each city in
[`config/cities.yaml`](config/cities.yaml) and stores them in that city's own PostgreSQL
database. It then emails a report of new ads and price statistics, and backs the database up to S3.

Cities: Salaspils, Sigulda, Mārupes pagasts, Ādažu novads, Ogre, Jūrmala.

## How it runs

Each city is its own Docker Compose project (`--project-name <city>`) on one EC2 host, with four containers:

| Container | What it does |
|---|---|
| `<city>-db-1` | PostgreSQL 15. Tables `listed_ads`, `removed_ads`, `scrape_runs`. Data in volume `<city>_db_data` |
| `<city>-ws-1` | FastAPI (`/run-task/<city>`, `/status`, `/health`). Runs the pipeline in a background thread: scrape → format → clean → DB → analytics → email (AWS SES) |
| `<city>-ts-1` | Scheduler: calls `/run-task/<city>`, then checks `/status` an hour later and emails an alert if the run failed |
| `<city>-backup-1` | `pg_dump` (15, matching the server) to S3, checked after upload; plus a staleness check |

On the host, a systemd watchdog (`scripts/fleet_watchdog.py`) checks every city's containers,
runs, row counts and backups, and the host's memory and disk. It sends [ntfy](https://ntfy.sh) pushes when a problem
appears or clears.

**Daily schedule (UTC):**

| Time | What |
|---|---|
| 00:40 | `ts` triggers the scrape (`TASK_TIME`) |
| 01:40 | `ts` verifies the run in `/status` (`VERIFY_TIME`) |
| 02:00 | `backup` dumps the DB to `s3://sslv-<env>-<city>-db-backups/db-backups/YYYY/MM/DD/` |
| 06:35 | Watchdog heartbeat push ("fleet OK") |
| 14:00 | `backup` staleness check (newest backup < 26 h) |
| every 15 min | Watchdog check |

The scraper reads every listing page (`get_total_pages()`), fetches details only for ads not
already in the DB, and caps new ads per run at `SCRAPE_URL_LIMIT` (default 500; `0` = no cap).

## Requirements

- An EC2 ARM (aarch64) host with Docker ≥ 25 and Compose v2 (`docker compose`), the AWS CLI, Python 3 and
  `make`. An IAM role must allow reading the CICD bucket, S3 backups and SES.
- For development: Python 3.11 (the images use `python:3.11-slim-bookworm`).

## Configuration

| Where | What |
|---|---|
| `config/cities.yaml` | The city list: key (`ogre`), display name, listing URL, email title |
| `s3://sslv-<env>-m6-cicd-files/.env.prod` | Shared settings: `POSTGRES_PASSWORD`, `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`, `SRC_EMAIL`, `DEST_EMAIL` |
| `s3://sslv-<env>-m6-cicd-files/.env.<city>` | Per city: `CITY`, `CITY_MAIN_URL`, `EMAIL_CITY_TITLE`, `S3_BUCKET` (its `-db-backups` bucket). Optional: `SCRAPE_*`, `TASK_TIME`, `VERIFY_TIME`, `ALERT_*` |
| `s3://sslv-<env>-m6-cicd-files/database.ini` | DB connection for `ws` |

`<env>` is `prod`, `staging` or `dev`. `M6_ENV` must be one of these; `make` lowercases it and
stops on anything else. City buckets use `-` in place of `_`: `sslv-prod-marupes-pag-db-backups`.

The deploy downloads `.env.prod` and `database.ini` fresh on every run, and `.env.<city>` when missing.
`RELEASE_VERSION` and `APP_ENV`, shown in every report email, are set by the deploy: CI passes them in, and a
manual deploy uses `git describe` and the env. Stale values in the env files are ignored.

## Deploy

On the host, from the **one** deploy directory (a git checkout of the release branch):

```bash
git pull --ff-only
make deploy-staging      # or: make deploy-prod
```

`deploy-multi-city-ws.sh` does this for each city in turn:
1. Checks backup age.
2. Builds and starts the city's project with `up -d --build`. Compose replaces only the changed containers, and DB volumes are kept.
3. Triggers `/run-task/<city>` and waits for the result. The city fails the deploy if its run fails or times out.

After the nightly run has succeeded, the trigger is skipped, because `/run-task` runs once a day.

| Variable | Default | Effect |
|---|---|---|
| `POST_DEPLOY_VERIFY` | `true` | `false` skips the post-deploy run |
| `POST_DEPLOY_VERIFY_TIMEOUT` | `1200` | Seconds to wait for each run. A city with a fresh volume fetches every ad and may need more |
| `FAIL_ON_FRESH_VOLUME` | `false` | Fail a city that has no backup at all |

`make undeploy-staging` / `make undeploy-prod` remove the containers and keep the DB volumes. `PURGE_DATA=1` also deletes
the volumes, and asks first.

**From GitHub Actions** (manual only; both refuse to deploy over local changes, during another deploy,
or when the branch moved after the tests):

| Workflow | Runs | Deploys |
|---|---|---|
| `main.yml` | Tests on every push / PR to `main` | **Run workflow** + `confirm = deploy-prod` → tested commit into `~/sslv-prod` |
| `staging.yml` | Tests and builds every image | **Run workflow** + `confirm = deploy-staging` → tested commit into the staging deploy dir |

Keep a single deploy directory per host. The watchdog runs from it, and a second checkout with its own
`docker compose up` would start a second set of containers.

## Monitoring

```bash
make fleet-status M6_ENV=staging            # one report now (read-only)
make watchdog-install M6_ENV=staging        # systemd timers: check every 15 min + 06:35 heartbeat
make watchdog-status                        # timers + recent output
make watchdog-drill M6_ENV=staging          # fire every alert once as [DRILL] pushes and check recovery
```

`watchdog-install` points the systemd units at the directory it is run from, so run it from the
deploy directory. The default ntfy topic for staging is `https://ntfy.sh/staging-sslv-mc-alerts`. Pass
`NTFY_TOPIC_URL=` for other envs; production refuses the staging topic.

## Backup and restore

Nightly backups are made by each city's `backup` container. There is **no** host cron for backups.
`scripts/add_cron.sh` is legacy and would add a second, host-side backup path.

| Command | Effect |
|---|---|
| `make backup-city CITY=ogre M6_ENV=prod` / `make backup-all M6_ENV=prod` | Manual backup to S3. Deletes **no** old backups unless `BACKUP_KEEP_LAST=N` is given |
| `make verify-backup M6_ENV=prod` | Read-only: newest backup per city is fresh and big enough |
| `make test-restore M6_ENV=prod` (`CITY=` for one) | Safe: loads the latest backup into a throwaway `postgres:15` container. **Fails on the first SQL error** |
| `make e2e-backup-restore CITY=ogre M6_ENV=staging` | Fresh backup → S3 check → throwaway restore |
| `make restore-city CITY=ogre M6_ENV=prod` | **Live**: keeps a safety copy, stops the city's writers, replaces the DB in one transaction (any error rolls back), restarts. Asks first |

`scripts/restore_db_city.sh` is the script behind the restore targets:
- `--date YYYY_MM_DD` restores the newest backup of that day.
- `--file <dump>` restores a local dump, such as the safety copy, to undo a restore.
- `--prepare-init` stages a dump for a fresh volume.

Dumps from `pg_dump` 17, taken before the backup image moved to Python 3.11 / bookworm, contain `SET transaction_timeout`, which
Postgres 15 rejects. The restore drops that line automatically.

S3 buckets have no lifecycle rule: backups are kept until deleted. Staging buckets are versioned and prod buckets are not.

## Log collection

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
once). The CICD buckets must never hold scraped data. Upload is refused
outright with `--no-redact`, and skipped if the self-test failed.

**Output:** `log-bundles/sslv-logs-<UTC>/` plus a matching `.tar.gz`:

| Path | Contents |
|---|---|
| `SUMMARY.txt` | **Read this first**: health matrix + last errors per city |
| `MANIFEST.txt` | Full inventory: what was collected, skipped, and why |
| `REDACTION-SELF-TEST.txt` | PASS/FAIL proof that no secret survived |
| `host/` | `docker ps`, images, disk, versions, `deploy-multi-city.log` |
| `cities/<city>/<svc>/` | `logs/`, `artifacts/`, `stdout.log`, `inspect.json`, `health.json`, `config.txt` |

Containers are matched on the compose labels `com.docker.compose.project`
(the city) and `com.docker.compose.service`, never on a name substring, so
cities can never be mixed up. Stopped containers are collected too.

**Secrets.** AWS keys and DB passwords are masked throughout,
and `.env.*` / `database.ini` are recorded by name and mtime only, never read.
A self-test then re-scans the finished bundle, including inside the `.gz`
dump. If anything survives, the run exits `3` and **no archive is created**.

Exit codes: `0` complete · `1` partial · `2` fatal · `3` a secret survived
redaction (do not share the bundle).

> `scripts/collect_logs_v2.sh` is **deprecated**. It predates multi-city and
> collects every city into the same filenames. Use v3.

## Adding a city

One city at a time:

1. Add it to `config/cities.yaml`, e.g. `riga:` with `display_name`, `main_url` and `email_title`.
2. Create its buckets: `make create-m6-bucket M6_CITY=riga M6_ENV=prod M6_PURPOSE=db-backups` (and `scraped-data`).
3. Upload `.env.riga` to `s3://sslv-prod-m6-cicd-files/` with `CITY=riga`, `CITY_MAIN_URL`, `EMAIL_CITY_TITLE` and
   `S3_BUCKET=sslv-prod-riga-db-backups`.
4. Check the scraper against ss.lv: `make verify-scrape CITY=riga`.
5. Deploy: `make deploy-prod`. The new city starts with an empty DB and fetches every ad on its first run.
6. After its first night: `make fleet-status M6_ENV=prod`, then `make test-restore CITY=riga M6_ENV=prod`.

## Development

```bash
make dev-setup     # .venv/ with pytest, coverage, httpx and the ws/ts requirements
make test          # full suite
make test-cov      # with coverage, as CI runs it
```

Shell scripts are tested with stub `aws`/`docker` commands (no AWS or Docker needed), for example
`tests/test_28_*`, `test_32_*`, `test_35_*` and `test_36_*`.

## Legacy single-project stack (M5)

`make setup`, `make build`, `make up`, `make down` and `make logs` still run the old one-city stack
(`docker compose --env-file .env.prod`). Don't use them on a multi-city host. `make down` deletes that
project's DB volume.

## Further reading

- [`docs/RELEASE_2.0.0_action_plan.md`](docs/RELEASE_2.0.0_action_plan.md): the release plan from single-city to multi-city
- [`docs/release-2.0.0_main_merge_inventory.md`](docs/release-2.0.0_main_merge_inventory.md): what the `main` merge kept, ported and dropped
- [`docs/staging_signoff_release-2.0.0.md`](docs/staging_signoff_release-2.0.0.md): staging sign-off status
- [`docs/critical_monitoring_ntfy_plan.md`](docs/critical_monitoring_ntfy_plan.md): monitoring and alerts
- [`docs/M6_phase_1_backup_restore_service_plan.md`](docs/M6_phase_1_backup_restore_service_plan.md): backup and restore design
- [`docs/ROLLBACK_GUIDE.md`](docs/ROLLBACK_GUIDE.md): rollback, written for the single-city stack and to be updated for multi-city (I-5)

## Work in progress

- [ ] Add Streamlit web service to CI/CD
- [ ] Add doc coverage step in CI/CD
