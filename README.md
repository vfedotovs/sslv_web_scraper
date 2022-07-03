# SS.LV Web Scraper release 1.5.x
![](https://img.shields.io/github/v/release/vfedotovs/sslv_web_scraper)![](https://img.shields.io/github/release-date/vfedotovs/sslv_web_scraper) ![](https://img.shields.io/github/commit-activity/y/vfedotovs/sslv_web_scraper)	![](https://img.shields.io/github/issues-raw/vfedotovs/sslv_web_scraper)![](https://img.shields.io/github/issues-closed-raw/vfedotovs/sslv_web_scraper)![](https://img.shields.io/github/milestones/progress-percent/vfedotovs/sslv_web_scraper/5)

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


## Available functionality
- [x] Scrape ss.lv website daily and extract information about apartments for sale for Ogre city
- [x] Store scraped data in postgres database 
- [x] Send daily email (includes URLs and scraped data categorized by room count)
- [ ] Website to display todays scraped data and historic data trends (work in progress)
- [ ] CICD pipeline (work in progress)  
