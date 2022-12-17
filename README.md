# SS.LV Web Scraper 

![CI Build ](https://github.com/vfedotovs/sslv_web_scraper/actions/workflows/main.yml/badge.svg)

## About application:
Purpose: This application will parse information from ss.lv website from apartments for sale category in specific city of your choice
and store scraped data in postgres database


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


## How to generate project documentation: 
```bash
mkdocks serve 

To acess navigate http://127.0.0.1:8000/sslv_web_scraper/
```

## Currently available features
- [x] Parse ss.lv website and extract information from section apartments for sale (currently hardcoded for Ogre city adjust to your needs)
- [x] Store scraped data in postgres database container tables listed_ads and removed_ads for tracking longer price trends
- [x] Daily email (includes URLs and key data categorized by room count)
- [x] Email contains MVP pdf attachment with basic price analytics for categorized by room count
- [x] Github Actions CICD 
