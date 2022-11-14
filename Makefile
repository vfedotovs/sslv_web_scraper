# Setup before start development or local deploy
PG_CONTAINER_NAME := `docker ps | grep db-1 | awk '{print $$11 }'`


fetch_env_files:
	@cp /Users/vfedotovs/sslv_envs/.env.prod .
	@cp /Users/vfedotovs/sslv_envs/* .

fetch_dump_example:
	@echo "make fetch_dump DB_BACKUP_DATE=2022_11_05"

fetch_dump: DB_BACKUP_DATE ?= 2022_11_01
fetch_dump:
	@aws s3 cp s3://$(S3_BUCKET)/pg_backup_$(DB_BACKUP_DATE).sql .
	@cp pg_backup_$(DB_BACKUP_DATE).sql pg_backup.sql 

list_tables:
	@docker exec $(PG_CONTAINER_NAME) psql -U new_docker_user -d new_docker_db -c '\dt+'


# Stage: before local deploy test
test:
	pytest -v

# Stage: local deploy for preprod testing  
clean:
	@docker system prune -a

compose_db_up:
	@docker-compose --env-file .env.prod up db -d

compose_up:
	@docker-compose --env-file .env.prod up -d

compose_down:
	@docker-compose --env-file .env.prod down


# Third stage: remote AWS deploy production

build:
	echo "Building and pushing containers to docker hub...(not implemented)"

deploy:
	echo "Manually deploying app with terraform to AWS EC2 ...(not implemented)"
