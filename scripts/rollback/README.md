# Rollback Scripts

Automated scripts for safe production rollbacks.

## Quick Start

### Emergency Rollback (Recommended)

```bash
# Rollback to previous commit
./emergency_rollback.sh

# Rollback to specific commit
./emergency_rollback.sh 03db23c
```

### Test After Rollback

```bash
# Run comprehensive test suite
./test_after_rollback.sh
```

---

## Scripts Overview

### 1. emergency_rollback.sh

**Purpose**: Automated, safe rollback with all necessary checks and backups

**Features**:
- ✅ Pre-rollback validation
- ✅ Automatic backups (code, database, logs)
- ✅ Smart rollback method selection (revert vs reset)
- ✅ Container rebuild and restart
- ✅ Post-rollback verification
- ✅ Detailed reporting

**Usage**:
```bash
# Rollback to previous commit (HEAD~1)
./emergency_rollback.sh

# Rollback to specific commit
./emergency_rollback.sh <commit-hash>

# Example: Rollback to commit 03db23c
./emergency_rollback.sh 03db23c
```

**What it does**:
1. Validates target commit exists
2. Shows current vs target commit
3. Creates backups:
   - Git branch backup
   - Database backup (if running)
   - Container logs
   - Current commit hash
4. Stops containers
5. Performs Git rollback (revert or reset based on push status)
6. Rebuilds and restarts containers
7. Runs basic verification tests
8. Provides detailed summary

**Output**:
- Backups saved to: `/tmp/rollback_backups/`
- Backup branch: `backup-before-rollback-YYYYMMDD-HHMMSS`
- Console output with color-coded status

---

### 2. test_after_rollback.sh

**Purpose**: Comprehensive testing suite to verify rollback success

**Features**:
- ✅ 10 test categories
- ✅ Critical vs warning classification
- ✅ Detailed test report
- ✅ Pass/fail/warning counts
- ✅ Actionable recommendations

**Usage**:
```bash
# Run all tests
./test_after_rollback.sh

# Test report saved to: test_report_YYYYMMDD_HHMMSS.txt
```

**Test Categories**:
1. **Container Health** - All containers running
2. **Network Connectivity** - Ports accessible, inter-container networking
3. **Application Endpoints** - Health check, workflow endpoints
4. **Database Checks** - Connection, tables, data integrity
5. **Memory Checks** - Memory usage within limits
6. **Log Checks** - No critical errors or OOM events
7. **File System Checks** - Volumes, backups present
8. **Cron Jobs** - Cron services functioning (if applicable)
9. **Git Status** - Current commit, clean working directory
10. **Performance Test** - Response time benchmarks

**Exit Codes**:
- `0`: All tests passed
- `1`: One or more critical tests failed

**Output**:
- Console: Color-coded test results
- File: `test_report_YYYYMMDD_HHMMSS.txt`

---

## Common Scenarios

### Scenario 1: Production Crash

```bash
# Step 1: Emergency rollback
./emergency_rollback.sh

# Step 2: Wait for script to complete (~2-3 minutes)

# Step 3: Run tests
./test_after_rollback.sh

# Step 4: Monitor for 30 minutes
watch -n 60 'docker stats --no-stream'
```

### Scenario 2: Memory Leak Detected

```bash
# Step 1: Rollback to last known good commit
./emergency_rollback.sh 03db23c

# Step 2: Verify memory returns to normal
docker stats --no-stream | grep ws

# Step 3: Run full test suite
./test_after_rollback.sh

# Step 4: Monitor memory over time
while true; do
    echo "$(date): $(docker stats --no-stream | grep ws)"
    sleep 300  # Check every 5 minutes
done
```

### Scenario 3: Database Issues

```bash
# Step 1: Check database backup exists
ls -lh /tmp/pg_backup_*.sql

# Step 2: Rollback code
./emergency_rollback.sh

# Step 3: Restore database (if needed)
docker-compose stop ws
docker exec -i $(docker ps -qf "name=db-1") psql -U new_docker_user -d new_docker_db < \
    /tmp/pg_backup_YYYYMMDD_HHMMSS.sql
docker-compose start ws

# Step 4: Test
./test_after_rollback.sh
```

### Scenario 4: Rollback Failed

```bash
# Find backup branch
git branch | grep backup

# Restore from backup
git checkout backup-before-rollback-YYYYMMDD-HHMMSS
git checkout -b emergency-recovery

# Rebuild containers
docker-compose down
docker-compose up -d --build

# Test
./test_after_rollback.sh
```

---

## Script Workflow

### Emergency Rollback Flow

