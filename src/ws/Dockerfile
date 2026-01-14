FROM python:3.8-slim-buster

COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8000

COPY database.ini /

COPY ./app /app

# Uvicorn configuration with memory leak prevention
# --host 0.0.0.0: Bind to all network interfaces (allows external connections)
# --port 8000: Listen on port 8000
# --workers 2: Run 2 worker processes (provides redundancy and load distribution)
# --max-requests 100: Restart worker after handling 100 requests (prevents memory accumulation)
# --max-requests-jitter 20: Add randomness (80-120 requests) to prevent all workers restarting simultaneously
# --timeout-keep-alive 5: Close keep-alive connections after 5 seconds (frees up resources)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--max-requests", "100", "--max-requests-jitter", "20", "--timeout-keep-alive", "5"]
