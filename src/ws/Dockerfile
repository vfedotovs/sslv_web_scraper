FROM python:3.11-slim-bookworm

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

# Uvicorn configuration
# One worker, no --limit-max-requests (main had --workers 2 --limit-max-requests 1000,
# an OOM workaround from when /run-task ran the whole pipeline inside the request):
# - /run-task now runs the pipeline in a background thread and guards it with an
#   in-process threading.Lock (M7 P6). A second worker would have its own lock, so
#   two runs could overlap instead of the second getting 409.
# - A max-requests recycle would kill that daemon thread mid-run and leave the
#   scrape_runs row stuck at 'running'.
# Memory is kept in check by gc + explicit DataFrame release after each stage.
# --timeout-keep-alive 5: Close keep-alive connections after 5 seconds (frees up resources)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "5"]
