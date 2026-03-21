# Rollback Checklist

Quick reference checklist for production rollbacks.

## 🚨 Emergency Rollback (Use This First!)

```bash
# One-command emergency rollback
./scripts/rollback/emergency_rollback.sh

# Or rollback to specific commit
./scripts/rollback/emergency_rollback.sh 03db23c
```

**The script will:**
- ✅ Create all necessary backups
- ✅ Stop containers safely
- ✅ Rollback code using git revert (safe method)
- ✅ Rebuild and restart containers
- ✅ Run verification tests
- ✅ Provide detailed report

---

## Pre-Rollback Checklist

Before starting rollback:

### 1. Assess the Situation
- [ ] Identify the specific problem
- [ ] Confirm it's critical enough to rollback
- [ ] Identify last known good commit
- [ ] Notify team of pending rollback

### 2. Gather Information
```bash
# Save current state
docker-compose logs ws > logs_before_rollback_$(date +%Y%m%d_%H%M%S).txt
docker stats --no-stream > stats_before_rollback_$(date +%Y%m%d_%H%M%S).txt
git log --oneline -10 > git_log_before_rollback_$(date +%Y%m%d_%H%M%S).txt
```

### 3. Create Backups
- [ ] Database backup created
- [ ] Current commit saved
- [ ] Logs captured
- [ ] Git branch backup created

---

## During Rollback

### Manual Rollback Steps

If not using the automated script:

#### 1. Stop Services
```bash
docker-compose down
```

#### 2. Backup Current State
```bash
# Backup database
docker exec -t $(docker ps -qf "name=db-1") pg_dump -U new_docker_user -d new_docker_db > \
    /tmp/backup_$(date +%Y%m%d_%H%M%S).sql

# Create Git branch backup
git branch backup-$(date +%Y%m%d-%H%M%S)

# Save current commit
git rev-parse HEAD > /tmp/commit_before_rollback.txt
```

#### 3. Perform Rollback
```bash
# Option A: Safe revert (for pushed commits)
git revert HEAD --no-edit

# Option B: Reset (for local commits only)
git reset --soft HEAD~1
```

#### 4. Rebuild & Restart
```bash
docker-compose up -d --build
```

#### 5. Wait for Startup
```bash
# Wait 30 seconds for containers to start
sleep 30
```

---

## Post-Rollback Checklist

### Immediate Verification (First 5 Minutes)

Run the automated test suite:
```bash
./scripts/rollback/test_after_rollback.sh
```

Or manual checks:

#### 1. Container Health
- [ ] All containers running
  ```bash
  docker-compose ps
  ```

#### 2. Endpoints Responding
- [ ] Health endpoint works
  ```bash
  curl http://localhost:8000/
  ```
- [ ] Main workflow works
  ```bash
  curl http://localhost:8000/run-task/Ogre
  ```

#### 3. Database Accessible
- [ ] Can query database
  ```bash
  docker-compose exec db psql -U new_docker_user -d new_docker_db -c "SELECT COUNT(*) FROM listed_ads;"
  ```

#### 4. No Critical Errors in Logs
- [ ] Check WS logs
  ```bash
  docker-compose logs ws | tail -50
  ```
- [ ] Check for OOM errors
  ```bash
  docker-compose logs ws | grep -i "oom\|out of memory"
  ```

#### 5. Memory Within Limits
- [ ] Check memory usage
  ```bash
  docker stats --no-stream | grep ws
  ```
  Expected: < 500 MB

### Short-term Monitoring (First Hour)

- [ ] Monitor every 10 minutes for:
  - Container status
  - Memory usage
  - Error logs
  - Response times

- [ ] Document observations
  ```bash
  # Create monitoring log
  echo "$(date): Memory check" >> rollback_monitoring.log
  docker stats --no-stream >> rollback_monitoring.log
  ```

### Medium-term Verification (First 24 Hours)

- [ ] Run full regression tests
- [ ] Check database integrity
  ```bash
  docker-compose exec db psql -U new_docker_user -d new_docker_db -c "\dt+"
  ```
- [ ] Verify cron jobs executed
  ```bash
  docker-compose logs cron | grep -i "backup\|s3"
  ```
- [ ] Monitor memory over time
- [ ] Check for any anomalies in application behavior

---

## Recovery Checklist

If rollback failed or made things worse:

