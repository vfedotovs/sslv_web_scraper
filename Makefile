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
