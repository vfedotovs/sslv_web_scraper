[![Build Status](https://travis-ci.com/vfedotovs/sslv_web_scraper.svg?branch=main)](https://travis-ci.com/vfedotovs/sslv_web_scraper)
# SS.LV Web Scraper

## About application:
Purpose: This application will parse information from ss.lv website from apartments for sale category in specific city of your choice
and  will send report filtered by your criteria to your gmail address 

## How to use application:
1. API KEY is needed from https://sendgrid.com/ for sending emails
2. Bulid docker image and run container
```bash
docker build -t my-app-image .
docker run -it --name my-app-name \
	-e DEST_EMAIL=dest@example.com \
	-e SENDGRID_API_KEY=<My_sendgrid_API_KEY> \
	-e SRC_EMAIL=src@example.com \
	-d <docker-image-ID>
```
3. Report should arrive to email


## Currently available features
- [x] Parse ss.lv website and extract information from section apartments for sale (currently hardcoded for Ogre city adjust to your needs)
- [x] Generate basic user frendly report in formated of one line for each advertisement
- [x] Send email via sendgrid email gateway with report  
- [x] Email includes pdf report with basic price analytics and Price/square m relationship graphs
- [x] Docker container is sleeping and running report once per day   