### 1. Restore from Backup Branch
```bash
# Find backup branch
git branch | grep backup

# Switch to backup branch
git checkout backup-before-rollback-YYYYMMDD-HHMMSS

# Create recovery branch
git checkout -b emergency-recovery
```

### 2. Restore Database (if needed)
```bash
# Find backup
ls -lh /tmp/pg_backup_*.sql

# Restore
docker-compose stop ws
docker exec -i $(docker ps -qf "name=db-1") psql -U new_docker_user -d new_docker_db < \
    /tmp/pg_backup_YYYYMMDD_HHMMSS.sql
docker-compose start ws
```

### 3. Escalate
- [ ] Contact team lead
- [ ] Document all actions taken
- [ ] Prepare detailed incident report

---

## Documentation Checklist

After successful rollback:

### Immediate (Within 1 Hour)
- [ ] Update team via Slack/email
- [ ] Create incident ticket
- [ ] Document root cause (if known)

### Short-term (Within 24 Hours)
- [ ] Write incident report
  - What happened
  - When detected
  - Action taken
  - Impact to users
  - Root cause
  - Prevention measures

### Medium-term (Within 1 Week)
- [ ] Post-mortem meeting
- [ ] Update rollback procedures (if needed)
- [ ] Implement preventive measures
- [ ] Update testing procedures

---

## Quick Decision Matrix

| Severity | Rollback? | Method | Urgency |
|----------|-----------|--------|---------|
| **Critical** - App down, data loss | ✅ YES | Automated script | Immediate |
| **High** - OOM crashes, major bugs | ✅ YES | Automated script | <15 min |
| **Medium** - Performance issues | 🟡 Maybe | Manual/planned | <1 hour |
| **Low** - Minor bugs | ❌ NO | Fix forward | Next deploy |

---

## Emergency Contacts

**Before rollback, notify:**
- Team Lead: [Contact]
- DevOps: [Contact]
- On-call Engineer: [Contact]

**Escalation path:**
1. Attempt automated rollback
2. If fails, attempt manual rollback
3. If still fails, restore from backup
4. If all fails, escalate to senior engineer

---

## Common Issues & Solutions

### Issue: Revert has conflicts
```bash
# Resolve conflicts manually
vim <conflicted-file>
git add <conflicted-file>
git revert --continue
```

### Issue: Container won't start after rollback
```bash
# Check logs
docker-compose logs ws

# Try rebuilding without cache
docker-compose build --no-cache ws
docker-compose up -d ws
```

### Issue: Database connection fails
```bash
# Check database container
docker-compose ps db

# Restart database
docker-compose restart db

# Wait 10 seconds
sleep 10

# Test connection
docker-compose exec db psql -U new_docker_user -d new_docker_db -c "SELECT 1;"
```

### Issue: Memory still high after rollback
```bash
# Restart containers to clear memory
docker-compose restart ws

# Check if memory reduces
docker stats --no-stream | grep ws
```

---

## Useful Commands Reference

```bash
# View recent commits
git log --oneline -10

# See what changed in a commit
git show <commit-hash>

# View current branch
git branch --show-current

# View unpushed commits
git log origin/$(git branch --show-current)..HEAD

# Create quick backup
git branch backup-now

# View container resource usage
docker stats

# Follow logs in real-time
docker-compose logs -f ws

# Restart single service
docker-compose restart ws

# Rebuild single service
docker-compose up -d --build ws

# Execute command in container
docker-compose exec ws <command>
```

---

## Success Criteria

Rollback is successful when:

- ✅ All containers running and healthy
- ✅ All critical endpoints responding
- ✅ No errors in logs
- ✅ Memory usage normal (< 500 MB)
- ✅ Database accessible and intact
- ✅ Cron jobs functioning (if applicable)
- ✅ Application performing as expected
- ✅ No user impact

---

## Remember

1. **Safety First**: Always create backups before rollback
2. **Communicate**: Keep team informed throughout process
3. **Document**: Record all actions and observations
4. **Test Thoroughly**: Don't rush the verification phase
5. **Learn**: Conduct post-mortem to prevent recurrence

---

## Additional Resources

- **Full Guide**: `docs/ROLLBACK_GUIDE.md`
- **Automated Script**: `scripts/rollback/emergency_rollback.sh`
- **Test Suite**: `scripts/rollback/test_after_rollback.sh`
- **Git Revert Docs**: https://git-scm.com/docs/git-revert
- **Docker Compose Docs**: https://docs.docker.com/compose/
