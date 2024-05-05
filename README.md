# SS.LV Web Scraper 

| | |
| --- | --- |
| Test, Build and Deploy | ![CI](https://github.com/vfedotovs/sslv_web_scraper/actions/workflows/CI.yml/badge.svg) |(https://github.com/vfedotovs/sslv_web_scraper/actions/workflows/CI.yml)|
| Coverage | [![codecov](https://codecov.io/gh/vfedotovs/sslv_web_scraper/graph/badge.svg?token=Y9AQW4YEYH)](https://codecov.io/gh/vfedotovs/sslv_web_scraper) |
| Embark on an exploration of Ogre City apartments for sale historical data here |http://propertydata.lv/|

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
all                  runs setup, build and up targets
setup                gets database.ini and .env.prod and dowloads last DB bacukp file
build                builds all containers
up                   starts all containers
down                 stops all containers
clean                removes setup and DB files and folders
lt                   Lists tables sizes in postgres docker allows to test if DB dump was restored correctly
```


## Currently available features
- [x] Scrape ss.lv website to extract advert data from Ogre city apartments for sale section
- [x] Store scraped data in postgres database container tables listed_ads and removed_ads for tracking longer price trends
- [x] Daily email is sent which includes advert URLs and key data categorized by room count
- [x] Email contains pdf attachment with basic price analytics for categorized by room count
- [x] Fully automated deployment for dev branche with Github Actions CICD to AWS EC2
- [x] Add tests and test coverage step in CICD and in README.md
- [x] Add WEB service functionality for data explore using Pygwalker and Streamlit


## Worok in progress:
- [ ] Add Streamlit web service to CICD 
- [ ] Add doc and doc coverage step in CICD and in README.md