```
Start
  ↓
[Pre-Rollback Checks]
  - Validate Git repo
  - Check target commit exists
  - Show commits
  ↓
[User Confirmation]
  - Proceed? (yes/no)
  ↓
[Create Backups]
  - Commit hash
  - Git branch
  - Database
  - Logs
  ↓
[Stop Containers]
  - docker-compose down
  ↓
[Git Rollback]
  - Check if pushed
  - Use revert (pushed) or reset (not pushed)
  ↓
[Rebuild & Restart]
  - docker-compose up -d --build
  - Wait 30 seconds
  ↓
[Verification]
  - Container status
  - Health check
  - Memory check
  - Log check
  ↓
[Summary Report]
  - Previous vs current commit
  - Backup locations
  - Verification results
  - Next steps
  ↓
End
```

### Test Suite Flow

```
Start
  ↓
[Initialize]
  - Create test report file
  - Reset counters
  ↓
[Run Test Categories]
  1. Container Health
  2. Network
  3. Endpoints
  4. Database
  5. Memory
  6. Logs
  7. File System
  8. Cron
  9. Git Status
  10. Performance
  ↓
  [Each Test]
    - Execute command
    - Record result (pass/fail/warning)
    - Update counters
  ↓
[Generate Report]
  - Summary statistics
  - Detailed results
  - Recommendations
  ↓
[Exit]
  - Return 0 (success) or 1 (failure)
```

---

## Configuration

### Environment Variables

No environment variables required - scripts auto-detect:
- Docker containers
- Git repository
- Database credentials (from docker-compose)

### Customization

Edit scripts to customize:

**Backup location** (in `emergency_rollback.sh`):
```bash
BACKUP_DIR="/tmp/rollback_backups"  # Change this path
```

**Database credentials** (in both scripts):
```bash
# Default:
psql -U new_docker_user -d new_docker_db

# Customize:
psql -U your_user -d your_db
```

**Test timeout** (in `test_after_rollback.sh`):
```bash
timeout 120 curl ...  # Change timeout (seconds)
```

---

## Troubleshooting

### Script fails with "Not in a git repository"

**Solution**: Ensure you're in the project root directory
```bash
cd /path/to/project
./scripts/rollback/emergency_rollback.sh
```

### Script fails with "Target commit does not exist"

**Solution**: Check commit hash is correct
```bash
git log --oneline -10  # View recent commits
./emergency_rollback.sh <correct-hash>
```

### Database backup fails

**Cause**: Database container not running

**Solution**: Start database first
```bash
docker-compose up -d db
sleep 10  # Wait for startup
./emergency_rollback.sh
```

### Tests fail after rollback

**Check**: Review test report for specific failures
```bash
cat test_report_*.txt
```

**Common issues**:
1. Containers not fully started - wait 30 more seconds
2. Database connection issues - restart db container
3. Memory still high - restart ws container

---

## Best Practices

1. **Always run test suite after rollback**
   ```bash
   ./test_after_rollback.sh
   ```

2. **Monitor for at least 30 minutes**
   ```bash
   watch -n 60 'docker stats --no-stream'
   ```

3. **Keep backups for 7 days**
   ```bash
   # Cleanup old backups
   find /tmp/rollback_backups -mtime +7 -delete
   ```

4. **Document every rollback**
   - What went wrong
   - What commit was bad
   - What was rolled back to
   - Test results
   - Lessons learned

5. **Never delete backup branches immediately**
   - Keep for at least 30 days
   - Only delete after thorough verification

---

## Safety Features

Both scripts include:

✅ **Confirmation prompts** - Prevent accidental rollbacks
✅ **Automatic backups** - Can restore if rollback fails
✅ **Smart rollback** - Uses safe method (revert) for pushed commits
✅ **Verification tests** - Ensures rollback succeeded
✅ **Detailed logging** - Track all actions taken
✅ **Color-coded output** - Easy to spot issues
✅ **Exit codes** - Integration with CI/CD pipelines

---

## Integration with CI/CD

### GitLab CI Example

```yaml
rollback:
  stage: emergency
  when: manual
  script:
    - ./scripts/rollback/emergency_rollback.sh
    - ./scripts/rollback/test_after_rollback.sh
  only:
    - main
    - production
```

### GitHub Actions Example

```yaml
name: Emergency Rollback
on:
  workflow_dispatch:
    inputs:
      commit:
        description: 'Commit hash to rollback to'
        required: false

jobs:
  rollback:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Rollback
        run: |
          ./scripts/rollback/emergency_rollback.sh ${{ github.event.inputs.commit }}
      - name: Test
        run: ./scripts/rollback/test_after_rollback.sh
```

---

## Support

For issues or questions:
- **Documentation**: `docs/ROLLBACK_GUIDE.md`
- **Checklist**: `docs/ROLLBACK_CHECKLIST.md`
- **Script Source**: Review inline comments in scripts

---

## Version History

- **v1.0.0** (2026-01-17): Initial release
  - Emergency rollback automation
  - Comprehensive test suite
  - Safety checks and backups
