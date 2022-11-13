check_vars:
	@test -n "$(S3_BUCKET)" || (echo "You need to set S3_BUCKET environment variable in .zshrc" >&2 && exit 1)
	@test -n "$(PG_BACKUP_FILE)" || (echo "You need to set PG_BACKUP_FILE environment variable" >&2 && exit 1)
	@test -n "$(DB_CONTAINER_NAME)" || (echo "You need to set DB_CONTANER_NAME environment variable" >&2 && exit 1)
	@test -n "$(AWS_EC2_IP)" || (echo "You need to set AWS_EC2_IP environment variable" >&2 && exit 1)

list_vars:
	@echo ""
	@echo "S3 Bucket name  : $(S3_BUCKET)"
	@echo "DB Continer name: $(DB_CONTAINER_NAME)"
	@echo "AWS EC2 IP      : $(AWS_EC2_IP)"

getenvs:
	@cp /Users/vfedotovs/sslv_envs/.env.prod .
	@cp /Users/vfedotovs/sslv_envs/* .

fetch_dump_example:
	@echo "make fetch_dump DB_BACKUP_DATE=2022_11_05"

fetch_dump: DB_BACKUP_DATE ?= 2022_11_01
fetch_dump:
	@aws s3 cp s3://$(S3_BUCKET)/pg_backup_$(DB_BACKUP_DATE).sql .


composeupdb:
	@docker-compose --env-file .env.prod up -d db

migratedb: DB_NAME ?= v151_221113-db-1
migratedb: DB_BACKUP_DATE ?= 2022_11_13
migratedb:
	@cat  pg_backup_2022_11_13.sql | docker exec -i v151_221113-db-1  -U new_docker_user -d new_docker_db

# First stage: before local deploy test

test:
	pytest -v

lint:
	flake8

# Second stage: local deploy for preprod testing  

clean:
	docker system prune -a

dps:
	docker ps

dcup:
	echo "Running docker compose up ..."
	docker-compose --env-file .env.prod up -d

dcdown:
	echo "Running docker compose down ..."
	docker-compose --env-file .env.prod down


# Third stage: remote AWS deploy production

build:
	echo "Building and pushing containers to docker hub...(not implemented)"

deploy:
	echo "Manually deploying app with terraform to AWS EC2 ...(not implemented)"
