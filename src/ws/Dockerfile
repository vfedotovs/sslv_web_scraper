FROM python:3.8-slim-buster

# Install curl for HEALTHCHECK
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8000

COPY database.ini /

COPY ./app /app

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Uvicorn configuration with memory leak prevention
# --host 0.0.0.0: Bind to all network interfaces (allows external connections)
# --port 8000: Listen on port 8000
# --workers 2: Run 2 worker processes (provides redundancy and load distribution)
# --limit-max-requests 30: Restart worker after handling 30 requests (prevents OOM on 2GB RAM instance)
#                          With ~24MB leak per request: 101MB + (24MB × 30) = 821MB per worker
#                          Total with 2 workers: ~1.64GB + 300MB OS = 1.94GB (safe for 2GB instance)
# --timeout-keep-alive 5: Close keep-alive connections after 5 seconds (frees up resources)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--limit-max-requests", "30", "--timeout-keep-alive", "5"]
