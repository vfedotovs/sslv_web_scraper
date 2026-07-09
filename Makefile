# Setup before start development or local deploy

OS := $(shell uname -s)
ARCH := $(shell uname -m)
SHELL := /bin/bash

ifeq ($(OS), Darwin)
    ifeq ($(ARCH), x86_64)
        default: setup build up down
    else
        default: ec2_setup ec2_build ec2_up ec2_down
    endif
else
    default: ec2_setup ec2_build ec2_up ec2_down
endif

# Helper function for colored output
# Usage: @printf "$(call log_info,Your message here)\n"
define log_info
\033[36mℹ\033[0m $(1)
endef

define log_success
\033[32m✓\033[0m $(1)
endef

define log_warning
\033[33m⚠\033[0m $(1)
endef

define log_error
\033[31m✗\033[0m $(1)
endef

define log_step
\033[35m▶\033[0m $(1)
endef

# Setup state file for idempotency
SETUP_STATE_FILE := .setup_state
BACKUP_AGE_WARNING_DAYS := 30

ec2_precheck:
	@printf "$(call log_step,Loading envs from AWS Secrets Manager...)\n"
	@set -e; \
	if ! command -v aws >/dev/null 2>&1; then \
		printf "$(call log_error,AWS CLI is not installed. Please install it first.)\n"; \
		exit 1; \
	fi; \
	if ! command -v jq >/dev/null 2>&1; then \
		printf "$(call log_error,jq is not installed. Please install it first.)\n"; \
		exit 1; \
	fi; \
	. ./scripts/set_s3_env_from_aws_sm.sh || { \
		printf "$(call log_error,Failed to load environment from AWS Secrets Manager)\n"; \
		exit 1; \
	}; \
	if [ -z "$$S3_BUCKET" ]; then \
		printf "$(call log_error,S3_BUCKET is not exported.)\n"; \
		printf "$(call log_info,To set env run: source scripts/set_s3_env_from_aws_sm.sh)\n"; \
		exit 1; \
	else \
		printf "$(call log_success,S3_BUCKET is exported: $$S3_BUCKET)\n"; \
	fi


PG_CONTAINER_NAME := `docker ps | grep db-1 | awk '{print $$NF }'`
S3_BACKUP_BUCKET := `env | grep S3_BUCKET`

.DEFAULT_GOAL := help
.PHONY: precheck build setup clean verify-setup check-backup-age create_s3_bucket

help:  ## 💬 This help message
	@grep -E '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# Define the precheck function
precheck:  ## checks if required exports are present
	@printf "$(call log_step,Checking if env S3_BUCKET is exported...)\n"
	@if [ -z "$(S3_BACKUP_BUCKET)" ]; then \
		echo ""; \
		printf "$(call log_error,S3_BUCKET is not exported.)\n"; \
		echo ""; \
		printf "$(call log_info,Option 1: Load environment secrets from AWS Secrets manager with:)\n"; \
		echo "  source scripts/load_secrets.sh"; \
		echo ""; \
		printf "$(call log_info,Option 2: Export manually:)\n"; \
		echo "  export S3_BUCKET='your-bucket-name'"; \
		echo ""; \
		exit 1; \
	fi
	@printf "$(call log_success,env S3_BUCKET is exported)\n"

check-backup-age:  ## verifies backup file is not too old
	@if [ -f src/db/pg_backup_*.sql ]; then \
		BACKUP_FILE=$$(ls -t src/db/pg_backup_*.sql 2>/dev/null | head -1); \
		if [ -n "$$BACKUP_FILE" ]; then \
			BACKUP_DATE=$$(echo $$BACKUP_FILE | grep -o '[0-9]\{4\}_[0-9]\{2\}_[0-9]\{2\}' | head -1); \
			if [ -n "$$BACKUP_DATE" ]; then \
				BACKUP_EPOCH=$$(date -j -f "%Y_%m_%d" "$$BACKUP_DATE" "+%s" 2>/dev/null || echo 0); \
				CURRENT_EPOCH=$$(date "+%s"); \
				AGE_DAYS=$$(( ($$CURRENT_EPOCH - $$BACKUP_EPOCH) / 86400 )); \
				if [ $$AGE_DAYS -gt $(BACKUP_AGE_WARNING_DAYS) ]; then \
					printf "$(call log_warning,Backup file is $$AGE_DAYS days old (threshold: $(BACKUP_AGE_WARNING_DAYS) days))\n"; \
					printf "$(call log_info,Consider fetching a more recent backup)\n"; \
				else \
					printf "$(call log_success,Backup file age: $$AGE_DAYS days (acceptable))\n"; \
				fi; \
			fi; \
		fi; \
	fi

verify-setup:  ## verifies all required setup files exist
	@printf "$(call log_step,Verifying setup files...)\n"
	@MISSING=0; \
	if [ ! -f .env.prod ]; then \
		printf "$(call log_error,Missing: .env.prod)\n"; \
		MISSING=1; \
	fi; \
	if [ ! -f database.ini ]; then \
		printf "$(call log_error,Missing: database.ini)\n"; \
		MISSING=1; \
	fi; \
	if [ ! -f src/ws/database.ini ]; then \
		printf "$(call log_error,Missing: src/ws/database.ini)\n"; \
		MISSING=1; \
	fi; \
	if ! ls src/db/pg_backup_*.sql 1> /dev/null 2>&1; then \
		printf "$(call log_error,Missing: src/db/pg_backup_*.sql)\n"; \
		MISSING=1; \
	fi; \
	if [ $$MISSING -eq 0 ]; then \
		printf "$(call log_success,All setup files are present)\n"; \
		return 0; \
	else \
		printf "$(call log_error,Some setup files are missing)\n"; \
		return 1; \
	fi

setup: ec2_precheck  ## loads secrets and pulls DB backup file
	@printf "$(call log_step,Starting EC2 setup...)\n"
	@set -e; \
	trap 'printf "$(call log_error,Setup failed! Cleaning up...)\n"; $(MAKE) cleanup-on-failure' ERR; \
	\
	if [ -f $(SETUP_STATE_FILE) ]; then \
		printf "$(call log_info,Previous setup detected. Checking if re-setup is needed...)\n"; \
		if $(MAKE) verify-setup 2>/dev/null; then \
			printf "$(call log_success,Setup already completed and verified.)\n"; \
			printf "$(call log_info,To force re-setup run: make clean && make setup)\n"; \
			exit 0; \
		else \
			printf "$(call log_warning,Previous setup incomplete. Re-running setup...)\n"; \
			rm -f $(SETUP_STATE_FILE); \
		fi; \
	fi; \
	\
	printf "$(call log_step,Loading secrets from AWS Secrets Manager...)\n"; \
	. ./scripts/load_secrets.sh || { \
		printf "$(call log_error,Failed to load secrets)\n"; \
		exit 1; \
	}; \
	\
	printf "$(call log_step,Verifying required files downloaded...)\n"; \
	if [ ! -f .env.prod ]; then \
		printf "$(call log_error,Failed to download .env.prod)\n"; \
		exit 1; \
	fi; \
	printf "$(call log_success,.env.prod downloaded)\n"; \
	\
	if [ ! -f database.ini ]; then \
		printf "$(call log_error,Failed to download database.ini)\n"; \
		exit 1; \
	fi; \
	printf "$(call log_success,database.ini downloaded)\n"; \
	\
	printf "$(call log_step,Copying database.ini to src/ws/...)\n"; \
	mkdir -p src/ws; \
	cp database.ini src/ws/ || { \
		printf "$(call log_error,Failed to copy database.ini)\n"; \
		exit 1; \
	}; \
	printf "$(call log_success,database.ini copied to src/ws/)\n"; \
	\
	printf "$(call log_step,Downloading Postgres DB backup from S3...)\n"; \
	bash scripts/get_last_s3_file.sh || { \
		printf "$(call log_error,Failed to download DB backup)\n"; \
		exit 1; \
	}; \
	\
	printf "$(call log_step,Verifying downloaded backup file...)\n"; \
	if ! ls pg_backup_*.sql 1> /dev/null 2>&1; then \
		printf "$(call log_error,No backup file found after download)\n"; \
		exit 1; \
	fi; \
	BACKUP_FILE=$$(ls -t pg_backup_*.sql | head -1); \
	BACKUP_SIZE=$$(stat -f%z "$$BACKUP_FILE" 2>/dev/null || stat -c%s "$$BACKUP_FILE" 2>/dev/null); \
	if [ $$BACKUP_SIZE -lt 1024 ]; then \
		printf "$(call log_error,Backup file too small ($$BACKUP_SIZE bytes) likely corrupted)\n"; \
		exit 1; \
	fi; \
	printf "$(call log_success,Backup file verified: $$BACKUP_FILE ($$(numfmt --to=iec $$BACKUP_SIZE 2>/dev/null || echo $$BACKUP_SIZE bytes)))\n"; \
	\
	printf "$(call log_step,Copying DB backup file to src/db/...)\n"; \
	mkdir -p src/db; \
	cp pg_backup_*.sql src/db/ || { \
		printf "$(call log_error,Failed to copy backup to src/db/)\n"; \
		exit 1; \
	}; \
	printf "$(call log_success,DB backup copied to src/db/)\n"; \
	\
	printf "$(call log_step,Setup files summary:)\n"; \
	ls -lh src/db/ | grep sql || true; \
	\
	printf "$(call log_success,Setup completed successfully!)\n"; \
	echo "$$(date)" > $(SETUP_STATE_FILE); \
	\
	$(MAKE) check-backup-age

cleanup-on-failure:  ## cleanup partial files on setup failure
	@printf "$(call log_step,Cleaning up partial setup files...)\n"
	@rm -f $(SETUP_STATE_FILE)
	@rm -f pg_backup_*.sql 2>/dev/null || true
	@printf "$(call log_info,Cleanup complete. You can retry setup.)\n"


build:  ## builds all containers (ts, ws, db)
	@docker-compose --env-file .env.prod build db
	@docker-compose --env-file .env.prod build ts
	@docker-compose --env-file .env.prod build ws


up:  ## starts all containers
	docker-compose --env-file .env.prod up -d


down:  ## stops all containers
	docker-compose --env-file .env.prod down -v   # removes volumes (clears old PGDATA)

clean:  ## removes setup and DB files and folders
	@printf "$(call log_step,Cleaning up setup files...)\n"
	@rm -f .env.prod && printf "$(call log_success,Removed .env.prod)\n" || printf "$(call log_info,.env.prod not found)\n"
	@rm -f database.ini && printf "$(call log_success,Removed database.ini)\n" || printf "$(call log_info,database.ini not found)\n"
	@rm -f ./src/ws/database.ini && printf "$(call log_success,Removed src/ws/database.ini)\n" || printf "$(call log_info,src/ws/database.ini not found)\n"
	@rm -f *.sql && printf "$(call log_success,Removed *.sql files)\n" || printf "$(call log_info,No .sql files found)\n"
	@rm -f ./src/db/pg_backup_*.sql && printf "$(call log_success,Removed DB backups)\n" || printf "$(call log_info,No DB backups found)\n"
	@rm -f $(SETUP_STATE_FILE) && printf "$(call log_success,Removed setup state file)\n" || printf "$(call log_info,No setup state file found)\n"
	@if [ -f ./rm_images.sh ]; then \
		bash ./rm_images.sh; \
	else \
		printf "$(call log_info,rm_images.sh not found - skipping)\n"; \
	fi
	@printf "$(call log_success,Cleanup completed)\n"

BUCKET_NAME ?= sslv-ogre-city-dev-v1-6-db-backups-2025-11
AWS_REGION ?= us-east-1

# M6 multi-city bucket helpers (recommended for new buckets)
# Usage: make create_m6_bucket CITY=salaspils ENV=prod PURPOSE=db-backups
#   or:  make create_m6_bucket CITY=salaspils ENV=staging PURPOSE=scraped-data
M6_ENV ?= prod
M6_CITY ?= 
M6_PURPOSE ?= db-backups
M6_BUCKET_NAME = sslv-$(M6_ENV)-$(M6_CITY)-$(M6_PURPOSE)

# List of cities and purposes for M6 (derived from config/cities.yaml + plan)
M6_CITIES ?= salaspils sigulda marupes-pag adazu-nov ogre jurmala
M6_PURPOSES ?= db-backups scraped-data
M6_ENVS ?= prod staging dev

create_m6_bucket: ## creates M6-style per-city bucket using M6_ENV, M6_CITY, M6_PURPOSE (e.g. make create_m6_bucket CITY=salaspils ENV=prod PURPOSE=db-backups)
	$(MAKE) create_s3_bucket BUCKET_NAME=sslv-$(M6_ENV)-$(M6_CITY)-$(M6_PURPOSE) AWS_REGION=$(AWS_REGION) M6_ENV=$(M6_ENV) M6_CITY=$(M6_CITY) M6_PURPOSE=$(M6_PURPOSE)

create_s3_bucket:  ## creates new S3 bucket for DB backups (use BUCKET_NAME= and AWS_REGION= to override)
	@printf "$(call log_step,Creating S3 bucket: $(BUCKET_NAME) in region $(AWS_REGION)...)\n"
	@if aws s3 ls s3://$(BUCKET_NAME) 2>/dev/null; then \
		printf "$(call log_warning,Bucket $(BUCKET_NAME) already exists)\n"; \
		exit 1; \
	fi
	@if [ "$(AWS_REGION)" = "us-east-1" ]; then \
		aws s3api create-bucket \
			--bucket $(BUCKET_NAME) \
			--region $(AWS_REGION) || { \
			printf "$(call log_error,Failed to create bucket)\n"; \
			exit 1; \
		}; \
	else \
		aws s3api create-bucket \
			--bucket $(BUCKET_NAME) \
			--region $(AWS_REGION) \
			--create-bucket-configuration LocationConstraint=$(AWS_REGION) || { \
			printf "$(call log_error,Failed to create bucket)\n"; \
			exit 1; \
		}; \
	fi
	@printf "$(call log_success,Bucket created successfully)\n"
	@printf "$(call log_step,Blocking public access...)\n"
	@aws s3api put-public-access-block \
		--bucket $(BUCKET_NAME) \
		--public-access-block-configuration \
		"BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true" || { \
		printf "$(call log_error,Failed to block public access)\n"; \
		exit 1; \
	}
	@printf "$(call log_success,Public access blocked)\n"
	@printf "$(call log_step,Enabling versioning...)\n"
	@aws s3api put-bucket-versioning \
		--bucket $(BUCKET_NAME) \
		--versioning-configuration Status=Enabled || { \
		printf "$(call log_error,Failed to enable versioning)\n"; \
		exit 1; \
	}
	@printf "$(call log_success,Versioning enabled)\n"
	@printf "$(call log_step,Adding lifecycle policy (delete after 90 days)...)\n"
	@aws s3api put-bucket-lifecycle-configuration \
		--bucket $(BUCKET_NAME) \
		--lifecycle-configuration '{ \
			"Rules": [{ \
				"Id": "DeleteOldBackups", \
				"Status": "Enabled", \
				"Filter": {"Prefix": ""}, \
				"Expiration": {"Days": 90} \
			}] \
		}' || { \
		printf "$(call log_error,Failed to set lifecycle policy)\n"; \
		exit 1; \
	}
	@printf "$(call log_success,Lifecycle policy set)\n"
	@printf "$(call log_step,Adding tags...)\n"
	@aws s3api put-bucket-tagging \
		--bucket $(BUCKET_NAME) \
		--tagging 'TagSet=[ \
			{Key=Project,Value=sslv}, \
			{Key=Environment,Value=$(M6_ENV)}, \
			{Key=City,Value=$(M6_CITY)}, \
			{Key=Version,Value=1.6}, \
			{Key=Purpose,Value=$(M6_PURPOSE)}, \
			{Key=CreatedDate,Value=$(shell date +%Y-%m-%d)} \
		]' || { \
		printf "$(call log_error,Failed to add tags)\n"; \
		exit 1; \
	}
	@printf "$(call log_success,Tags added)\n"
	@printf "$(call log_success,S3 bucket $(BUCKET_NAME) created and configured successfully!)\n"
	@printf "$(call log_info,Bucket details:)\n"
	@printf "  - Name: $(BUCKET_NAME)\n"
	@printf "  - Region: $(AWS_REGION)\n"
	@printf "  - Public Access: Blocked\n"
	@printf "  - Versioning: Enabled\n"
	@printf "  - Lifecycle: Delete after 90 days\n"

list_m6_buckets: ## prints all expected M6 bucket names (from M6_ENVS x M6_CITIES x M6_PURPOSES)
	@echo "Expected M6 buckets:"
	@for env in $(M6_ENVS); do \
		for city in $(M6_CITIES); do \
			for purpose in $(M6_PURPOSES); do \
				echo "  sslv-$$env-$$city-$$purpose"; \
			done; \
		done; \
	done

list_existing_m6_buckets: ## lists buckets in AWS that match the M6 naming pattern
	@echo "Existing buckets matching M6 pattern (sslv-{env}-{city}-{purpose}):"
	@aws s3 ls | awk '{print $$3}' | grep -E '^sslv-(prod|staging|dev)-.*-(db-backups|scraped-data)$$' || echo "  (none found or no AWS access)"

tag_existing_bucket: ## applies standard M6 tags to an existing bucket. Use BUCKET_NAME=... or M6_ENV + M6_CITY + M6_PURPOSE
	@if [ -n "$(BUCKET_NAME)" ]; then \
		BUCKET="$(BUCKET_NAME)"; \
		ENV_TAG="$$(echo $$BUCKET | cut -d- -f2)"; \
		CITY_TAG="$$(echo $$BUCKET | cut -d- -f3- | rev | cut -d- -f2- | rev)"; \
		PURPOSE_TAG="$$(echo $$BUCKET | rev | cut -d- -f1 | rev)"; \
	else \
		if [ -z "$(M6_CITY)" ]; then \
			echo "Error: provide BUCKET_NAME=... or M6_CITY=... (with M6_ENV and M6_PURPOSE)"; \
			exit 1; \
		fi; \
		BUCKET="sslv-$(M6_ENV)-$(M6_CITY)-$(M6_PURPOSE)"; \
		ENV_TAG="$(M6_ENV)"; \
		CITY_TAG="$(M6_CITY)"; \
		PURPOSE_TAG="$(M6_PURPOSE)"; \
	fi; \
	echo "Tagging bucket: $$BUCKET"; \
	aws s3api put-bucket-tagging \
		--bucket $$BUCKET \
		--tagging 'TagSet=[ \
			{Key=Project,Value=sslv}, \
			{Key=Environment,Value='$$ENV_TAG'}, \
			{Key=City,Value='$$CITY_TAG'}, \
			{Key=Version,Value=1.6}, \
			{Key=Purpose,Value='$$PURPOSE_TAG'}, \
			{Key=CreatedDate,Value=$(shell date +%Y-%m-%d)} \
		]' || { printf "$(call log_error,Failed to tag $$BUCKET)\n"; exit 1; }; \
	echo "Tags applied to $$BUCKET"

check_m6_bucket: ## checks configuration of a bucket (public access, versioning, etc). Use BUCKET_NAME=...
	@if [ -z "$(BUCKET_NAME)" ]; then \
		echo "Error: BUCKET_NAME=... is required"; \
		exit 1; \
	fi; \
	echo "Checking bucket: $(BUCKET_NAME)"; \
	echo "  Public access block:"; \
	aws s3api get-public-access-block --bucket $(BUCKET_NAME) --query 'PublicAccessBlockConfiguration' --output text 2>/dev/null || echo "    (not set or error)"; \
	echo "  Versioning:"; \
	aws s3api get-bucket-versioning --bucket $(BUCKET_NAME) --query 'Status' --output text 2>/dev/null || echo "    (unknown)"; \
	echo "  Location:"; \
	aws s3api get-bucket-location --bucket $(BUCKET_NAME) --query 'LocationConstraint' --output text 2>/dev/null || echo "    us-east-1"; \
	echo "  Lifecycle rules:"; \
	aws s3api get-bucket-lifecycle-configuration --bucket $(BUCKET_NAME) --query 'Rules[0].Status' --output text 2>/dev/null || echo "    (none or error)"

create_all_m6_buckets: ## creates ALL M6 buckets for ENV (default prod). WARNING: will attempt to create 12 buckets.
	@echo "Creating all M6 buckets for ENV=$(M6_ENV) ..."
	@for city in $(M6_CITIES); do \
		for purpose in $(M6_PURPOSES); do \
			$(MAKE) create_m6_bucket M6_ENV=$(M6_ENV) M6_CITY=$$city M6_PURPOSE=$$purpose || true; \
		done; \
	done
	@echo "Done (some may have been skipped if already existed)."

fetch_dump_example: # Example of fetch specific date DB dump file from S3 bucket
	@echo "make fetch_dump DB_BACKUP_DATE=2026_07_08"
	@echo "make fetch_dump DB_BACKUP_DATE=2026_07_08 CITY=ogre"

fetch_dump: DB_BACKUP_DATE ?= 2022_11_01
fetch_dump: # Fetches DB dump file from S3 bucket. Supports CITY= (e.g. make fetch_dump CITY=ogre)
	@if [ -n "$(CITY)" ]; then \
		city_slug=$$(echo $(CITY) | sed 's/_/-/g'); \
		bucket="sslv-$(M6_ENV)-$$city_slug-db-backups"; \
	else \
		bucket="$(S3_BUCKET)"; \
	fi; \
	echo "Fetching from bucket: $$bucket"; \
	aws s3 cp s3://$$bucket/pg_backup_$(DB_BACKUP_DATE).sql . ; \
	cp pg_backup_$(DB_BACKUP_DATE).sql src/db/ || true

fetch_last_db_dump: # Fetches last Postgres DB dump. Supports CITY= ENV=
	@python3 src/db/get_last_db_backup.py $(if $(CITY),--city $(CITY) --env $(M6_ENV),)
	@cp *.sql src/db/ || true

backup-city: ## run backup for one city (e.g. make backup-city CITY=ogre ENV=prod)
	@./scripts/backup_db_city.sh --city $(CITY) --env $(M6_ENV)

restore-city: ## run restore for one city
	@./scripts/restore_db_city.sh --city $(CITY) --env $(M6_ENV)

backup-all: ## backup all cities for ENV (default prod)
	@./scripts/backup_db_city.sh --all --env $(M6_ENV)

restore-all: ## restore all cities (latest)
	@./scripts/restore_db_city.sh --all --env $(M6_ENV)

verify-backup: ## verify latest backup for CITY (size check, S3 presence, basic health)
	@echo "Basic verification for backup of CITY=$(CITY) ENV=$(M6_ENV)..."
	@./scripts/backup_db_city.sh --city $(CITY) --env $(M6_ENV) 2>&1 | grep -E '(Verifying|size|Verified|Pruned)' || true
	@echo "For full test-restore: use restore with verification step (lists tables)"

test-restore: ## perform sample restore + list tables for verification (uses restore script's built-in verify)
	@echo "Test-restore + verification for CITY=$(CITY)..."
	@./scripts/restore_db_city.sh --city $(CITY) --env $(M6_ENV) 2>&1 | tail -20

e2e-backup-restore: ## End-to-end simulation: backup one city → simulate volume loss → manual restore → verify (item 11)
	@echo "=== E2E for CITY=$(CITY) ENV=$(M6_ENV) ==="
	@echo "1. Backup..."
	@./scripts/backup_db_city.sh --city $(CITY) --env $(M6_ENV)
	@echo "2. Simulate volume loss (would be: docker compose --project-name $(CITY) down -v )"
	@echo "3. Manual restore..."
	@./scripts/restore_db_city.sh --city $(CITY) --env $(M6_ENV)
	@echo "4. Verify (lt)..."
	@echo "(Run 'make lt' or docker exec after real restore to list tables)"
	@echo "E2E simulation complete. See test-restore target for automated verify."

# M6 Multi-city deployment targets
_deploy-precheck:
	@printf "$(call log_step,Running pre-flight checks for multi-city deploy...)\n"
	@bucket="$${CICD_FILES_BUCKET}"; \
	if [ -z "$$bucket" ]; then bucket="sslv-staging-m6-cicd-files"; fi; \
	if [ ! -f deploy-multi-city-ws.sh ]; then \
		printf "$(call log_error,deploy-multi-city-ws.sh not found)\n"; \
		exit 1; \
	fi; \
	if [ ! -x deploy-multi-city-ws.sh ]; then \
		printf "$(call log_warning,Making deploy-multi-city-ws.sh executable...)\n"; \
		chmod +x deploy-multi-city-ws.sh; \
	fi; \
	if ! command -v aws >/dev/null 2>&1; then \
		printf "$(call log_error,AWS CLI is required (to fetch .env.* files from CICD bucket))\n"; \
		exit 1; \
	fi; \
	if ! command -v docker >/dev/null 2>&1; then \
		printf "$(call log_error,Docker is required)\n"; \
		exit 1; \
	fi; \
	if ! docker compose version >/dev/null 2>&1 && ! command -v docker-compose >/dev/null 2>&1; then \
		printf "$(call log_error,Neither 'docker compose' nor 'docker-compose' found)\n"; \
		exit 1; \
	fi; \
	if [ ! -f config/cities.yaml ]; then \
		printf "$(call log_error,config/cities.yaml not found)\n"; \
		exit 1; \
	fi; \
	printf "$(call log_step,Checking access to CICD bucket: $$bucket ...)\n"; \
	if aws s3 ls "s3://$$bucket/" --max-items 1 > /dev/null 2>&1; then \
		printf "$(call log_success,CICD bucket $$bucket is accessible)\n"; \
	else \
		printf "$(call log_warning,Cannot access s3://$$bucket/ (this is OK if .env.* files already exist locally))\n"; \
		if ! ls .env.* 1>/dev/null 2>&1; then \
			printf "$(call log_error,No local .env.* files found and cannot reach CICD bucket.)\n"; \
			printf "$(call log_info,Run with AWS credentials that can access the bucket, or place .env.* files locally first.)\n"; \
			exit 1; \
		fi; \
	fi; \
	printf "$(call log_success,Pre-flight checks passed)\n"

deploy-staging: ## runs ./deploy-multi-city-ws.sh configured for staging
	@CICD_FILES_BUCKET=sslv-staging-m6-cicd-files M6_ENV=staging $(MAKE) _deploy-precheck
	@printf "$(call log_step,Deploying all cities to staging...)\n"
	@printf "$(call log_info,Command: CICD_FILES_BUCKET=sslv-staging-m6-cicd-files M6_ENV=staging ./deploy-multi-city-ws.sh)\n"
	CICD_FILES_BUCKET=sslv-staging-m6-cicd-files M6_ENV=staging ./deploy-multi-city-ws.sh

deploy-prod: ## runs ./deploy-multi-city-ws.sh configured for production
	@CICD_FILES_BUCKET=sslv-prod-m6-cicd-files M6_ENV=prod $(MAKE) _deploy-precheck
	@printf "$(call log_step,Deploying all cities to production...)\n"
	@printf "$(call log_info,Command: CICD_FILES_BUCKET=sslv-prod-m6-cicd-files M6_ENV=prod ./deploy-multi-city-ws.sh)\n"
	CICD_FILES_BUCKET=sslv-prod-m6-cicd-files M6_ENV=prod ./deploy-multi-city-ws.sh

lt: ## Lists tables sizes to test if DB dump was restored correctly 
	@docker exec $(PG_CONTAINER_NAME) psql -U new_docker_user -d new_docker_db -c '\dt+'

test: precheck ## Runs pytests locally (Not implemented)
	pytest -v

test_cov: precheck ## Runs pytest coverage (Not implemented)
	pytest --cov=.


verify-scrape: ## Phase 3 Item 10 - verify dynamic page count + city naming for CITY (default jurmala)
	@CITY=$${CITY:-jurmala} ./scripts/verify_city_scrape.sh $${CITY}

verify-scrape-all: ## Run verification for several cities (jurmala, ogre, sigulda)
	@for c in jurmala ogre sigulda; do \
	  echo "=== Verifying $$c ==="; \
	  CITY=$$c ./scripts/verify_city_scrape.sh $$c || true; \
	  echo; \
	done
