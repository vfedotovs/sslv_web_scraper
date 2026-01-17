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
.PHONY: precheck build setup-venv clean-venv test-venv

# Virtual environment settings
VENV_DIR := .venv
PYTHON := $(VENV_DIR)/bin/python
PIP := $(VENV_DIR)/bin/pip
PYTEST := $(VENV_DIR)/bin/pytest

help:  ## 💬 This help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

setup-venv:  ## 🐍 Setup Python virtual environment using uv with pytest and pytest-cov
	@echo "Setting up Python virtual environment with uv..."
	@if ! command -v uv &> /dev/null; then \
		echo "❌ Error: uv is not installed"; \
		echo "Install uv with: curl -LsSf https://astral.sh/uv/install.sh | sh"; \
		echo "Or with pip: pip install uv"; \
		exit 1; \
	fi
	@echo "✅ uv found: $$(uv --version)"
	@if [ -d "$(VENV_DIR)" ]; then \
		echo "⚠️  Virtual environment already exists at $(VENV_DIR)"; \
		echo "Run 'make clean-venv' to remove it first"; \
	else \
		echo "Creating virtual environment at $(VENV_DIR)..."; \
		uv venv $(VENV_DIR); \
		echo "✅ Virtual environment created"; \
		echo "Installing pytest and pytest-cov..."; \
		uv pip install --python $(PYTHON) pytest pytest-cov; \
		echo "✅ pytest and pytest-cov installed"; \
		echo ""; \
		echo "Virtual environment setup complete!"; \
		echo ""; \
		echo "To activate the virtual environment:"; \
		echo "  source $(VENV_DIR)/bin/activate"; \
		echo ""; \
		echo "Installed packages:"; \
		$(PIP) list; \
	fi

clean-venv:  ## 🧹 Remove Python virtual environment
	@echo "Removing virtual environment..."
	@if [ -d "$(VENV_DIR)" ]; then \
		rm -rf $(VENV_DIR); \
		echo "✅ Virtual environment removed"; \
	else \
		echo "⚠️  No virtual environment found at $(VENV_DIR)"; \
	fi

test-venv:  ## 🧪 Run tests using the virtual environment
	@if [ ! -d "$(VENV_DIR)" ]; then \
		echo "❌ Virtual environment not found. Run 'make setup-venv' first"; \
		exit 1; \
	fi
	@echo "Running tests with pytest..."
	$(PYTEST) -v

test-cov-venv:  ## 📊 Run tests with coverage using the virtual environment
	@if [ ! -d "$(VENV_DIR)" ]; then \
		echo "❌ Virtual environment not found. Run 'make setup-venv' first"; \
		exit 1; \
	fi
	@echo "Running tests with coverage..."
	$(PYTEST) --cov=. --cov-report=term-missing --cov-report=html

install-dev:  ## 📦 Install development dependencies in virtual environment
	@if [ ! -d "$(VENV_DIR)" ]; then \
		echo "❌ Virtual environment not found. Run 'make setup-venv' first"; \
		exit 1; \
	fi
	@echo "Installing development dependencies..."
	@if [ -f "requirements-dev.txt" ]; then \
		uv pip install --python $(PYTHON) -r requirements-dev.txt; \
		echo "✅ Development dependencies installed"; \
	else \
		echo "⚠️  requirements-dev.txt not found, installing common dev tools..."; \
		uv pip install --python $(PYTHON) black flake8 mypy isort pylint; \
		echo "✅ Common development tools installed"; \
	fi

venv-info:  ## ℹ️  Show virtual environment information
	@if [ -d "$(VENV_DIR)" ]; then \
		echo "Virtual environment: $(VENV_DIR)"; \
		echo "Python: $$($(PYTHON) --version)"; \
		echo ""; \
		echo "Installed packages:"; \
		$(PIP) list; \
	else \
		echo "❌ No virtual environment found at $(VENV_DIR)"; \
		echo "Run 'make setup-venv' to create one"; \
	fi

# Define the precheck function
precheck:  ## checks if required exports are present 
	@echo "Checking if env S3_BUCKET is exported...";
	@if [ -z "$(S3_BACKUP_BUCKET)" ]; then \
		echo "Error: S3_BUCKET is not not exported."; \
		echo "Load envs from AWS Secrets manager with:"; \
		echo "source scripts/load_secrets.sh"; \
		echo "Alternatively export manually:"; \
		exit 1; \
	fi
		@echo "[OK] env S3_BUCKET is exported...";
		@echo "Checking if env SENDGRID_API_KEY is exported...";
		@if [ -z "$(SENDGRID_API_KEY)" ]; then \
		echo "Error: SENDGRID_API_KEY is not not exported."; \
		echo "Load envs from AWS Secrets manager with:"; \
		echo "source scripts/load_secrets.sh"; \
		echo "Alternatively export manually:"; \
		exit 1; \
	fi
	@echo "[OK] env SENDGRID_API_KEY is exported...";

setup: ec2_precheck  ## loads secrets and pulls DB backup file
	## loads secrets, downloads DB backup from AWS S3
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
	@echo "[OK] Seetup is completed..."


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


