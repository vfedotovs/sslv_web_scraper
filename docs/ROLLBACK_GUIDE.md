# Production Rollback Guide

Complete guide for safely rolling back to a previous commit when bugs are detected in production.

## Table of Contents

1. [Overview](#overview)
2. [Pre-Rollback Assessment](#pre-rollback-assessment)
3. [Rollback Methods](#rollback-methods)
4. [Detailed Rollback Procedures](#detailed-rollback-procedures)
5. [Testing & Verification](#testing--verification)
6. [Database Rollback Considerations](#database-rollback-considerations)
7. [Emergency Rollback (Quick)](#emergency-rollback-quick)
8. [Post-Rollback Actions](#post-rollback-actions)

---

## Overview

### When to Rollback

Rollback immediately if:
- ✅ Application crashes or fails to start
- ✅ Critical functionality is broken
- ✅ Memory leaks cause OOM crashes
- ✅ Data corruption or loss detected
- ✅ Security vulnerabilities introduced

### Rollback Methods Comparison

| Method | Safety | Use Case | Preserves History | Reversible |
|--------|--------|----------|-------------------|------------|
| **git revert** | ✅ Safest | Production | ✅ Yes | ✅ Yes |
| **git reset --soft** | 🟡 Safe | Pre-push local | ✅ Yes (with reflog) | ✅ Yes |
| **git reset --hard** | ⚠️ Dangerous | Emergency | ❌ No | 🟡 Maybe (reflog) |
| **Redeploy old tag** | ✅ Safe | Docker only | ✅ Yes | ✅ Yes |

**Recommendation:** Use `git revert` for production rollbacks.

---

## Pre-Rollback Assessment

### Step 1: Identify the Problem

**Checklist:**
```bash
# 1. Check container status
docker-compose ps

# 2. Check recent logs
docker-compose logs --tail=100 ws
docker-compose logs --tail=100 db

# 3. Check for OOM errors
docker-compose logs ws | grep -i "out of memory\|oom\|killed"

# 4. Check memory usage
docker stats --no-stream

# 5. Test critical endpoints
curl http://localhost:8000/
curl http://localhost:8000/run-task/Ogre
```

**Document the issue:**
```bash
# Save logs for analysis
docker-compose logs ws > logs_before_rollback_$(date +%Y%m%d_%H%M%S).txt
docker-compose logs db >> logs_before_rollback_$(date +%Y%m%d_%H%M%S).txt
```

---

### Step 2: Identify Last Known Good Commit

**Check recent commits:**
```bash
git log --oneline -10
```

Example output:
```
3aa9a0a (HEAD -> dev-1.5.10) (ws):oom bugfix - safer --limit-max-requests 30
9b9b9e6 (ws):oom bugfix - memory optimizations in file_downloader.py
92221dc (ws):oom bugfix - gc in main.py
ce9fcd8 (ws):oom bugfix - remove pdf_creator
8debdfa (ws):oom bug - memory usage logging
03db23c (origin/dev-1.5.10) Fix ws container restart ← LAST KNOWN GOOD
```

**Check what changed in suspect commit:**
```bash
# View changes in current commit
git show HEAD

# Compare with previous commit
git diff HEAD~1 HEAD

# See files changed
git diff --name-only HEAD~1 HEAD
```

---

### Step 3: Create Backup Before Rollback

```bash
# 1. Backup database
docker-compose exec cron /scripts/backup_db.sh

# Or manually:
docker exec -t $(docker ps -qf "name=db-1") pg_dump -U new_docker_user -d new_docker_db > \
    /tmp/emergency_backup_$(date +%Y%m%d_%H%M%S).sql

# 2. Backup current code state
git branch backup-before-rollback-$(date +%Y%m%d-%H%M%S)

# 3. Note current commit
git rev-parse HEAD > /tmp/commit_before_rollback.txt
```

---

## Rollback Methods

### Method 1: Git Revert (Recommended for Production)

**Best for:** Production environments, shared branches, preserving history

**How it works:** Creates a new commit that undoes changes from a bad commit

**Advantages:**
- ✅ Preserves full Git history
- ✅ Safe for shared branches
- ✅ Easy to understand what was reverted
- ✅ Can be reverted again if needed

**Disadvantages:**
- ❌ Requires creating a new commit
- ❌ May have merge conflicts

---

### Method 2: Git Reset --soft (Local Development)

**Best for:** Local branches not yet pushed, staging area preservation

**How it works:** Moves HEAD pointer but keeps changes in staging area

**Advantages:**
- ✅ Can modify and recommit
- ✅ No changes lost
- ✅ Clean history

**Disadvantages:**
- ⚠️ Rewrites history (don't use on pushed commits)
- ⚠️ Can confuse team members

---

### Method 3: Git Reset --hard (Emergency)

**Best for:** Emergency situations, local-only changes

**How it works:** Completely removes commits and changes

**Advantages:**
- ✅ Fast and complete rollback
- ✅ Clean working directory

**Disadvantages:**
- 🔴 **DESTRUCTIVE** - permanently deletes changes
- 🔴 Cannot be undone (except via reflog)
- 🔴 Never use on pushed commits

---

### Method 4: Redeploy Previous Docker Tag

**Best for:** Docker-only issues, no code rollback needed

**How it works:** Deploy a previous Docker image version

**Advantages:**
- ✅ Fastest rollback method
- ✅ No Git changes needed
- ✅ Easy to test before committing

---

## Detailed Rollback Procedures

---

## Procedure A: Git Revert (Production Rollback)

**Use when:** Bug detected in production, need to maintain history

### Step-by-Step:

#### 1. Identify commits to revert

```bash
# Show last 5 commits
git log --oneline -5

# Example output:
# 3aa9a0a (HEAD) Bad commit - introduced bug
# 9b9b9e6 Another change
# 92221dc Previous change
# 03db23c Last known good commit
```

#### 2. Revert the bad commit(s)

**Option A: Revert single commit**
```bash
# Revert the most recent commit
git revert HEAD

# Or revert specific commit by hash
git revert 3aa9a0a
```

**Option B: Revert multiple commits**
```bash
# Revert last 2 commits (in reverse order)
git revert HEAD~1..HEAD

# Or specify range
git revert 9b9b9e6..3aa9a0a
```

**Option C: Revert without committing (to test first)**
```bash
# Stage revert changes but don't commit
git revert --no-commit HEAD

# Test the changes
docker-compose up -d --build

# If good, commit the revert
git commit -m "Revert: rollback OOM fixes due to production issues"

# If bad, abort
git revert --abort
```

#### 3. Resolve conflicts (if any)

```bash
# If revert has conflicts, Git will notify you
# Edit conflicted files, then:
git add .
git revert --continue
```

#### 4. Push the revert

```bash
git push origin dev-1.5.10
```

#### 5. Deploy reverted code

```bash
# Rebuild and restart containers
docker-compose down
docker-compose up -d --build

# Verify deployment
docker-compose ps
docker-compose logs -f ws
```

---

## Procedure B: Git Reset --soft (Pre-Push Local Rollback)

**Use when:** Changes not yet pushed, want to modify before recommitting

### Step-by-Step:

#### 1. Check if commits are pushed

```bash
# See unpushed commits
git log origin/dev-1.5.10..HEAD

# If output shows commits, they're NOT pushed yet - safe to reset
```

#### 2. Reset to target commit

```bash
# Reset to last known good commit (keeps changes staged)
git reset --soft 03db23c

# Verify
git status  # Should show changes in staging area
git log --oneline -5  # Should show HEAD at 03db23c
```

#### 3. Review staged changes

```bash
# See what changes are staged
git diff --cached

# If you want to keep some changes, unstage specific files
git restore --staged src/ws/Dockerfile
```

#### 4. Make corrections and recommit

```bash
# Make necessary fixes
vim src/ws/app/main.py

# Commit with corrected changes
git commit -m "Fix: corrected OOM fixes with proper testing"
```

#### 5. Deploy

```bash
docker-compose down
docker-compose up -d --build
```

---

## Procedure C: Git Reset --hard (Emergency Rollback)

**⚠️ DANGER: Only use in emergencies on local-only commits**

### Step-by-Step:

#### 1. **CRITICAL: Verify commits are NOT pushed**

```bash
# Check remote
git log origin/dev-1.5.10..HEAD

# If this shows commits, DO NOT USE --hard!
# Use git revert instead
```

#### 2. Create safety backup

```bash
# Create a backup branch at current state
git branch emergency-backup-$(date +%Y%m%d-%H%M%S)

# Or save commit hash
git rev-parse HEAD > /tmp/last_commit_before_reset.txt
```

#### 3. Reset to target commit

```bash
# Reset to last known good commit (DESTRUCTIVE)
git reset --hard 03db23c

# Verify
git log --oneline -5
git status  # Should show "nothing to commit, working tree clean"
```

#### 4. Force push (if absolutely necessary)

```bash
# ⚠️ WARNING: Only if you're sure no one else has pulled these commits
git push --force origin dev-1.5.10
```

#### 5. Deploy

```bash
docker-compose down
docker-compose up -d --build
```

#### 6. Recovery if needed

```bash
# If you need to recover the reset commits
git reflog  # Find the commit hash

# Example output:
# 3aa9a0a HEAD@{0}: reset: moving to 03db23c
# 3aa9a0a HEAD@{1}: commit: Bad commit

# Recover
git reset --hard 3aa9a0a  # Or HEAD@{1}
```

---

## Procedure D: Docker-Only Rollback (No Git Changes)

**Use when:** Only Docker/container issues, code is fine

### Step-by-Step:

#### 1. Find last working Docker image

```bash
# List recent images
docker images | grep ws

# Example output:
# ws    latest    abc123    10 mins ago   500MB
# ws    <none>    def456    2 hours ago   480MB  ← Last known good
```

#### 2. Tag the good image

```bash
# Tag the working image
docker tag def456 ws:rollback-working
```

#### 3. Update docker-compose to use specific image

Edit `docker-compose.yml`:
```yaml
ws:
  # build: ./src/ws  # Comment out build
  image: ws:rollback-working  # Use specific image
```

#### 4. Restart with rollback image

```bash
docker-compose down
docker-compose up -d

# Verify
docker-compose ps
docker-compose logs -f ws
```

#### 5. If working, investigate code

```bash
# Find what changed between images
docker history ws:latest
docker history ws:rollback-working
```

---

## Testing & Verification

### Post-Rollback Testing Checklist

**1. Container Health**
```bash
# ✅ All containers running
docker-compose ps

# Expected: All containers "Up"
```

**2. Application Endpoints**
```bash
# ✅ Health check
curl http://localhost:8000/
# Expected: {"FastAPI server is ready !!!"}

# ✅ Main workflow
curl http://localhost:8000/run-task/Ogre
# Expected: Success response (may take 30-60 seconds)
```

**3. Memory Monitoring**
```bash
# ✅ Check memory usage
docker stats --no-stream | grep ws

# Expected: Memory under 500 MB after request
```

**4. Database Connectivity**
```bash
# ✅ Database accessible
docker-compose exec db psql -U new_docker_user -d new_docker_db -c "SELECT COUNT(*) FROM listed_ads;"

# Expected: Returns count without errors
```

**5. Logs Review**
```bash
# ✅ No errors in logs
docker-compose logs ws | tail -50

# Expected: No ERROR, OOM, or crash messages
```

**6. Cron Jobs (if applicable)**
```bash
# ✅ Cron container running
docker-compose exec cron ps aux | grep cron

# ✅ Test backup
docker-compose exec cron /scripts/backup_db.sh

# Expected: Backup created successfully
```

**7. S3 Integration**
```bash
# ✅ Test S3 upload
docker-compose exec cron /scripts/upload_backup_to_s3.sh

# Expected: Upload successful
```

**8. Monitoring Alerts**
```bash
# ✅ Test notifications
docker-compose exec cron /scripts/send_container_uptime.sh

# Expected: Message sent to ntfy.sh
```

---

### Detailed Test Script

Create `scripts/test_after_rollback.sh`:

```bash
#!/bin/bash
# Comprehensive post-rollback testing script

set -e

echo "========================================="
echo "Post-Rollback Testing Script"
echo "Started: $(date)"
echo "========================================="

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Test counter
PASSED=0
FAILED=0

# Function to test and report
test_item() {
    local test_name="$1"
    local test_command="$2"

    echo -n "Testing: $test_name... "

    if eval "$test_command" > /dev/null 2>&1; then
        echo -e "${GREEN}PASSED${NC}"
        ((PASSED++))
        return 0
    else
        echo -e "${RED}FAILED${NC}"
        ((FAILED++))
        return 1
    fi
}

echo ""
echo "1. Container Health Checks"
echo "----------------------------"
test_item "DB container running" "docker-compose ps db | grep -q 'Up'"
test_item "WS container running" "docker-compose ps ws | grep -q 'Up'"
test_item "Cron container running" "docker-compose ps cron | grep -q 'Up'"

echo ""
echo "2. Application Endpoints"
echo "-------------------------"
test_item "Health endpoint" "curl -f http://localhost:8000/"
test_item "Main workflow endpoint (may take 60s)" "timeout 120 curl -f http://localhost:8000/run-task/Ogre"

echo ""
echo "3. Database Checks"
echo "-------------------"
test_item "Database connection" "docker-compose exec -T db psql -U new_docker_user -d new_docker_db -c 'SELECT 1;'"
test_item "listed_ads table exists" "docker-compose exec -T db psql -U new_docker_user -d new_docker_db -c 'SELECT COUNT(*) FROM listed_ads;'"

echo ""
echo "4. Memory Checks"
echo "-----------------"
WS_MEMORY=$(docker stats --no-stream --format "{{.MemUsage}}" | grep ws | awk -F'/' '{print $1}' | sed 's/MiB//')
echo "WS container memory: ${WS_MEMORY} MB"
if [ "$WS_MEMORY" -lt 1000 ]; then
    echo -e "${GREEN}Memory within limits${NC}"
    ((PASSED++))
else
    echo -e "${RED}Memory too high!${NC}"
    ((FAILED++))
fi

echo ""
echo "5. Log Checks"
echo "--------------"
if docker-compose logs ws | tail -100 | grep -qi "error\|exception\|traceback"; then
    echo -e "${RED}Errors found in logs${NC}"
    ((FAILED++))
else
    echo -e "${GREEN}No errors in logs${NC}"
    ((PASSED++))
fi

echo ""
echo "6. Cron Jobs"
echo "-------------"
test_item "Cron daemon running" "docker-compose exec -T cron ps aux | grep -q crond"
test_item "Database backup script" "docker-compose exec -T cron /scripts/backup_db.sh"

echo ""
echo "========================================="
echo "Test Results"
echo "========================================="
echo -e "${GREEN}Passed: $PASSED${NC}"
echo -e "${RED}Failed: $FAILED${NC}"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ All tests passed! Rollback successful.${NC}"
    exit 0
else
    echo -e "${RED}❌ Some tests failed. Review above output.${NC}"
    exit 1
fi
```

**Make executable and run:**
```bash
chmod +x scripts/test_after_rollback.sh
./scripts/test_after_rollback.sh
```

---

## Database Rollback Considerations

### When Database Schema Changed

If the bad commit included database migrations:

#### Option 1: Restore from Backup

```bash
# 1. Stop application
docker-compose stop ws

# 2. Restore database from backup
docker exec -i $(docker ps -qf "name=db-1") psql -U new_docker_user -d new_docker_db < \
    /tmp/backup_before_change.sql

# 3. Verify restoration
docker-compose exec db psql -U new_docker_user -d new_docker_db -c "\dt"

# 4. Start application
docker-compose start ws
```

#### Option 2: Manual Schema Rollback

```bash
# 1. Identify schema changes
git show HEAD:src/db/schema.sql > /tmp/new_schema.sql
git show HEAD~1:src/db/schema.sql > /tmp/old_schema.sql
diff /tmp/old_schema.sql /tmp/new_schema.sql

# 2. Create rollback SQL script
# (Manually write SQL to undo changes)

# 3. Execute rollback
docker-compose exec db psql -U new_docker_user -d new_docker_db -f /path/to/rollback.sql
```

### Database Backup Best Practices

**Before any deployment:**
```bash
# Automated backup via cron
docker-compose exec cron /scripts/backup_db.sh

# Manual backup with timestamp
docker exec -t $(docker ps -qf "name=db-1") pg_dump -U new_docker_user -d new_docker_db > \
    /tmp/pre_deploy_backup_$(date +%Y%m%d_%H%M%S).sql
```

---

## Emergency Rollback (Quick Reference)

**⚡ 5-Minute Emergency Rollback**

```bash
# 1. Stop containers
docker-compose down

# 2. Revert last commit (if on Git)
git revert HEAD --no-edit

# 3. Rebuild and restart
docker-compose up -d --build

# 4. Verify
docker-compose ps
curl http://localhost:8000/

# 5. Push revert
git push origin dev-1.5.10
```

**Or use the emergency script (see below)**

---

## Post-Rollback Actions

### 1. Notify Team

```bash
# Send Slack/email notification
"ALERT: Production rolled back from commit 3aa9a0a to 03db23c due to [REASON].
All systems operational. Investigating root cause."
```

### 2. Document Incident

Create incident report:
```markdown
## Incident Report: Production Rollback - 2026-01-17

**Summary:** Rolled back OOM fixes due to unexpected memory behavior

**Timeline:**
- 15:00 UTC: Deployment of commit 3aa9a0a
- 15:30 UTC: OOM alerts triggered
- 15:35 UTC: Decision to rollback
- 15:40 UTC: Rollback completed
- 15:45 UTC: Verification tests passed

**Root Cause:** [To be determined]

**Action Items:**
1. Review memory leak fixes
2. Add more comprehensive testing
3. Implement canary deployment
```

### 3. Analyze Root Cause

```bash
# Compare working vs broken commits
git diff 03db23c 3aa9a0a

# Review logs from failed deployment
cat logs_before_rollback_*.txt

# Test suspect changes in isolation
git checkout -b test-suspect-change
git cherry-pick <suspect-commit>
```

### 4. Plan Forward

```bash
# Create hotfix branch for proper fix
git checkout -b hotfix-proper-oom-fix dev-1.5.10

# Make incremental changes
# Test thoroughly
# Deploy to staging first
```

---

## Rollback Decision Matrix

| Situation | Recommended Method | Priority | Risk |
|-----------|-------------------|----------|------|
| Production crash | Git revert | 🔴 Immediate | Low |
| Memory leak detected | Git revert | 🔴 Immediate | Low |
| Data corruption | DB restore + Git revert | 🔴 Immediate | Medium |
| Minor bug, not critical | Wait for fix, no rollback | 🟡 Low | Low |
| Local dev issue | Git reset --soft | 🟢 Low | Low |
| Testing failure (pre-push) | Git reset --soft | 🟡 Medium | Low |
| Container won't start | Docker rollback | 🔴 Immediate | Low |

---

## Automation Tools

All rollback automation tools are in `scripts/rollback/` - see the emergency rollback script documentation below.

---

## Additional Resources

- **Git Revert Docs:** https://git-scm.com/docs/git-revert
- **Git Reset Docs:** https://git-scm.com/docs/git-reset
- **Docker Rollback:** https://docs.docker.com/engine/reference/commandline/rollback/
- **Database Backup:** See `src/cron/README.md`

---

## Safety Checklist

Before ANY rollback:
- [ ] Create database backup
- [ ] Create Git branch backup
- [ ] Document current state (logs, commits, etc.)
- [ ] Notify team
- [ ] Have recovery plan ready

After rollback:
- [ ] Run all tests
- [ ] Check logs for errors
- [ ] Monitor memory usage
- [ ] Verify all services running
- [ ] Document what happened

---

**Remember:** When in doubt, use `git revert` - it's the safest option for production!
