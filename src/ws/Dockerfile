FROM python:3.8-slim-buster

# Install curl for the HEALTHCHECK
# 'apt-get update' refreshes the package list
# 'apt-get install -y' installs packages without prompting
# '--no-install-recommends' helps keep the image size smaller by not installing
#                         recommended but not strictly required packages
# 'ca-certificates' is often needed for HTTPS connections to work reliably
# 'rm -rf /var/lib/apt/lists/*' cleans up the apt cache after installation
#                               to reduce the final image size.
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

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
