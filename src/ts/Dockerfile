
FROM python:3.8-slim-buster

WORKDIR /app

COPY src/ts/requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

COPY src/ts/ts.py .

CMD [ "python", "./ts.py" ]
