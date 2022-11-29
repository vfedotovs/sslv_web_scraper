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


# Third stage: remote AWS deploy production
build_containers:
	echo "Building containers loaclly ...(not implemented)"

push_to_ECR:
    echo "Tagging and pushing containers to AWS ECR (not implemented)"

deploy_to_AWS_EC2:
	echo "Manually deploying app with terraform to AWS EC2 ...(not implemented)"
