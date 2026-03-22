# Cron Service

Dockerized cron service for automated backups, monitoring, and notifications.

## Overview

This container runs scheduled tasks including:
- **Database backups** (daily at 3:05 AM UTC)
- **S3 uploads** (daily at 3:07 AM UTC)
- **Monitoring alerts** (multiple times per day)

All cron jobs are defined in `crontab` and executed via individual scripts in `/scripts/`.

## Features

✅ **Isolated cron environment** - No need for host crontab
✅ **Docker socket access** - Can manage other containers
✅ **AWS CLI integration** - Uploads backups to S3
✅ **ntfy.sh notifications** - Real-time monitoring alerts
✅ **Structured logging** - All logs saved to `/var/log/cron/`

## Architecture

```
src/cron/
├── Dockerfile              # Container definition
├── crontab                 # Cron schedule definitions
├── entrypoint.sh          # Startup script
├── scripts/               # Individual job scripts
│   ├── backup_db.sh
│   ├── upload_backup_to_s3.sh
│   ├── send_db_worker_results.sh
│   ├── send_db_comparison.sh
│   ├── send_container_uptime.sh
│   ├── send_container_stats.sh
│   └── send_tmp_files_info.sh
└── README.md
```

## Schedule

| Time (UTC) | Task | Script | Description |
|------------|------|--------|-------------|
| 3:05 AM | DB Backup | `backup_db.sh` | Creates PostgreSQL dump |
| 3:07 AM | S3 Upload | `upload_backup_to_s3.sh` | Uploads backup to S3 |
| 3:10 AM | DB Results | `send_db_worker_results.sh` | Sends DB worker stats to ntfy |
| 3:12 AM | DB Comparison | `send_db_comparison.sh` | Sends comparison logs to ntfy |
| 4:10 AM | Container Uptime | `send_container_uptime.sh` | Sends uptime to ntfy |
| 4:11 AM | Container Stats | `send_container_stats.sh` | Sends memory/CPU stats to ntfy |
| 4:12 AM | /tmp Files | `send_tmp_files_info.sh` | Sends backup file info to ntfy |

## Prerequisites

### Environment Variables

Set these in your `.env` file:

```bash
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
```

### Docker Socket

The container needs access to the Docker socket to:
- Execute commands in other containers (db, ws)
- Get container stats and status

This is mounted via:
```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
```

## Deployment

### 1. Build and Start

```bash
docker-compose up -d --build cron
```

### 2. Verify Container is Running

```bash
docker-compose ps cron
```

### 3. Check Startup Logs

```bash
docker-compose logs cron
```

You should see:
```
Starting cron service...
Current time: 2026-01-17 10:00:00
✅ Docker access confirmed
✅ AWS access confirmed
Starting crond in foreground...
```

### 4. Verify Cron Jobs

```bash
docker-compose exec cron cat /etc/crontabs/root
```

## Manual Testing

### Test Database Backup

```bash
docker-compose exec cron /scripts/backup_db.sh
```

Check for backup file:
```bash
docker-compose exec cron ls -lh /tmp/pg_backup_*.sql
```

### Test S3 Upload

```bash
docker-compose exec cron /scripts/upload_backup_to_s3.sh
```

### Test Notifications

```bash
docker-compose exec cron /scripts/send_container_uptime.sh
```

## Logs

View cron execution logs:

```bash
# All cron activity
docker-compose logs -f cron

# Backup logs only
docker-compose exec cron cat /var/log/cron/backup.log

# S3 upload logs
docker-compose exec cron cat /var/log/cron/s3_upload.log

# Notification logs
docker-compose exec cron cat /var/log/cron/ntfy.log
```

## Troubleshooting

### Cron Jobs Not Running

1. Check if container is running:
   ```bash
   docker-compose ps cron
   ```

2. Check cron daemon logs:
   ```bash
   docker-compose logs cron
   ```

3. Verify crontab syntax:
   ```bash
   docker-compose exec cron cat /etc/crontabs/root
   ```

### Docker Access Issues

If you see "Cannot access Docker":

1. Verify Docker socket is mounted:
   ```bash
   docker-compose exec cron ls -la /var/run/docker.sock
   ```

2. Check permissions:
   ```bash
   docker-compose exec cron docker ps
   ```

### AWS S3 Upload Failures

1. Verify AWS credentials:
   ```bash
   docker-compose exec cron env | grep AWS
   ```

2. Test AWS CLI access:
   ```bash
   docker-compose exec cron aws s3 ls
   ```

3. Check S3 bucket permissions

### Missing Backups

1. Check if backup script ran:
   ```bash
   docker-compose exec cron cat /var/log/cron/backup.log
   ```

2. Verify database container is accessible:
   ```bash
   docker-compose exec cron docker ps --filter "name=db-1"
   ```

## Customization

### Change Timezone

Edit `docker-compose.yml`:
```yaml
cron:
  environment:
    TZ: Europe/Riga  # Your timezone
```

### Modify Schedule

Edit `src/cron/crontab`:
```cron
# Run backup every 6 hours instead of daily
0 */6 * * * /scripts/backup_db.sh >> /var/log/cron/backup.log 2>&1
```

### Add New Job

1. Create script in `src/cron/scripts/`:
   ```bash
   #!/bin/bash
   echo "My custom job"
   ```

2. Add to `crontab`:
   ```cron
   0 12 * * * /scripts/my_custom_job.sh >> /var/log/cron/custom.log 2>&1
   ```

3. Rebuild container:
   ```bash
   docker-compose up -d --build cron
   ```

## Backup Retention

By default, old backups accumulate in `/tmp`. To implement retention:

Add to `crontab`:
```cron
# Delete backups older than 7 days (runs daily at 5 AM)
0 5 * * * find /tmp -name "pg_backup_*.sql" -mtime +7 -delete
```

## Migration from Host Crontab

To remove the old host crontab:

```bash
# Backup current crontab
crontab -l > ~/crontab_backup.txt

# Remove all cron jobs
crontab -r

# Verify removal
crontab -l
```

The dockerized cron service will now handle all scheduled tasks.

## Security Notes

⚠️ **Docker Socket Access**: This container has full access to the Docker daemon. Only run in trusted environments.

⚠️ **AWS Credentials**: Ensure `.env` file is not committed to version control. Add to `.gitignore`.

⚠️ **Network Access**: Container can make outbound HTTP requests to ntfy.sh. Ensure your firewall allows this if needed.

## Support

For issues or questions:
- Check logs: `docker-compose logs cron`
- Review cron execution: `cat /var/log/cron/*.log`
- Test scripts manually before scheduling
