# =============================================================================
# SSLV multi-city web scraper — Makefile
#
#   make            show this help (grouped by category)
#   make help       same
#
# Layout
#   1. Configuration     variables you can override: make <target> VAR=value
#   2. Helpers           colored output + safety guards used by recipes
#   3. Targets, one "##@" section per category (most-used first):
#        Deploy · Monitoring & alerts · Diagnostics · Backup & restore ·
#        AWS S3 buckets · Tests · Legacy single-project (M5)
#
# Conventions
#   - "## text" after a target  -> listed by `make help`
#   - "##@ Title" line          -> starts a section in `make help`
#   - targets without "##" or starting with "_" are internal helpers
#   - every command target is .PHONY (declared next to its section)
# =============================================================================

# =============================================================================
# 1. Configuration
# =============================================================================

SHELL := /bin/bash
OS := $(shell uname -s)
ARCH := $(shell uname -m)

# Deployment environment for bucket names, backups and alerts: prod | staging | dev
M6_ENV ?= prod
# Single city for per-city targets (backup-city, restore-city, collect-logs, ...)
# CITY ?=            (no default; required where noted)

# S3 bucket helpers (see "AWS S3 buckets")
BUCKET_NAME ?= sslv-ogre-city-dev-v1-6-db-backups-2025-11
AWS_REGION ?= us-east-1
M6_CITY ?= 
M6_PURPOSE ?= db-backups
M6_BUCKET_NAME = sslv-$(M6_ENV)-$(M6_CITY)-$(M6_PURPOSE)
# Bucket matrix for list/create helpers (city slugs use '-', derived from config/cities.yaml)
M6_CITIES ?= salaspils sigulda marupes-pag adazu-nov ogre jurmala
M6_PURPOSES ?= db-backups scraped-data
M6_ENVS ?= prod staging dev

# Watchdog ntfy alerts (see "Monitoring & alerts")
NTFY_STAGING_TOPIC_URL := https://ntfy.sh/staging-sslv-mc-alerts
NTFY_TOPIC_URL ?= $(NTFY_STAGING_TOPIC_URL)
WATCHDOG_UNITS := sslv-watchdog.service sslv-watchdog.timer sslv-watchdog-heartbeat.service sslv-watchdog-heartbeat.timer

# Legacy single-project flow (see "Legacy single-project")
SETUP_STATE_FILE := .setup_state
BACKUP_AGE_WARNING_DAYS := 30
PG_CONTAINER_NAME := `docker ps | grep db-1 | awk '{print $$NF }'`
S3_BACKUP_BUCKET := `env | grep S3_BUCKET`

.DEFAULT_GOAL := help

# =============================================================================
# 2. Helpers
# =============================================================================

