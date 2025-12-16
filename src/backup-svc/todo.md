# Database Backup Service - Implementation Tasks

## Critical Fixes Required

### 1. Create Missing cronfile
- [ ] Create `src/backup-svc/cronfile` with cron schedule
- [ ] Define backup frequency (e.g., daily at 2 AM)
- [ ] Ensure proper cron syntax and logging

### 2. Fix Hardcoded Values in backup_upload.py
- [ ] Replace `DB-USER` with environment variable `${POSTGRES_USER}`
- [ ] Replace `DB-NAME` with environment variable `${POSTGRES_DB}`
- [ ] Replace `"your-region"` with environment variable `${AWS_REGION}`
- [ ] Replace `"bucket-name-pg-backups"` with environment variable `${S3_BUCKET}`
- [ ] Add `PGPASSWORD` environment variable for pg_dump authentication

### 3. Add Error Handling and Logging
- [ ] Add try/except blocks around pg_dump subprocess call
- [ ] Add try/except blocks around S3 upload
- [ ] Implement proper logging with timestamps
- [ ] Log to both stdout and `/var/log/cron.log`
- [ ] Add success/failure notifications

### 4. Update docker-compose.yml
- [ ] Add all required environment variables
- [ ] Add POSTGRES_USER, POSTGRES_DB, POSTGRES_PASSWORD
- [ ] Add AWS_REGION, S3_BUCKET
- [ ] Fix dependency on `db` service (ensure network compatibility)
- [ ] Consider health checks for backup service

## Testing Tasks

### Phase 1: Unit Testing
- [ ] Create `tests/test_backup_service.py`
- [ ] Mock boto3 S3 client to test upload_to_s3()
- [ ] Mock subprocess to test backup_postgres()
- [ ] Test error handling scenarios
- [ ] Test filename generation with different dates

### Phase 2: Integration Testing
- [ ] Build Docker image: `docker build -t backup-svc:test src/backup-svc/`
- [ ] Test manual one-time backup run
- [ ] Verify database connectivity with pg_dump
- [ ] Verify S3 upload functionality
- [ ] Test cron scheduling

### Phase 3: End-to-End Validation
- [ ] Deploy service with docker-compose
- [ ] Verify service starts successfully
- [ ] Verify pg_dump creates valid SQL file
- [ ] Verify file is uploaded to S3
- [ ] Verify backup file exists in S3 bucket
- [ ] Verify cron job runs at scheduled time
- [ ] Test backup restoration process
- [ ] Verify data integrity after restoration

## Integration with Main Project

### 5. Integrate with Main docker-compose.yml
- [ ] Add backup-svc to root `docker-compose.yml`
- [ ] Ensure proper network configuration
- [ ] Add to multi-city deployment scripts if needed
- [ ] Update `.env.prod` template with backup service variables

### 6. Update Documentation
- [ ] Update CLAUDE.md with backup service architecture
- [ ] Document backup service configuration
- [ ] Add backup service commands to Makefile
- [ ] Document restoration procedure
- [ ] Add troubleshooting section for backup service

### 7. CI/CD Integration
- [ ] Add backup service tests to CI workflow
- [ ] Consider backup verification in CI
- [ ] Update deployment scripts for production

## Optional Enhancements
- [ ] Add backup retention policy (delete old backups)
- [ ] Add compression for backup files (gzip)
- [ ] Add email notifications on backup success/failure
- [ ] Add metrics/monitoring integration
- [ ] Add backup verification step (test restore)
- [ ] Support incremental backups
