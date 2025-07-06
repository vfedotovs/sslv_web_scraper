
FROM python:3.10-slim-buster

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

COPY ts.py .

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD curl -f http://ws:8000/health || exit 1

CMD [ "python", "./ts.py" ]
