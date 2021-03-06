FROM python:3

WORKDIR /home/user/docker/sslv_web_scraper

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD [ "python", "./app.py" ]
