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
.PHONY: precheck build setup clean verify-setup check-backup-age

help:  ## 💬 This help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

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

fetch_dump_example: # Example of fetch specific date DB dump file form S3 bucket
	@echo "make fetch_dump DB_BACKUP_DATE=2022_11_05"

fetch_dump: DB_BACKUP_DATE ?= 2022_11_01
fetch_dump: # Fetches DB dump file from S3 bucket
	@aws s3 cp s3://$(S3_BUCKET)/pg_backup_$(DB_BACKUP_DATE).sql .
	@cp pg_backup_$(DB_BACKUP_DATE).sql src/db/pg_backup.sql 

fetch_last_db_dump: # Fetches last Postgres DB dump from AWS S3 bucket
	@python3 src/db/get_last_db_backup.py
	@cp *.sql src/db/

lt: ## Lists tables sizes to test if DB dump was restored correctly 
	@docker exec $(PG_CONTAINER_NAME) psql -U new_docker_user -d new_docker_db -c '\dt+'

test: precheck ## Runs pytests locally (Not implemented)
	pytest -v

test_cov: precheck ## Runs pytest coverage (Not implemented)
	pytest --cov=.


