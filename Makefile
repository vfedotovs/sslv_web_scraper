# Used by `image`, `push` & `deploy` targets, override as required


IMAGE_REPO ?= vfedotovsdocker/TBC
IMAGE_TAG ?= 1.2.0


# Don't change:
SRC_DIR := src/ws


.DEFAULT_GOAL := help

help:  ## 💬 This help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

test: venv  ## 🎯 Unit tests for src/ws container
	. $(SRC_DIR)/.venv/bin/activate \
	&& pytest -v

test-report: venv  ## 🎯 Unit tests for ws container (with report output)
	. $(SRC_DIR)/.venv/bin/activate \
	&& pytest -v --junitxml=test-results.xml

run: venv  ## 🏃 Run Fastapi server locally 
	. $(SRC_DIR)/.venv/bin/activate \
	&& python src/app.py


image:  ## 🔨 Build container image from Dockerfile
	docker build . --file build/Dockerfile \
	--tag $(IMAGE_REPO):$(IMAGE_TAG)


push:  ## 📤 Push container image to registry
	docker push $(IMAGE_REPO):$(IMAGE_TAG)


dcup:  ## Run docker-compose up
	docker-compose --env-file .env.prod up -d

dcdown: ## Run docker-compose down
	echo "Running docker compose down ..."
	docker-compose --env-file .env.prod down

build:
	echo "Building and pushing containers to docker hub...(not implemented)"
    
deploy:
	echo "Manually deploying app with terraform to AWS EC2 ...(not implemented)"


clean:  ## 🧹 Clean up project
	rm -rf $(SRC_DIR)/.venv
	rm -rf tests/node_modules
	rm -rf tests/package*
	rm -rf test-results.xml
	rm -rf $(SRC_DIR)/app/__pycache__
	rm -rf $(SRC_DIR)/app/tests/__pycache__
	rm -rf .pytest_cache
	rm -rf $(SRC_DIR)/.pytest_cache

# ============================================================================


venv: $(SRC_DIR)/.venv/touchfile

$(SRC_DIR)/.venv/touchfile: $(SRC_DIR)/requirements.txt
	python3 -m venv $(SRC_DIR)/.venv
	. $(SRC_DIR)/.venv/bin/activate; pip install -Ur $(SRC_DIR)/requirements.txt
	touch $(SRC_DIR)/.venv/touchfile
