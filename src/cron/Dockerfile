FROM alpine:3.19

# Install required packages
RUN apk add --no-cache \
    bash \
    curl \
    docker-cli \
    aws-cli \
    postgresql-client \
    tzdata

# Set timezone (adjust as needed)
ENV TZ=UTC

# Create directory for scripts
RUN mkdir -p /scripts

# Copy cron jobs file
COPY crontab /etc/crontabs/root

# Copy helper scripts
COPY scripts/* /scripts/
RUN chmod +x /scripts/*.sh

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create log directory
RUN mkdir -p /var/log/cron

ENTRYPOINT ["/entrypoint.sh"]
CMD ["crond", "-f", "-l", "2"]
