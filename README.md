# SS.LV Web Scraper release 1.4


## About application:
Purpose: This application will parse information from ss.lv website from apartments for sale category in specific city of your choice
and store scraped data in postgres database


## Requirements
1. OS version: RHEL TBC

2. # docker -v                                                                 
Docker version 20.10.11, build dea9396

3. # docker-compose -v                                                                  
Docker Compose version v2.2.1

3. # git version                                                                  
git version 2.32.0


## How to use application:
1. Clone repository 
2. Create database.ini here is example content
```bash
database.ini                                        
[postgresql]
host=<your docker db hostname>
database=<your db name>
user=<your db username>
password=<your db password>

```
3. Create .env.prod file dor docker compose
4. TODO: .env.prod file  example
5. Run docker-compose --env-file .env.prod up -d


## Currently available features
- [x] Parse ss.lv website and extract information from section apartments for sale (currently hardcoded for Ogre city adjust to your needs)
- [x] Store scraped data in psotgres DB container tables listed_ads and removed_ads  
