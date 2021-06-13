FROM python:3.7-slim

WORKDIR /home/user/docker/sslv_web_scraper

COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

COPY sslv_web_scraper .

CMD [ "python", "./app.py" ]
