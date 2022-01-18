# SS.LV Web Scraper release 1.4.3


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


## Currently available features
- [x] Parse ss.lv website and extract information from section apartments for sale (currently hardcoded for Ogre city adjust to your needs)
- [x] Store scraped data in postgres database container tables listed_ads and removed_ads for tracking longer price trends
- [x] Daily email (includes URLs and key data categorized by room count)
- [ ] Daily email with pdf attachment that includes basic price analytics for categorized by room count
