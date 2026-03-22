# Setup before start development or local deploy

OS := $(shell uname -s)
ARCH := $(shell uname -m)

ifeq ($(OS), Darwin)
    ifeq ($(ARCH), x86_64)
        default: setup build up down
    else
        default: ec2_setup ec2_build ec2_up ec2_down
    endif
else
    default: ec2_setup ec2_build ec2_up ec2_down
endif



ec2_precheck:
	@echo "Loading envs from AWS Secrets Manager..."
	. ./scripts/set_s3_env_from_aws_sm.sh 
	@if [ -z "$$S3_BUCKET" ]; then \
		echo "[Fail] S3_BUCKET is not exported."; \
		echo "To set env run source scripts/set_s3_env_from_aws_sm.sh"; \
		exit 1; \
	else \
		echo "[Pass] S3_BUCKET is exported."; \
	fi


PG_CONTAINER_NAME := `docker ps | grep db-1 | awk '{print $$NF }'`
S3_BACKUP_BUCKET := `env | grep S3_BUCKET`

.DEFAULT_GOAL := help
.PHONY: precheck build

help:  ## 💬 This help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# Define the precheck function
precheck:  ## checks OS, architecture and if required exports are present
	@echo "=========================================="
	@echo " SSLV Precheck"
	@echo "=========================================="
	@echo ""
	@echo "--- System Detection ---"
	@echo "  OS:           $$(uname -s)"
	@echo "  Architecture: $$(uname -m)"
	@echo "  Kernel:       $$(uname -r)"
	@echo "  Hostname:     $$(hostname)"
	@echo ""
	@if [ "$$(uname -s)" != "Linux" ]; then \
		echo "[WARN] OS is $$(uname -s), expected Linux (EC2 instance)"; \
	else \
		echo "[OK] OS is Linux"; \
	fi
	@if [ "$$(uname -m)" != "aarch64" ]; then \
		echo "[WARN] Architecture is $$(uname -m), expected aarch64 (EC2 ARM)"; \
	else \
		echo "[OK] Architecture is aarch64 (ARM)"; \
	fi
	@if [ -f /sys/devices/virtual/dmi/id/board_asset_tag ]; then \
		EC2_TAG=$$(cat /sys/devices/virtual/dmi/id/board_asset_tag 2>/dev/null); \
		if echo "$$EC2_TAG" | grep -qi "amazon\|ec2\|aws"; then \
			echo "[OK] Running on AWS EC2 instance"; \
		else \
			echo "[WARN] DMI tag found but does not match AWS EC2"; \
		fi; \
	elif curl -s --max-time 2 http://169.254.169.254/latest/meta-data/instance-id > /dev/null 2>&1; then \
		echo "[OK] Running on AWS EC2 instance (metadata reachable)"; \
	else \
		echo "[WARN] Not running on AWS EC2 instance (or metadata not reachable)"; \
	fi
	@echo ""
	@echo "--- Docker Detection ---"
	@if command -v docker > /dev/null 2>&1; then \
		echo "[OK] Docker is installed: $$(docker --version)"; \
	else \
		echo "[FAIL] Docker is not installed"; \
		exit 1; \
	fi
	@if command -v docker compose > /dev/null 2>&1; then \
		echo "[OK] Docker Compose is available: $$(docker compose version)"; \
	elif command -v docker-compose > /dev/null 2>&1; then \
		echo "[WARN] Using legacy docker-compose: $$(docker-compose --version)"; \
	else \
		echo "[FAIL] Docker Compose is not installed"; \
		exit 1; \
	fi
	@echo ""
	@echo "--- Environment Variables ---"
	@if [ -z "$(S3_BACKUP_BUCKET)" ]; then \
		echo "[FAIL] S3_BUCKET is not exported"; \
		echo "       Load envs from AWS Secrets Manager with:"; \
		echo "         source scripts/load_secrets.sh"; \
		exit 1; \
	else \
		echo "[OK] S3_BUCKET is exported"; \
	fi
	@echo ""
	@echo "=========================================="
	@echo " Precheck PASSED"
	@echo "=========================================="

setup: ec2_precheck  ## loads secrets and pulls DB backup file
	@echo "=========================================="
	@echo " SSLV Setup"
	@echo "=========================================="
	@echo ""
	@echo "--- Loading Secrets ---"
	@echo "  Fetching .env.prod and database.ini from S3..."
	@. ./scripts/load_secrets.sh
	@if [ -f .env.prod ]; then \
		echo "[OK] .env.prod downloaded"; \
	else \
		echo "[FAIL] .env.prod not found after download"; \
		exit 1; \
	fi
	@if [ -f database.ini ]; then \
		echo "[OK] database.ini downloaded"; \
	else \
		echo "[FAIL] database.ini not found after download"; \
		exit 1; \
	fi
	@echo ""
	@echo "--- Copying Config Files ---"
	@echo "  Copying database.ini to src/ws/..."
	@cp database.ini src/ws/
	@echo "[OK] database.ini copied to src/ws/"
	@echo ""
	@echo "--- Downloading DB Backup ---"
	@echo "  Fetching latest Postgres backup from $(S3_BACKUP_BUCKET)..."
	@bash scripts/get_last_s3_file.sh
	@if ls *.sql 1> /dev/null 2>&1; then \
		echo "[OK] DB backup downloaded"; \
	else \
		echo "[FAIL] No .sql file found after download"; \
		exit 1; \
	fi
	@echo ""
	@echo "--- Preparing DB Restore ---"
	@echo "  Copying SQL backup to src/db/..."
	@cp *.sql src/db/
	@echo "[OK] SQL backup copied to src/db/"
	@echo "  Backup file:"
	@ls -lh src/db/ | grep sql
	@echo ""
	@echo "=========================================="
	@echo " Setup PASSED"
	@echo "=========================================="


build:  ## builds all containers (ts, ws, db)
	@docker-compose --env-file .env.prod build db
	@docker-compose --env-file .env.prod build ts
	@docker-compose --env-file .env.prod build ws


up:  ## starts all containers
	docker-compose --env-file .env.prod up -d


down:  ## stops all containers
	docker-compose --env-file .env.prod down -v   # removes volumes (clears old PGDATA)

clean:  ## removes setup and DB files and folders
	rm .env.prod
	rm ./src/ws/database.ini
	rm *.sql
	rm ./src/db/pg_backup_*.sql
	bash ./rm_images.sh

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


