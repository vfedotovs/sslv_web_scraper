FROM python:3.8-slim-buster

WORKDIR /app

COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

COPY ts.py .

# Expose health check port
EXPOSE 8080

# Health check using Python's built-in urllib (no external dependencies needed)
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health').read()" || exit 1

CMD [ "python", "./ts.py" ]
