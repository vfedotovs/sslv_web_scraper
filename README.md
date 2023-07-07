# SS.LV Web Scraper 

![CI Build ](https://github.com/vfedotovs/sslv_web_scraper/actions/workflows/main.yml/badge.svg)

## About application:
Purpose: This application will scrape daily ss.lv website from apartments for sale category in specific city of your choice
and store scraped data in postgres database and will send daily email with report.


## Requirements

```bash
# docker -v                                                                 
Docker version 20.10.11, build dea9396

# docker-compose -v                                                                  
Docker Compose version v2.2.1

```

## How to use application:
1. Clone repository 
2. Create database.ini here is example
```bash                                      
[postgresql]
host=<your docker db hostname>
database=<your db name>
user=<your db username>
password=<your db password>

```
3. Create .env.prod file for docker compose
```bash                                      
# ws_worker container envs
DEST_EMAIL=user@example.com
SENDGRID_API_KEY=<Your SENDGRID API Key>
SRC_EMAIL=user@example.com
POSTGRES_PASSWORD=<Your DB Password>
```
5. Run docker-compose --env-file .env.prod up -d

## Use make
```bash
make                                                                          
help                 💬 This help message
fetch_env_files      Fetches locally env files database.ini and .env.prod
fetch_dump_example   Example of fetch specific date DB dump file form S3 bucket
fetch_dump           Fetches DB dump file from S3 bucket
fetch_last_db_dump   Fetches last Postgres DB dump from AWS S3 bucket
compose_db_up        Starts DB container
list_db_tables       Lists tables sizes in postgres docker allows to test if DB dump was restored correctly
compose_up           Starts remainig containers
compose_down         Stops all containers
test                 Runs pytests locally
test_cov             Runs pytest coverage report across project
prune_containers     Cleans all docker containers locally
build_ts             Building task_scheduler container
push_ts              Tagging and pushing ts to AWS ECR
build_db             Building db container
push_db              Tagging and pushing db container to AWS ECR
build_ws             Building web_scraper container
push_ws              Tagging and pushing ws container to AWS ECR
deploy               Deploying app to AWS EC2 ...(not implemented)
```


## Currently available features
- [x] Scrape ss.lv website to extract advert data from Ogre city apartments for sale section
- [x] Store scraped data in postgres database container tables listed_ads and removed_ads for tracking longer price trends
- [x] Daily email is sent which includes advert URLs and key data categorized by room count
- [x] Email contains pdf attachment with basic price analytics for categorized by room count
- [x] Fully automated deployment for dev, release and main branches with Github Actions CICD to AWS EC2


## TODO:
- [x] Add feature for dev-1.4.xx cron job backup docker container DB on EC2
- [x] Add feature for dev-1.4.xx cron job upload DB backup file to S3 bucket so it can be used in next CICD deployments
- [ ] Add feature for dev-1.4.xx save logs daily to one container and cron job to backup logs to S3 for root cause needs
- [ ] Add Sphinx project documentation and doc coverage in README.md
- [ ] Improve pdf attachment file content (Priority)
- [ ] Improve email body to contain added and removed ads for every day in current month (Priority)
- [ ] Add WEB services GUI for data explore and analytics (Work inprogress)
- [ ] Add test coverage on CICD and in README.md
