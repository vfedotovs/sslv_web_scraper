# S3 Environment Variable Strategy — TODO

This document captures findings from a full codebase audit of S3 bucket usage
and provides a roadmap for making prod/staging independent and supporting
multi-city scaling (1 → 5 cities).

**No code changes yet** — this is a planning reference.

---

## Current State: 3 Buckets, Mixed Strategy

| Bucket | Purpose | How Referenced | Problem |
|--------|---------|----------------|---------|
| `sslv-ws-m5-cicd-files` | CI/CD config (.env.prod, database.ini) | **Hardcoded** in `scripts/load_secrets.sh` | Single env — no staging/prod separation |
| `${S3_BUCKET}` from Secrets Manager | DB backup upload/download | Env var via `sslv_creds.s3_db_backups` | Single value — shared across environments |
| `lambda-ogre-scraped-data` | Lambda scraped data files | **Hardcoded** in `src/ws/app/wsmodules/file_downloader.py` | Single city (Ogre) baked in, no env separation |

### Current Environment Variable Flow

```
AWS Secrets Manager (secret: sslv_creds)
    │
    ├── scripts/load_secrets.sh ──► exports S3_BUCKET, DEST_EMAIL, SRC_EMAIL, RELEASE_VERSION
    ├── scripts/set_s3_env_from_aws_sm.sh ──► exports S3_BUCKET only
    └── scripts/load_secrets_v2.sh ──► same as load_secrets.sh (improved error handling)
            │
            ▼
    docker-compose.yml
    ├── ws: gets AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY (for boto3 in file_downloader.py)
    └── cron: gets S3_BUCKET, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
            │
            ▼
    Containers use os.environ to read values
```

### Current S3 Operations by Component

| Component | File | Operation | Bucket Source |
|-----------|------|-----------|---------------|
| cron | `src/cron/scripts/upload_backup_to_s3.sh` | Upload daily DB backup | `$S3_BUCKET` env var |
| db | `src/db/get_last_db_backup.py` | Download latest DB backup (boto3) | `$S3_BUCKET` env var |
| ws | `src/ws/app/wsmodules/file_downloader.py` | Download Lambda scraped data (boto3) | Hardcoded `lambda-ogre-scraped-data` |
| scripts | `scripts/load_secrets.sh` | Download .env.prod, database.ini | Hardcoded `sslv-ws-m5-cicd-files` |
| scripts | `scripts/get_last_s3_file.sh` | Download latest DB backup (AWS CLI) | `$S3_BUCKET` from Secrets Manager |
| Makefile | `fetch_dump`, `fetch_last_db_dump` targets | Download DB backup | `$S3_BUCKET` env var |
| GitHub Actions | `staging.yml` build job | Download DB backup | `${{ secrets.S3_BUCKET }}` |

---

## Key Issues

### 1. No Environment Isolation
- Prod and staging share the same DB backup bucket
- A staging deploy could restore a prod backup or vice versa
- CI/CD config bucket `sslv-ws-m5-cicd-files` has only prod files
- Single Secrets Manager secret `sslv_creds` — no per-environment values

### 2. City Name Hardcoded Throughout
- `lambda-ogre-scraped-data` bucket name in `file_downloader.py`
- `Ogre-raw-data-report-*` filename patterns in `main.py`
- `CITY_NAME = "Ogre"` constant in `main.py`
- Adding a second city would require code duplication

### 3. Single S3_BUCKET Variable Overloaded
- `S3_BUCKET` is used for DB backups only, but the name is generic
- Lambda data bucket and CI/CD bucket have no env vars at all

---

## Recommended Strategy

### Bucket Naming Convention

```
sslv-{environment}-{purpose}
```

| Purpose | Production | Staging |
|---------|-----------|---------|
| CI/CD config files | `sslv-prod-cicd-files` | `sslv-staging-cicd-files` |
| DB backups | `sslv-prod-db-backups` | `sslv-staging-db-backups` |
| Lambda scraped data | `sslv-prod-lambda-data` | `sslv-staging-lambda-data` |

### New Environment Variables

Replace the single `S3_BUCKET` with three purpose-specific variables:

