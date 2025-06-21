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




# Define the precheck function
precheck:
	@if [ -z "$(S3_BACKUP_BUCKET)" ]; then \
		echo "Error: S3_BACKUP_BUCKET is not not exported."; \
		exit 1; \
	fi
		@if [ -z "$(SENDGRID_API_KEY)" ]; then \
		echo "Error: SENDGRID_API_KEY is not not exported."; \
		exit 1; \
	fi

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
	@if [ -z "$$SENDGRID_API_KEY" ]; then \
		echo "[Fail] SENDGRID_API_KEY is not exported."; \
		echo "To set env run source scripts/set_s3_env_from_aws_sm.sh"; \
		exit 1; \
	else \
		echo "[Pass] SENDGRID_API_KEY is exported."; \
	fi


PG_CONTAINER_NAME := `docker ps | grep db-1 | awk '{print $$NF }'`
S3_BACKUP_BUCKET := `env | grep S3_BUCKET`

.DEFAULT_GOAL := help
.PHONY: precheck build

help:  ## 💬 This help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

all: setup build up ## runs setup, build and up targets

setup: precheck ## gets database.ini and .env.prod and dowloads last DB bacukp file
	@echo "Copying env files from home folder..."
	cp ~/sslv_envs/.env.prod .
	cp ~/sslv_envs/database.ini src/ws/
	@echo "Downloading DB backup file from $(S3_BACKUP_BUCKET)..."
	python3.11 src/db/get_last_db_backup.py
	cp *.sql src/db/
	ls -lh src/db/ | grep sql

ec2_setup: ec2_precheck ## runs ec2 instance setup
	@echo "Started EC2 setup..."
	@echo "Loading secrets from AWS Secrets Manager..."
	. ./scripts/load_secrets.sh
	cp database.ini src/ws/
	@echo "Downloading Postgres DB backup from $(S3_BACKUP_BUCKET)..."
	bash scripts/get_last_s3_file.sh
	@echo "Copying DB backup file to src/db/..."
	cp *.sql src/db/
	@echo "Setup will use following backup file..."
	ls -lh src/db/ | grep sql
	@echo "Completed EC2 setup..."


build: ## builds all containers 
	@docker compose --env-file .env.prod build db
	@docker compose --env-file .env.prod build ts
	@docker compose --env-file .env.prod build ws

ec2_build: ## builds all containers on ec2
	@docker-compose --env-file .env.prod build db
	@docker-compose --env-file .env.prod build ts
	@docker-compose --env-file .env.prod build ws

up: ## starts all containers
	docker compose --env-file .env.prod up -d

ec2_up: ## starts all containers on ec2
	docker-compose --env-file .env.prod up -d

down: ## stops all containers
	docker compose --env-file .env.prod down

ec2_down: ## stops all containers on ec2
	docker-compose --env-file .env.prod down

clean: ## removes setup and DB files and folders
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

test: precheck ## Runs pytests locally
	pytest -v

test_cov: precheck ## Runs pytest coverage report across project
	pytest --cov=.

build_ts: # Building task_scheduler container
	@docker build src/ts -t sslv-dev-ts --file src/ts/Dockerfile

build_db: # Building db container
	@docker build src/db -t sslv-dev-db --file src/db/Dockerfile

build_ws: # Building web_scraper container
	@docker build src/ws -t sslv-dev-ws --file src/ws/Dockerfile

