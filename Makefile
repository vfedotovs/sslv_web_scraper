# Setup before start development or local deploy

# Define the precheck function
precheck:
	@if [ -z "$(AWS_ACCESS_KEY_ID)" ]; then \
		echo "Error: AWS_ACCESS_KEY_ID is not exported."; \
		exit 1; \
	fi
	@if [ -z "$(AWS_SECRET_ACCESS_KEY)" ]; then \
		echo "Error: AWS_SECRET_ACCESS_KEY is not exported."; \
		exit 1; \
	fi
	@if [ -z "$(S3_BACKUP_BUCKET)" ]; then \
		echo "Error: S3_BACKUP_BUCKET is not not exported."; \
		exit 1; \
	fi
	@if [ -z "$(RELEASE_VERSION)" ]; then \
		echo "Error: RELEASE_VERSION is not not exported."; \
		exit 1; \
	fi
		@if [ -z "$(SENDGRID_API_KEY)" ]; then \
		echo "Error: SENDGRID_API_KEY is not not exported."; \
		exit 1; \
	fi



PG_CONTAINER_NAME := `docker ps | grep db-1 | awk '{print $$NF }'`
S3_BACKUP_BUCKET := `env | grep S3_BUCKET`

.DEFAULT_GOAL := help





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


build: ## builds all containers 
	@docker-compose --env-file .env.prod build db
	@docker-compose --env-file .env.prod build ts
	@docker-compose --env-file .env.prod build ws
	@docker-compose --env-file .env.prod build web

up: ## starts all containers
	docker-compose --env-file .env.prod up -d

down: ## stops all containers
	docker-compose --env-file .env.prod down

clean: ## removes setup and DB files and folders
	rm .env.prod
	rm ./src/ws/database.ini
	rm *.sql
	rm ./src/db/pg_backup_*.sql

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

push_ts: # Tagging and pushing ts to AWS ECR
	@aws ecr get-login-password --region eu-west-1 | docker login --username AWS --password-stdin $(TS_IMAGE_REPO)
	@docker tag sslv-dev-ts:latest $(TS_IMAGE_REPO)/sslv-dev-ts:latest
	@docker push $(TS_IMAGE_REPO)/sslv-dev-ts:latest

build_db: # Building db container
	@docker build src/db -t sslv-dev-db --file src/db/Dockerfile

push_db: # Tagging and pushing db container to AWS ECR
	@aws ecr get-login-password --region eu-west-1 | docker login --username AWS --password-stdin $(TS_IMAGE_REPO)
	@docker tag sslv-dev-db:latest $(TS_IMAGE_REPO)/sslv-dev-db:latest
	@docker push $(TS_IMAGE_REPO)/sslv-dev-db:latest

build_ws: # Building web_scraper container
	@docker build src/ws -t sslv-dev-ws --file src/ws/Dockerfile

push_ws: # Tagging and pushing ws container to AWS ECR
	@aws ecr get-login-password --region eu-west-1 | docker login --username AWS --password-stdin $(TS_IMAGE_REPO)
	@docker tag sslv-dev-ws:latest $(TS_IMAGE_REPO)/sslv-dev-ws:latest
	@docker push $(TS_IMAGE_REPO)/sslv-dev-ws:latest


deploy: # Deploying app to AWS EC2 ...(not implemented)
	echo "Deploying app to AWS EC2 ...(not implemented)"