```bash
S3_CICD_BUCKET=sslv-prod-cicd-files        # .env, database.ini
S3_BACKUP_BUCKET=sslv-prod-db-backups      # pg_dump upload/download
S3_LAMBDA_BUCKET=sslv-prod-lambda-data     # Lambda scraped data
```

### Multi-City: Folder Prefixes (Not Separate Buckets)

Use S3 key prefixes within the same bucket instead of one bucket per city:

```
s3://sslv-prod-lambda-data/
  ├── ogre/Ogre-raw-data-report-2026-03-24T00-40-00.txt
  ├── riga/Riga-raw-data-report-2026-03-24T00-40-00.txt
  ├── jurmala/Jurmala-raw-data-report-2026-03-24T00-40-00.txt
  ├── jelgava/...
  └── liepaja/...

s3://sslv-prod-db-backups/
  ├── ogre/pg_backup_2026_03_24.sql
  ├── riga/pg_backup_2026_03_24.sql
  └── ...
```

A new `CITY_NAME` env var controls which prefix each container instance uses:

```python
# file_downloader.py — before
S3_LAMBDA_BUCKET_NAME = "lambda-ogre-scraped-data"  # hardcoded

# file_downloader.py — after
S3_LAMBDA_BUCKET = os.environ["S3_LAMBDA_BUCKET"]
CITY_NAME = os.environ.get("CITY_NAME", "ogre")
S3_PREFIX = f"{CITY_NAME}/"
```

### Secrets Manager: Per-Environment Secrets

```
Secret: sslv_prod_creds
{
  "s3_cicd_bucket": "sslv-prod-cicd-files",
  "s3_backup_bucket": "sslv-prod-db-backups",
  "s3_lambda_bucket": "sslv-prod-lambda-data",
  "dest_email": "...",
  "src_email": "...",
  "release_version": "..."
}

Secret: sslv_staging_creds
{
  "s3_cicd_bucket": "sslv-staging-cicd-files",
  "s3_backup_bucket": "sslv-staging-db-backups",
  "s3_lambda_bucket": "sslv-staging-lambda-data",
  "dest_email": "...",
  "src_email": "...",
  "release_version": "..."
}
```

---

## Files That Need Code Changes

| File | Current Issue | Change Needed |
|------|--------------|---------------|
| `scripts/load_secrets.sh` | Hardcoded `sslv-ws-m5-cicd-files`, single secret `sslv_creds` | Accept `ENV` param, use `sslv_${ENV}_creds`, read 3 bucket vars |
| `scripts/set_s3_env_from_aws_sm.sh` | Fetches single `s3_db_backups` | Fetch all 3 bucket vars from per-env secret |
| `scripts/load_secrets_v2.sh` | Same as load_secrets.sh | Same changes |
| `scripts/get_last_s3_file.sh` | Uses single `S3_BUCKET` | Use `S3_BACKUP_BUCKET` |
| `src/ws/app/wsmodules/file_downloader.py` | Hardcoded `lambda-ogre-scraped-data` | Read `S3_LAMBDA_BUCKET` + `CITY_NAME` from env |
| `src/ws/app/main.py` | `CITY_NAME = "Ogre"` hardcoded | Read from `CITY_NAME` env var |
| `src/db/get_last_db_backup.py` | Uses `S3_BUCKET` env var | Rename to `S3_BACKUP_BUCKET`, add city prefix |
| `src/cron/scripts/upload_backup_to_s3.sh` | Uses `S3_BUCKET` | Use `S3_BACKUP_BUCKET` + city prefix |
| `docker-compose.yml` | Passes single `S3_BUCKET` to cron | Pass `S3_BACKUP_BUCKET`, `S3_LAMBDA_BUCKET`, `CITY_NAME` |
| `.github/workflows/main.yml` | No env-specific secret selection | Use `sslv_prod_creds` secret ID |
| `.github/workflows/staging.yml` | Same secrets as prod | Use `sslv_staging_creds` secret ID |
| `Makefile` | Single `S3_BUCKET` reference | Support `ENV=prod\|staging` param, use 3 bucket vars |

---

## Implementation Phases

### Phase 1 — Environment Isolation (Do Now)
**Goal:** Prod and staging can run independently without sharing S3 state.

