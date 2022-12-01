# Setup before start development or local deploy
PG_CONTAINER_NAME := `docker ps | grep db-1 | awk '{print $$11 }'`


.DEFAULT_GOAL := help

help:  ## 💬 This help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

fetch_env_files: ## Fetches locally env files database.ini and .env.prod  
	@cp /Users/vfedotovs/sslv_envs/.env.prod .
	@cp /Users/vfedotovs/sslv_envs/* .

fetch_dump_example: ## Example of fetch Postgres DB dump file form S3 bucket
	@echo "make fetch_dump DB_BACKUP_DATE=2022_11_05"

fetch_dump: DB_BACKUP_DATE ?= 2022_11_01
fetch_dump: ## Fetches DB dump file from S3 bucket
	@aws s3 cp s3://$(S3_BUCKET)/pg_backup_$(DB_BACKUP_DATE).sql .
	@cp pg_backup_$(DB_BACKUP_DATE).sql pg_backup.sql 

fetch_last_db_dump: ## Fetches last Postgres DB dump from AWS S3 bucket
	@python3 get_last_db_backup.py
	@cp *.sql src/db/

compose_db_up: ## Starts DB container
	@docker-compose --env-file .env.prod up db -d

list_db_tables: ## Lists tables sizes in postgres docker allows to test if DB dump was restored correctly 
	@docker exec $(PG_CONTAINER_NAME) psql -U new_docker_user -d new_docker_db -c '\dt+'

compose_up: ## Starts remainig containers 
	@docker-compose --env-file .env.prod up -d

compose_down: ## Stops all containers
	@docker-compose --env-file .env.prod down

test: ## Runs pytests locally
	pytest -v

prune_containers: ## Cleans all docker containers locally
	@docker system prune -a

build_ts: ## Building task_scheduler container
	@docker build -t sslv-dev-ts --file src/ts/Dockerfile .

push_ts: ## Tagging and pushing ts to AWS ECR
	@aws ecr get-login-password --region eu-west-1 | docker login --username AWS --password-stdin $(TS_IMAGE_REPO)
	@docker tag sslv-dev-ts:latest $(TS_IMAGE_REPO)/sslv-dev-ts:latest
	@docker push $(TS_IMAGE_REPO)/sslv-dev-ts:latest

build_db: ## Building db container
	@docker build -t sslv-dev-db --file src/db/Dockerfile .

push_db: ## Tagging and pushing db container to AWS ECR
	@aws ecr get-login-password --region eu-west-1 | docker login --username AWS --password-stdin $(TS_IMAGE_REPO)
	@docker tag sslv-dev-db:latest $(TS_IMAGE_REPO)/sslv-dev-db:latest
	@docker push $(TS_IMAGE_REPO)/sslv-dev-db:latest

build_ws: ## Building web_scraper container
	@docker build -t sslv-dev-ws --file src/ws/Dockerfile .

push_ws: ## Tagging and pushing ws container to AWS ECR
	@aws ecr get-login-password --region eu-west-1 | docker login --username AWS --password-stdin $(TS_IMAGE_REPO)
	@docker tag sslv-dev-ws:latest $(TS_IMAGE_REPO)/sslv-dev-ws:latest
	@docker push $(TS_IMAGE_REPO)/sslv-dev-ws:latest


deploy: ## Deploying app to AWS EC2 ...(not implemented)
	echo "Deploying app to AWS EC2 ...(not implemented)"