# Colored output. Usage: @printf "$(call log_info,Your message here)\n"
define log_info
\033[36mℹ\033[0m $(1)
endef

define log_success
\033[32m✓\033[0m $(1)
endef

define log_warning
\033[33m⚠\033[0m $(1)
endef

define log_error
\033[31m✗\033[0m $(1)
endef

define log_step
\033[35m▶\033[0m $(1)
endef

# Refuse to point a non-staging env at the staging topic.
define ntfy_topic_guard
	@if [ "$(M6_ENV)" != "staging" ] && [ "$(NTFY_TOPIC_URL)" = "$(NTFY_STAGING_TOPIC_URL)" ]; then \
		printf "$(call log_error,M6_ENV=$(M6_ENV) would push to the staging topic. Pass M6_ENV=staging or NTFY_TOPIC_URL=<topic for $(M6_ENV)>.)\n"; \
		exit 1; \
	fi
endef

# Undeploying makes every watchdog check fail; stop the timers so it does not
# page for an intentional outage. They stay enabled and come back on reboot.
define watchdog_timers_stop
	@if systemctl is-active --quiet sslv-watchdog.timer 2>/dev/null \
		|| systemctl is-active --quiet sslv-watchdog-heartbeat.timer 2>/dev/null; then \
		printf "$(call log_info,Stopping watchdog timers (resume after deploy: sudo systemctl start sslv-watchdog.timer sslv-watchdog-heartbeat.timer))\n"; \
		sudo systemctl stop sslv-watchdog.timer sslv-watchdog-heartbeat.timer; \
	fi
endef

# =============================================================================
# 3. Targets
# =============================================================================

##@ Help

.PHONY: help

help:  ## Show this help, grouped by category
	@awk 'BEGIN {FS = ":.*## "} \
		/^##@ / {printf "\n\033[1m%s\033[0m\n", substr($$0, 5); next} \
		/^[a-zA-Z0-9_-]+:.*## / {printf "  \033[36m%-26s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

##@ Deploy (multi-city)
# Day-to-day lifecycle of the 6-city fleet on one host (config/cities.yaml).
# Every city is its own compose project: <city>-db-1 / -ws-1 / -ts-1 / -backup-1.
# deploy-* fetch .env.prod, database.ini and .env.<city> from the env's CICD
# bucket. undeploy-* keep each city's DB volume unless PURGE_DATA=1.

.PHONY: deploy-staging deploy-prod undeploy-staging undeploy-prod clean-containers _deploy-precheck

deploy-staging: ## deploy all cities to staging (sslv-staging-m6-cicd-files)
	@CICD_FILES_BUCKET=sslv-staging-m6-cicd-files M6_ENV=staging $(MAKE) _deploy-precheck
	@printf "$(call log_step,Deploying all cities to staging...)\n"
	@printf "$(call log_info,Command: CICD_FILES_BUCKET=sslv-staging-m6-cicd-files M6_ENV=staging ./deploy-multi-city-ws.sh)\n"
	CICD_FILES_BUCKET=sslv-staging-m6-cicd-files M6_ENV=staging ./deploy-multi-city-ws.sh

deploy-prod: ## deploy all cities to production (sslv-prod-m6-cicd-files)
	@CICD_FILES_BUCKET=sslv-prod-m6-cicd-files M6_ENV=prod $(MAKE) _deploy-precheck
	@printf "$(call log_step,Deploying all cities to production...)\n"
	@printf "$(call log_info,Command: CICD_FILES_BUCKET=sslv-prod-m6-cicd-files M6_ENV=prod ./deploy-multi-city-ws.sh)\n"
	CICD_FILES_BUCKET=sslv-prod-m6-cicd-files M6_ENV=prod ./deploy-multi-city-ws.sh

undeploy-staging: ## remove all city containers on staging; keeps DB volumes (PURGE_DATA=1 deletes them, asks first)
	$(watchdog_timers_stop)
	M6_ENV=staging ./undeploy-multi-city.sh $(if $(filter 1 true yes,$(PURGE_DATA)),--purge-data)

undeploy-prod: ## remove all city containers on production; keeps DB volumes (PURGE_DATA=1 deletes them, asks first)
	$(watchdog_timers_stop)
	M6_ENV=prod ./undeploy-multi-city.sh $(if $(filter 1 true yes,$(PURGE_DATA)),--purge-data)

clean-containers: ## force-remove city containers + networks by compose label; keeps volumes/images (CITIES="a b")
	$(watchdog_timers_stop)
	@cities="$(CITIES)"; \
	if [ -z "$$cities" ]; then source scripts/lib/cities.sh; cities=$$(parse_cities config/cities.yaml); fi; \
	for city in $$cities; do \
		ids=$$(docker ps -aq --filter "label=com.docker.compose.project=$$city"); \
		if [ -n "$$ids" ]; then \
			docker rm -f $$ids > /dev/null && printf "$(call log_success,$$city: removed $$(echo $$ids | wc -w | tr -d ' ') container(s))\n"; \
		else \
			printf "$(call log_info,$$city: no containers)\n"; \
		fi; \
		nets=$$(docker network ls -q --filter "label=com.docker.compose.project=$$city"); \
		if [ -n "$$nets" ]; then docker network rm $$nets > /dev/null; fi; \
	done; \
	printf "$(call log_success,Containers removed; DB volumes kept (docker volume ls | grep _db_data))\n"

# Internal: tool + CICD bucket pre-flight shared by deploy-staging / deploy-prod.
_deploy-precheck:
	@printf "$(call log_step,Running pre-flight checks for multi-city deploy...)\n"
	@bucket="$${CICD_FILES_BUCKET}"; \
	if [ -z "$$bucket" ]; then bucket="sslv-staging-m6-cicd-files"; fi; \
	if [ ! -f deploy-multi-city-ws.sh ]; then \
		printf "$(call log_error,deploy-multi-city-ws.sh not found)\n"; \
		exit 1; \
	fi; \
	if [ ! -x deploy-multi-city-ws.sh ]; then \
		printf "$(call log_warning,Making deploy-multi-city-ws.sh executable...)\n"; \
		chmod +x deploy-multi-city-ws.sh; \
	fi; \
	if ! command -v aws >/dev/null 2>&1; then \
		printf "$(call log_error,AWS CLI is required (to fetch .env.* files from CICD bucket))\n"; \
		exit 1; \
	fi; \
	if ! command -v docker >/dev/null 2>&1; then \
		printf "$(call log_error,Docker is required)\n"; \
		exit 1; \
	fi; \
	if ! docker compose version >/dev/null 2>&1 && ! command -v docker-compose >/dev/null 2>&1; then \
		printf "$(call log_error,Neither 'docker compose' nor 'docker-compose' found)\n"; \
		exit 1; \
	fi; \
	if [ ! -f config/cities.yaml ]; then \
		printf "$(call log_error,config/cities.yaml not found)\n"; \
		exit 1; \
	fi; \
	printf "$(call log_step,Checking access to CICD bucket: $$bucket ...)\n"; \
	# Probe using direct object fetch first (aws s3 cp of a known key only needs s3:GetObject; \
	# does not require s3:ListBucket which root 'ls' does). Falls back to ls for compatibility. \
	if aws s3 cp "s3://$$bucket/.env.prod" /tmp/.probe-env.prod.$$$$ --quiet 2>/dev/null; then \
		rm -f /tmp/.probe-env.prod.$$$$ 2>/dev/null || true; \
		printf "$(call log_success,CICD bucket $$bucket is accessible (via GetObject))\n"; \
	elif aws s3 cp "s3://$$bucket/database.ini" /tmp/.probe-db.$$$$ --quiet 2>/dev/null; then \
		rm -f /tmp/.probe-db.$$$$ 2>/dev/null || true; \
		printf "$(call log_success,CICD bucket $$bucket is accessible (via GetObject))\n"; \
	elif aws s3 ls "s3://$$bucket/" --max-items 1 > /dev/null 2>&1; then \
		printf "$(call log_success,CICD bucket $$bucket is accessible)\n"; \
	else \
		printf "$(call log_warning,Cannot access s3://$$bucket/ (this is OK if .env.* or .env.prod files already exist locally))\n"; \
		if ! ls .env.* .env.prod 1>/dev/null 2>&1; then \
			printf "$(call log_error,No local .env.* / .env.prod files found and cannot reach CICD bucket.)\n"; \
			printf "$(call log_info,Run with AWS credentials/IAM that can GetObject (or ListBucket) the bucket, or place .env.* + .env.prod locally first.)\n"; \
			exit 1; \
		fi; \
	fi; \
	printf "$(call log_success,Pre-flight checks passed)\n"

##@ Monitoring & alerts
# fleet_watchdog.py checks containers, last runs, DB rows, S3 backups, memory,
# OOM kills and disk (docs/critical_monitoring_ntfy_plan.md). fleet-status is a
# read-only report; watchdog-* manage the systemd timers that push to ntfy.
# Pass M6_ENV=staging on staging: the staging topic is refused for other envs.

.PHONY: fleet-status watchdog-install watchdog-status watchdog-test-ntfy watchdog-drill watchdog-uninstall

fleet-status: ## print the watchdog report once: containers, runs, DB rows, backups, host (read-only, M6_ENV=)
	@python3 scripts/fleet_watchdog.py --email-mode never --env $(M6_ENV)

watchdog-install: ## install ntfy alert timers: every 15 min + daily heartbeat (M6_ENV=, NTFY_TOPIC_URL=, HEARTBEAT_PING_URL=)
	$(ntfy_topic_guard)
	@printf "$(call log_step,Writing /etc/sslv-watchdog.env (ENV=$(M6_ENV), topic $(NTFY_TOPIC_URL))...)\n"
	@{ printf 'ENV=%s\nNTFY_TOPIC_URL=%s\n' "$(M6_ENV)" "$(NTFY_TOPIC_URL)"; \
		if [ -n "$(HEARTBEAT_PING_URL)" ]; then printf 'HEARTBEAT_PING_URL=%s\n' "$(HEARTBEAT_PING_URL)"; fi; \
	} | sudo tee /etc/sslv-watchdog.env > /dev/null
	@sudo chmod 600 /etc/sslv-watchdog.env
	@for unit in $(WATCHDOG_UNITS); do \
		sed -e "s|@REPO_DIR@|$(CURDIR)|" -e "s|@USER@|$$(id -un)|" scripts/systemd/$$unit \
			| sudo tee /etc/systemd/system/$$unit > /dev/null; \
	done
	@sudo systemctl daemon-reload
	@sudo systemctl enable --now sslv-watchdog.timer sslv-watchdog-heartbeat.timer
	@printf "$(call log_success,Watchdog timers installed. Check with: make watchdog-status)\n"

watchdog-status: ## show watchdog timers and recent run output
	@systemctl list-timers 'sslv-watchdog*' --all
	@journalctl -u sslv-watchdog.service -u sslv-watchdog-heartbeat.service -n 30 --no-pager

watchdog-test-ntfy: ## send one low-priority test push to NTFY_TOPIC_URL
	@curl -fsS -H "Title: [$(M6_ENV)] SSLV watchdog test" -H "Priority: low" -H "Tags: test_tube" \
		-d "Test push from $$(hostname) at $$(date -u '+%Y-%m-%d %H:%M UTC')" "$(NTFY_TOPIC_URL)" > /dev/null \
		&& printf "$(call log_success,Test push sent to $(NTFY_TOPIC_URL))\n"

watchdog-drill: ## fire each alert once as [DRILL] pushes and check recovery (M6_ENV=staging, DRILL=memory,...)
	$(ntfy_topic_guard)
	@paused=0; \
	trap 'if [ $$paused = 1 ]; then sudo systemctl start sslv-watchdog.timer; printf "$(call log_info,Watchdog timer resumed)\n"; fi' EXIT; \
	if systemctl is-active --quiet sslv-watchdog.timer 2>/dev/null; then \
		printf "$(call log_info,Pausing sslv-watchdog.timer during the drill...)\n"; \
		sudo systemctl stop sslv-watchdog.timer && paused=1; \
	fi; \
	NTFY_TOPIC_URL="$(NTFY_TOPIC_URL)" python3 scripts/watchdog_drill.py --env $(M6_ENV) $(if $(DRILL),--only $(DRILL))

watchdog-uninstall: ## remove the watchdog timers and /etc/sslv-watchdog.env
	@sudo systemctl disable --now sslv-watchdog.timer sslv-watchdog-heartbeat.timer 2>/dev/null || true
	@for unit in $(WATCHDOG_UNITS); do sudo rm -f /etc/systemd/system/$$unit; done
	@sudo rm -f /etc/sslv-watchdog.env
	@sudo systemctl daemon-reload
	@printf "$(call log_success,Watchdog timers removed)\n"

##@ Diagnostics
# Read-only investigation: log bundles for support, scraper verification
# against ss.lv, and a quick look at table sizes. Safe to run any time.

.PHONY: collect-logs collect-logs-running collect-logs-full verify-scrape verify-scrape-all lt

collect-logs: ## bundle logs, artifacts and state from all cities (CITY= for one)
	@if [ -n "$(CITY)" ]; then \
	  ./scripts/collect_logs_v3.sh --city $(CITY); \
	else \
	  ./scripts/collect_logs_v3.sh; \
	fi

collect-logs-running: ## same, only cities with containers up
	@./scripts/collect_logs_v3.sh --running-only

collect-logs-full: ## same, plus debug DB dump and data dirs; large (CITY= optional)
	@if [ -n "$(CITY)" ]; then \
	  ./scripts/collect_logs_v3.sh --city $(CITY) --with-db-dump --with-data-dirs; \
	else \
	  ./scripts/collect_logs_v3.sh --with-db-dump --with-data-dirs; \
	fi

verify-scrape: ## verify page count + city naming against ss.lv (CITY=, default jurmala)
	@CITY=$${CITY:-jurmala} ./scripts/verify_city_scrape.sh $${CITY}

verify-scrape-all: ## run verify-scrape for jurmala, ogre, sigulda
	@for c in jurmala ogre sigulda; do \
	  echo "=== Verifying $$c ==="; \
	  CITY=$$c ./scripts/verify_city_scrape.sh $$c || true; \
	  echo; \
	done

lt: ## list table sizes in the first *-db-1 container (check a restore)
	@docker exec $(PG_CONTAINER_NAME) psql -U new_docker_user -d new_docker_db -c '\dt+'

##@ Backup & restore (per city)
# Backups live in sslv-<env>-<city>-db-backups (M6_ENV picks the env; CITY uses
# the cities.yaml key, e.g. marupes_pag). verify-backup and test-restore are
# safe to run any time. backup-* write to S3 and keep only the newest 5 objects.
# restore-* load the dump into the LIVE DB on top of existing data and ask you
# to type the city/env first — run test-restore before, backup-city right before.

.PHONY: backup-city backup-all verify-backup restore-city restore-all test-restore e2e-backup-restore fetch-last-db-dump fetch-dump fetch-dump-example

backup-city: ## back up one city's DB to S3; bucket keeps the newest 5 (CITY=ogre M6_ENV=prod)
	@./scripts/backup_db_city.sh --city $(CITY) --env $(M6_ENV)

backup-all: ## back up every city's DB to S3; each bucket keeps the newest 5 (M6_ENV=)
	@./scripts/backup_db_city.sh --all --env $(M6_ENV)

verify-backup: ## read-only: newest S3 backup per city is < 26h old and >= MIN_BACKUP_SIZE_KB (CITY= or all, M6_ENV=)
	@./scripts/verify_backup.sh $(if $(CITY),--city $(CITY),--all) --env $(M6_ENV)

restore-city: ## LIVE restore of one city's latest backup into its running DB; asks to confirm (CITY= M6_ENV=, YES=1)
	@./scripts/restore_db_city.sh --city $(CITY) --env $(M6_ENV) $(if $(filter 1 true yes,$(YES)),--yes)

restore-all: ## LIVE restore of every city's latest backup into its running DB; asks to confirm (M6_ENV=, YES=1)
	@./scripts/restore_db_city.sh --all --env $(M6_ENV) $(if $(filter 1 true yes,$(YES)),--yes)

test-restore: ## safe: restore the latest backup into a throwaway postgres container + count rows (CITY= or all, M6_ENV=)
	@./scripts/restore_db_city.sh $(if $(CITY),--city $(CITY),--all) --env $(M6_ENV) --scratch

e2e-backup-restore: ## take a fresh backup of CITY=, then prove it restores in a throwaway container (M6_ENV=)
	@if [ -z "$(CITY)" ]; then printf "$(call log_error,CITY= is required (e.g. make e2e-backup-restore CITY=ogre M6_ENV=staging))\n"; exit 1; fi
	@printf "$(call log_step,1/3 Backup $(CITY) (env $(M6_ENV)) to S3 — keeps the newest 5 backups...)\n"
	@./scripts/backup_db_city.sh --city $(CITY) --env $(M6_ENV)
	@printf "$(call log_step,2/3 Check the new backup in S3...)\n"
	@./scripts/verify_backup.sh --city $(CITY) --env $(M6_ENV)
	@printf "$(call log_step,3/3 Restore it into a throwaway container (live DB untouched)...)\n"
	@./scripts/restore_db_city.sh --city $(CITY) --env $(M6_ENV) --scratch
	@printf "$(call log_success,E2E backup/restore passed for $(CITY))\n"

fetch-last-db-dump: ## download the newest DB dump into src/db/ (CITY= M6_ENV= for a city bucket)
	@python3 src/db/get_last_db_backup.py $(if $(CITY),--city $(CITY) --env $(M6_ENV),)
	@cp *.sql src/db/ || true

fetch-dump: DB_BACKUP_DATE ?= 2022_11_01
fetch-dump: ## download the dump for one date into src/db/ (DB_BACKUP_DATE=2026_07_08, CITY= optional)
	@if [ -n "$(CITY)" ]; then \
		city_slug=$$(echo $(CITY) | sed 's/_/-/g'); \
		bucket="sslv-$(M6_ENV)-$$city_slug-db-backups"; \
	else \
		bucket="$(S3_BUCKET)"; \
	fi; \
	echo "Fetching from bucket: $$bucket"; \
	aws s3 cp s3://$$bucket/pg_backup_$(DB_BACKUP_DATE).sql . ; \
	cp pg_backup_$(DB_BACKUP_DATE).sql src/db/ || true

# Prints fetch-dump usage examples.
fetch-dump-example: # Example of fetch specific date DB dump file from S3 bucket
	@echo "make fetch-dump DB_BACKUP_DATE=2026_07_08"
	@echo "make fetch-dump DB_BACKUP_DATE=2026_07_08 CITY=ogre"

##@ AWS S3 buckets (one-time infrastructure)
# Create, tag and audit buckets following sslv-<env>-<city>-<purpose>. New
# buckets get public access blocked, versioning and a 90-day lifecycle rule.
# create_* change real AWS resources; list_* / check_* are read-only.

.PHONY: create-m6-bucket create-all-m6-buckets create-s3-bucket tag-existing-bucket check-m6-bucket list-m6-buckets list-existing-m6-buckets

create-m6-bucket: ## create sslv-<env>-<city>-<purpose> (M6_ENV= M6_CITY= M6_PURPOSE=, AWS_REGION=)
	$(MAKE) create-s3-bucket BUCKET_NAME=sslv-$(M6_ENV)-$(M6_CITY)-$(M6_PURPOSE) AWS_REGION=$(AWS_REGION) M6_ENV=$(M6_ENV) M6_CITY=$(M6_CITY) M6_PURPOSE=$(M6_PURPOSE)

create-all-m6-buckets: ## create every city x purpose bucket for M6_ENV= (12 buckets)
	@echo "Creating all M6 buckets for ENV=$(M6_ENV) ..."
	@for city in $(M6_CITIES); do \
		for purpose in $(M6_PURPOSES); do \
			$(MAKE) create-m6-bucket M6_ENV=$(M6_ENV) M6_CITY=$$city M6_PURPOSE=$$purpose || true; \
		done; \
	done
	@echo "Done (some may have been skipped if already existed)."

create-s3-bucket: ## create + harden one bucket: private, versioned, 90-day expiry (BUCKET_NAME= AWS_REGION=)
	@printf "$(call log_step,Creating S3 bucket: $(BUCKET_NAME) in region $(AWS_REGION)...)\n"
	@if aws s3 ls s3://$(BUCKET_NAME) 2>/dev/null; then \
		printf "$(call log_warning,Bucket $(BUCKET_NAME) already exists)\n"; \
		exit 1; \
	fi
	@if [ "$(AWS_REGION)" = "us-east-1" ]; then \
		aws s3api create-bucket \
			--bucket $(BUCKET_NAME) \
			--region $(AWS_REGION) || { \
			printf "$(call log_error,Failed to create bucket)\n"; \
			exit 1; \
		}; \
	else \
		aws s3api create-bucket \
			--bucket $(BUCKET_NAME) \
			--region $(AWS_REGION) \
			--create-bucket-configuration LocationConstraint=$(AWS_REGION) || { \
			printf "$(call log_error,Failed to create bucket)\n"; \
			exit 1; \
		}; \
	fi
	@printf "$(call log_success,Bucket created successfully)\n"
	@printf "$(call log_step,Blocking public access...)\n"
	@aws s3api put-public-access-block \
		--bucket $(BUCKET_NAME) \
		--public-access-block-configuration \
		"BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true" || { \
		printf "$(call log_error,Failed to block public access)\n"; \
		exit 1; \
	}
	@printf "$(call log_success,Public access blocked)\n"
	@printf "$(call log_step,Enabling versioning...)\n"
	@aws s3api put-bucket-versioning \
		--bucket $(BUCKET_NAME) \
		--versioning-configuration Status=Enabled || { \
		printf "$(call log_error,Failed to enable versioning)\n"; \
		exit 1; \
	}
	@printf "$(call log_success,Versioning enabled)\n"
	@printf "$(call log_step,Adding lifecycle policy (delete after 90 days)...)\n"
	@aws s3api put-bucket-lifecycle-configuration \
		--bucket $(BUCKET_NAME) \
		--lifecycle-configuration '{ \
			"Rules": [{ \
				"Id": "DeleteOldBackups", \
				"Status": "Enabled", \
				"Filter": {"Prefix": ""}, \
				"Expiration": {"Days": 90} \
			}] \
		}' || { \
		printf "$(call log_error,Failed to set lifecycle policy)\n"; \
		exit 1; \
	}
	@printf "$(call log_success,Lifecycle policy set)\n"
	@printf "$(call log_step,Adding tags...)\n"
	@aws s3api put-bucket-tagging \
		--bucket $(BUCKET_NAME) \
		--tagging 'TagSet=[ \
			{Key=Project,Value=sslv}, \
			{Key=Environment,Value=$(M6_ENV)}, \
			{Key=City,Value=$(M6_CITY)}, \
			{Key=Version,Value=1.6}, \
			{Key=Purpose,Value=$(M6_PURPOSE)}, \
			{Key=CreatedDate,Value=$(shell date +%Y-%m-%d)} \
		]' || { \
		printf "$(call log_error,Failed to add tags)\n"; \
		exit 1; \
	}
	@printf "$(call log_success,Tags added)\n"
	@printf "$(call log_success,S3 bucket $(BUCKET_NAME) created and configured successfully!)\n"
	@printf "$(call log_info,Bucket details:)\n"
	@printf "  - Name: $(BUCKET_NAME)\n"
	@printf "  - Region: $(AWS_REGION)\n"
	@printf "  - Public Access: Blocked\n"
	@printf "  - Versioning: Enabled\n"
	@printf "  - Lifecycle: Delete after 90 days\n"

tag-existing-bucket: ## apply standard tags to an existing bucket (BUCKET_NAME= or M6_ENV= M6_CITY= M6_PURPOSE=)
	@if [ -n "$(BUCKET_NAME)" ]; then \
		BUCKET="$(BUCKET_NAME)"; \
		ENV_TAG="$$(echo $$BUCKET | cut -d- -f2)"; \
		CITY_TAG="$$(echo $$BUCKET | cut -d- -f3- | rev | cut -d- -f2- | rev)"; \
		PURPOSE_TAG="$$(echo $$BUCKET | rev | cut -d- -f1 | rev)"; \
	else \
		if [ -z "$(M6_CITY)" ]; then \
			echo "Error: provide BUCKET_NAME=... or M6_CITY=... (with M6_ENV and M6_PURPOSE)"; \
			exit 1; \
		fi; \
		BUCKET="sslv-$(M6_ENV)-$(M6_CITY)-$(M6_PURPOSE)"; \
		ENV_TAG="$(M6_ENV)"; \
		CITY_TAG="$(M6_CITY)"; \
		PURPOSE_TAG="$(M6_PURPOSE)"; \
	fi; \
	echo "Tagging bucket: $$BUCKET"; \
	aws s3api put-bucket-tagging \
		--bucket $$BUCKET \
		--tagging 'TagSet=[ \
			{Key=Project,Value=sslv}, \
			{Key=Environment,Value='$$ENV_TAG'}, \
			{Key=City,Value='$$CITY_TAG'}, \
			{Key=Version,Value=1.6}, \
			{Key=Purpose,Value='$$PURPOSE_TAG'}, \
			{Key=CreatedDate,Value=$(shell date +%Y-%m-%d)} \
		]' || { printf "$(call log_error,Failed to tag $$BUCKET)\n"; exit 1; }; \
	echo "Tags applied to $$BUCKET"

check-m6-bucket: ## show a bucket's public access, versioning, region and lifecycle (BUCKET_NAME=)
	@if [ -z "$(BUCKET_NAME)" ]; then \
		echo "Error: BUCKET_NAME=... is required"; \
		exit 1; \
	fi; \
	echo "Checking bucket: $(BUCKET_NAME)"; \
	echo "  Public access block:"; \
	aws s3api get-public-access-block --bucket $(BUCKET_NAME) --query 'PublicAccessBlockConfiguration' --output text 2>/dev/null || echo "    (not set or error)"; \
	echo "  Versioning:"; \
	aws s3api get-bucket-versioning --bucket $(BUCKET_NAME) --query 'Status' --output text 2>/dev/null || echo "    (unknown)"; \
	echo "  Location:"; \
	aws s3api get-bucket-location --bucket $(BUCKET_NAME) --query 'LocationConstraint' --output text 2>/dev/null || echo "    us-east-1"; \
	echo "  Lifecycle rules:"; \
	aws s3api get-bucket-lifecycle-configuration --bucket $(BUCKET_NAME) --query 'Rules[0].Status' --output text 2>/dev/null || echo "    (none or error)"

list-m6-buckets: ## print expected bucket names (M6_ENVS x M6_CITIES x M6_PURPOSES)
	@echo "Expected M6 buckets:"
	@for env in $(M6_ENVS); do \
		for city in $(M6_CITIES); do \
			for purpose in $(M6_PURPOSES); do \
				echo "  sslv-$$env-$$city-$$purpose"; \
			done; \
		done; \
	done

list-existing-m6-buckets: ## list buckets in AWS matching sslv-<env>-<city>-<purpose>
	@echo "Existing buckets matching M6 pattern (sslv-{env}-{city}-{purpose}):"
	@aws s3 ls | awk '{print $$3}' | grep -E '^sslv-(prod|staging|dev)-.*-(db-backups|scraped-data)$$' || echo "  (none found or no AWS access)"

##@ Tests

.PHONY: test test-cov

test: ## run pytest
	pytest -v

test-cov: ## run pytest with coverage
	pytest --cov=.

##@ Legacy single-project (M5, pre-multi-city)
# The original one-city stack: `docker-compose --env-file .env.prod` without
# --project-name, secrets from AWS Secrets Manager (sslv_creds) and the M5
# bucket. Still used by .github/workflows/main.yml (setup, build, up); the M5
# workflow (CICD-arm-dev-m5.yml) checks out dev-1.5.8 and uses that branch's
# ec2_* targets. Not for
# the multi-city fleet — use the Deploy section. `down` deletes its DB volume.

.PHONY: setup verify-setup check-backup-age precheck build up down clean cleanup-on-failure _setup-precheck

setup: _setup-precheck ## load secrets (Secrets Manager + M5 bucket) and download the latest DB backup
	@printf "$(call log_step,Starting EC2 setup...)\n"
	@set -e; \
	trap 'printf "$(call log_error,Setup failed! Cleaning up...)\n"; $(MAKE) cleanup-on-failure' ERR; \
	\
	if [ -f $(SETUP_STATE_FILE) ]; then \
		printf "$(call log_info,Previous setup detected. Checking if re-setup is needed...)\n"; \
		if $(MAKE) verify-setup 2>/dev/null; then \
			printf "$(call log_success,Setup already completed and verified.)\n"; \
			printf "$(call log_info,To force re-setup run: make clean && make setup)\n"; \
			exit 0; \
		else \
			printf "$(call log_warning,Previous setup incomplete. Re-running setup...)\n"; \
			rm -f $(SETUP_STATE_FILE); \
		fi; \
	fi; \
	\
	printf "$(call log_step,Loading secrets from AWS Secrets Manager...)\n"; \
	. ./scripts/load_secrets.sh || { \
		printf "$(call log_error,Failed to load secrets)\n"; \
		exit 1; \
	}; \
	\
	printf "$(call log_step,Verifying required files downloaded...)\n"; \
	if [ ! -f .env.prod ]; then \
		printf "$(call log_error,Failed to download .env.prod)\n"; \
		exit 1; \
	fi; \
	printf "$(call log_success,.env.prod downloaded)\n"; \
	\
	if [ ! -f database.ini ]; then \
		printf "$(call log_error,Failed to download database.ini)\n"; \
		exit 1; \
	fi; \
	printf "$(call log_success,database.ini downloaded)\n"; \
	\
	printf "$(call log_step,Copying database.ini to src/ws/...)\n"; \
	mkdir -p src/ws; \
	cp database.ini src/ws/ || { \
		printf "$(call log_error,Failed to copy database.ini)\n"; \
		exit 1; \
	}; \
	printf "$(call log_success,database.ini copied to src/ws/)\n"; \
	\
	printf "$(call log_step,Downloading Postgres DB backup from S3...)\n"; \
	bash scripts/get_last_s3_file.sh || { \
		printf "$(call log_error,Failed to download DB backup)\n"; \
		exit 1; \
	}; \
	\
	printf "$(call log_step,Verifying downloaded backup file...)\n"; \
	if ! ls pg_backup_*.sql 1> /dev/null 2>&1; then \
		printf "$(call log_error,No backup file found after download)\n"; \
		exit 1; \
	fi; \
	BACKUP_FILE=$$(ls -t pg_backup_*.sql | head -1); \
	BACKUP_SIZE=$$(stat -f%z "$$BACKUP_FILE" 2>/dev/null || stat -c%s "$$BACKUP_FILE" 2>/dev/null); \
	if [ $$BACKUP_SIZE -lt 1024 ]; then \
		printf "$(call log_error,Backup file too small ($$BACKUP_SIZE bytes) likely corrupted)\n"; \
		exit 1; \
	fi; \
	printf "$(call log_success,Backup file verified: $$BACKUP_FILE ($$(numfmt --to=iec $$BACKUP_SIZE 2>/dev/null || echo $$BACKUP_SIZE bytes)))\n"; \
	\
	printf "$(call log_step,Copying DB backup file to src/db/...)\n"; \
	mkdir -p src/db; \
	cp pg_backup_*.sql src/db/ || { \
		printf "$(call log_error,Failed to copy backup to src/db/)\n"; \
		exit 1; \
	}; \
	printf "$(call log_success,DB backup copied to src/db/)\n"; \
	\
	printf "$(call log_step,Setup files summary:)\n"; \
	ls -lh src/db/ | grep sql || true; \
	\
	printf "$(call log_success,Setup completed successfully!)\n"; \
	echo "$$(date)" > $(SETUP_STATE_FILE); \
	\
	$(MAKE) check-backup-age

verify-setup: ## check .env.prod, database.ini and the DB backup file are present
	@printf "$(call log_step,Verifying setup files...)\n"
	@MISSING=0; \
	if [ ! -f .env.prod ]; then \
		printf "$(call log_error,Missing: .env.prod)\n"; \
		MISSING=1; \
	fi; \
	if [ ! -f database.ini ]; then \
		printf "$(call log_error,Missing: database.ini)\n"; \
		MISSING=1; \
	fi; \
	if [ ! -f src/ws/database.ini ]; then \
		printf "$(call log_error,Missing: src/ws/database.ini)\n"; \
		MISSING=1; \
	fi; \
	if ! ls src/db/pg_backup_*.sql 1> /dev/null 2>&1; then \
		printf "$(call log_error,Missing: src/db/pg_backup_*.sql)\n"; \
		MISSING=1; \
	fi; \
	if [ $$MISSING -eq 0 ]; then \
		printf "$(call log_success,All setup files are present)\n"; \
		return 0; \
	else \
		printf "$(call log_error,Some setup files are missing)\n"; \
		return 1; \
	fi

check-backup-age: ## warn if src/db/pg_backup_*.sql is older than BACKUP_AGE_WARNING_DAYS
	@if [ -f src/db/pg_backup_*.sql ]; then \
		BACKUP_FILE=$$(ls -t src/db/pg_backup_*.sql 2>/dev/null | head -1); \
		if [ -n "$$BACKUP_FILE" ]; then \
			BACKUP_DATE=$$(echo $$BACKUP_FILE | grep -o '[0-9]\{4\}_[0-9]\{2\}_[0-9]\{2\}' | head -1); \
			if [ -n "$$BACKUP_DATE" ]; then \
				BACKUP_EPOCH=$$(date -j -f "%Y_%m_%d" "$$BACKUP_DATE" "+%s" 2>/dev/null || echo 0); \
				CURRENT_EPOCH=$$(date "+%s"); \
				AGE_DAYS=$$(( ($$CURRENT_EPOCH - $$BACKUP_EPOCH) / 86400 )); \
				if [ $$AGE_DAYS -gt $(BACKUP_AGE_WARNING_DAYS) ]; then \
					printf "$(call log_warning,Backup file is $$AGE_DAYS days old (threshold: $(BACKUP_AGE_WARNING_DAYS) days))\n"; \
					printf "$(call log_info,Consider fetching a more recent backup)\n"; \
				else \
					printf "$(call log_success,Backup file age: $$AGE_DAYS days (acceptable))\n"; \
				fi; \
			fi; \
		fi; \
	fi

precheck: ## check S3_BUCKET is exported
	@printf "$(call log_step,Checking if env S3_BUCKET is exported...)\n"
	@if [ -z "$(S3_BACKUP_BUCKET)" ]; then \
		echo ""; \
		printf "$(call log_error,S3_BUCKET is not exported.)\n"; \
		echo ""; \
		printf "$(call log_info,Option 1: Load environment secrets from AWS Secrets manager with:)\n"; \
		echo "  source scripts/load_secrets.sh"; \
		echo ""; \
		printf "$(call log_info,Option 2: Export manually:)\n"; \
		echo "  export S3_BUCKET='your-bucket-name'"; \
		echo ""; \
		exit 1; \
	fi
	@printf "$(call log_success,env S3_BUCKET is exported)\n"

build: ## build the db, ts and ws images
	@docker-compose --env-file .env.prod build db
	@docker-compose --env-file .env.prod build ts
	@docker-compose --env-file .env.prod build ws

up: ## start the single-project stack
	docker-compose --env-file .env.prod up -d

down: ## stop the single-project stack AND delete its DB volume (multi-city: undeploy-*)
	docker-compose --env-file .env.prod down -v   # removes volumes (clears old PGDATA)

clean: ## delete setup files, DB dumps and project images (not containers)
	@printf "$(call log_step,Cleaning up setup files...)\n"
	@rm -f .env.prod && printf "$(call log_success,Removed .env.prod)\n" || printf "$(call log_info,.env.prod not found)\n"
	@rm -f database.ini && printf "$(call log_success,Removed database.ini)\n" || printf "$(call log_info,database.ini not found)\n"
	@rm -f ./src/ws/database.ini && printf "$(call log_success,Removed src/ws/database.ini)\n" || printf "$(call log_info,src/ws/database.ini not found)\n"
	@rm -f *.sql && printf "$(call log_success,Removed *.sql files)\n" || printf "$(call log_info,No .sql files found)\n"
	@rm -f ./src/db/pg_backup_*.sql && printf "$(call log_success,Removed DB backups)\n" || printf "$(call log_info,No DB backups found)\n"
	@rm -f $(SETUP_STATE_FILE) && printf "$(call log_success,Removed setup state file)\n" || printf "$(call log_info,No setup state file found)\n"
	@if [ -f ./rm_images.sh ]; then \
		bash ./rm_images.sh; \
	else \
		printf "$(call log_info,rm_images.sh not found - skipping)\n"; \
	fi
	@printf "$(call log_step,Pruning project-specific images (e.g. *-backup) ...)\n"
	@docker images --format "{{.Repository}}" | grep -E -e '-(backup|ts|ws|db)$$' | xargs -r docker rmi -f 2>/dev/null || true
	@printf "$(call log_success,Cleanup completed)\n"

# Internal: called by setup's ERR trap.
cleanup-on-failure:  # cleanup partial files on setup failure
	@printf "$(call log_step,Cleaning up partial setup files...)\n"
	@rm -f $(SETUP_STATE_FILE)
	@rm -f pg_backup_*.sql 2>/dev/null || true
	@printf "$(call log_info,Cleanup complete. You can retry setup.)\n"

# Internal: prerequisite of setup (AWS CLI, jq, S3_BUCKET from Secrets Manager).
_setup-precheck:
	@printf "$(call log_step,Loading envs from AWS Secrets Manager...)\n"
	@set -e; \
	if ! command -v aws >/dev/null 2>&1; then \
		printf "$(call log_error,AWS CLI is not installed. Please install it first.)\n"; \
		exit 1; \
	fi; \
	if ! command -v jq >/dev/null 2>&1; then \
		printf "$(call log_error,jq is not installed. Please install it first.)\n"; \
		exit 1; \
	fi; \
	. ./scripts/set_s3_env_from_aws_sm.sh || { \
		printf "$(call log_error,Failed to load environment from AWS Secrets Manager)\n"; \
		exit 1; \
	}; \
	if [ -z "$$S3_BUCKET" ]; then \
		printf "$(call log_error,S3_BUCKET is not exported.)\n"; \
		printf "$(call log_info,To set env run: source scripts/set_s3_env_from_aws_sm.sh)\n"; \
		exit 1; \
	else \
		printf "$(call log_success,S3_BUCKET is exported: $$S3_BUCKET)\n"; \
	fi

# Deprecated snake_case names, kept so old docs, notes and muscle memory still
# work. Each runs the kebab-case target, then prints a deprecation notice.
# Hidden from `make help`; remove once nothing uses them.
DEPRECATED_ALIASES := create_m6_bucket:create-m6-bucket create_all_m6_buckets:create-all-m6-buckets \
	create_s3_bucket:create-s3-bucket tag_existing_bucket:tag-existing-bucket \
	check_m6_bucket:check-m6-bucket list_m6_buckets:list-m6-buckets \
	list_existing_m6_buckets:list-existing-m6-buckets fetch_dump:fetch-dump \
	fetch_last_db_dump:fetch-last-db-dump fetch_dump_example:fetch-dump-example \
	test_cov:test-cov ec2_precheck:_setup-precheck

define deprecated_alias
.PHONY: $(1)
$(1): $(2)
	@printf "$$(call log_warning,'make $(1)' is deprecated; use 'make $(2)')\n"
endef
$(foreach a,$(DEPRECATED_ALIASES),$(eval $(call deprecated_alias,$(word 1,$(subst :, ,$(a))),$(word 2,$(subst :, ,$(a))))))
