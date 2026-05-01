FROM python:3.10-slim-bookworm

# Install curl for HEALTHCHECK
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8000

COPY database.ini /

COPY ./app /app

HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Uvicorn configuration with memory leak prevention
# --host 0.0.0.0: Bind to all network interfaces (allows external connections)
# --port 8000: Listen on port 8000
# --workers 2: Run 2 worker processes (provides redundancy and load distribution)
# --limit-max-requests 1000: Restart worker after 1000 requests (prevents OOM on 2GB RAM instance)
#                            Health checks (~1440/worker/day) are lightweight and don't leak memory.
#                            Only /run-task requests leak ~24MB each. At 1000 limit, workers restart
#                            roughly every 8 hours, balancing OOM safety with minimal churn.
# --timeout-keep-alive 5: Close keep-alive connections after 5 seconds (frees up resources)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--limit-max-requests", "1000", "--timeout-keep-alive", "5"]