- [ ] Create 6 new S3 buckets (3 per environment) following naming convention
- [ ] Create `sslv_prod_creds` and `sslv_staging_creds` in Secrets Manager
- [ ] Migrate `.env.prod` and `database.ini` to per-env CI/CD buckets
- [ ] Migrate existing DB backups to per-env backup buckets
- [ ] Update `scripts/load_secrets.sh` to accept ENV parameter
- [ ] Update `scripts/set_s3_env_from_aws_sm.sh` to export 3 bucket vars
- [ ] Rename `S3_BUCKET` → `S3_BACKUP_BUCKET` in all files
- [ ] Remove hardcoded `sslv-ws-m5-cicd-files` from load_secrets.sh
- [ ] Remove hardcoded `lambda-ogre-scraped-data` from file_downloader.py
- [ ] Update docker-compose.yml to pass new env vars
- [ ] Update GitHub Actions workflows to use per-env secrets
- [ ] Update GitHub repository secrets (add per-env bucket vars)
- [ ] Update Makefile to support ENV parameter
- [ ] Test staging deployment independently
- [ ] Test production deployment independently

### Phase 2 — Multi-City Support (Before Adding City #2)
**Goal:** Same codebase supports 1–5 cities via configuration only.

- [ ] Add `CITY_NAME` env var to docker-compose.yml
- [ ] Update `file_downloader.py` to use `CITY_NAME` as S3 prefix
- [ ] Update `main.py` to read `CITY_NAME` from env instead of constant
- [ ] Update `upload_backup_to_s3.sh` to include city prefix in backup key
- [ ] Update `get_last_db_backup.py` to filter by city prefix
- [ ] Update Lambda scraper to write to city-prefixed S3 keys
- [ ] Consider separate database per city or shared DB with city column
- [ ] Update analytics and mailer to support per-city reports
- [ ] Test with Ogre as default city (backwards compatible)
- [ ] Add second city and validate full pipeline

### Phase 3 — Automation & Guardrails (Optional)
**Goal:** Prevent accidental cross-environment operations.

- [ ] Add S3 bucket policies restricting prod credentials from staging buckets
- [ ] Add IAM roles per environment instead of shared access keys
- [ ] Add Makefile validation that ENV is set before any S3 operation
- [ ] Consider Terraform/CloudFormation for S3 bucket provisioning

---

## AWS CLI Commands Reference

### Create New Buckets
```bash
# Production
aws s3 mb s3://sslv-prod-cicd-files --region eu-west-1
aws s3 mb s3://sslv-prod-db-backups --region eu-west-1
aws s3 mb s3://sslv-prod-lambda-data --region eu-west-1

# Staging
aws s3 mb s3://sslv-staging-cicd-files --region eu-west-1
aws s3 mb s3://sslv-staging-db-backups --region eu-west-1
aws s3 mb s3://sslv-staging-lambda-data --region eu-west-1
```

### Migrate Existing Data
```bash
# Copy CI/CD files to prod bucket
aws s3 sync s3://sslv-ws-m5-cicd-files s3://sslv-prod-cicd-files
aws s3 cp s3://sslv-prod-cicd-files/.env.prod s3://sslv-staging-cicd-files/.env.staging

# Copy DB backups to prod bucket
aws s3 sync s3://ws-prod-main-db-backups-2025-feb s3://sslv-prod-db-backups

# Copy Lambda data to prod bucket (with city prefix)
aws s3 sync s3://lambda-ogre-scraped-data s3://sslv-prod-lambda-data/ogre/
```

### Create Per-Environment Secrets
```bash
aws secretsmanager create-secret \
  --name sslv_prod_creds \
  --secret-string '{
    "s3_cicd_bucket": "sslv-prod-cicd-files",
    "s3_backup_bucket": "sslv-prod-db-backups",
    "s3_lambda_bucket": "sslv-prod-lambda-data",
    "dest_email": "user@example.com",
    "src_email": "user@example.com",
    "release_version": "1.5.11"
  }'

aws secretsmanager create-secret \
  --name sslv_staging_creds \
  --secret-string '{
    "s3_cicd_bucket": "sslv-staging-cicd-files",
    "s3_backup_bucket": "sslv-staging-db-backups",
    "s3_lambda_bucket": "sslv-staging-lambda-data",
    "dest_email": "user@example.com",
    "src_email": "user@example.com",
    "release_version": "1.5.11-staging"
  }'
```
