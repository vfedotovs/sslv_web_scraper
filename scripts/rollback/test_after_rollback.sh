#!/bin/bash
#
# Post-Rollback Testing Script
# Comprehensive testing suite to verify rollback was successful
#
# Usage: ./test_after_rollback.sh
#

set -e

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test counters
PASSED=0
FAILED=0
WARNINGS=0

# Output file
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
TEST_REPORT="test_report_${TIMESTAMP}.txt"

echo "=========================================" | tee "$TEST_REPORT"
echo "Post-Rollback Testing Script" | tee -a "$TEST_REPORT"
echo "Started: $(date)" | tee -a "$TEST_REPORT"
echo "=========================================" | tee -a "$TEST_REPORT"

# Function to test and report
test_item() {
    local test_name="$1"
    local test_command="$2"
    local is_critical="${3:-yes}"  # Default to critical

    echo -n "Testing: $test_name... "

    if eval "$test_command" > /dev/null 2>&1; then
        echo -e "${GREEN}PASSED${NC}"
        echo "✅ PASSED: $test_name" >> "$TEST_REPORT"
        ((PASSED++))
        return 0
    else
        if [ "$is_critical" = "yes" ]; then
            echo -e "${RED}FAILED${NC}"
            echo "❌ FAILED: $test_name" >> "$TEST_REPORT"
            ((FAILED++))
        else
            echo -e "${YELLOW}WARNING${NC}"
            echo "⚠️  WARNING: $test_name" >> "$TEST_REPORT"
            ((WARNINGS++))
        fi
        return 1
    fi
}

# Category 1: Container Health
echo "" | tee -a "$TEST_REPORT"
echo "1. Container Health Checks" | tee -a "$TEST_REPORT"
echo "----------------------------" | tee -a "$TEST_REPORT"

test_item "DB container running" \
    "docker-compose ps db | grep -q 'Up'"

test_item "WS container running" \
    "docker-compose ps ws | grep -q 'Up'"

test_item "TS container running" \
    "docker-compose ps ts | grep -q 'Up'" \
    "no"

test_item "Cron container running" \
    "docker-compose ps cron | grep -q 'Up'" \
    "no"

# Category 2: Network Connectivity
echo "" | tee -a "$TEST_REPORT"
echo "2. Network Connectivity" | tee -a "$TEST_REPORT"
echo "------------------------" | tee -a "$TEST_REPORT"

test_item "WS port 8000 accessible" \
    "nc -z localhost 8000"

test_item "DB container network reachable" \
    "docker-compose exec -T ws ping -c 1 db > /dev/null"

# Category 3: Application Endpoints
echo "" | tee -a "$TEST_REPORT"
echo "3. Application Endpoints" | tee -a "$TEST_REPORT"
echo "-------------------------" | tee -a "$TEST_REPORT"

test_item "Health endpoint (GET /)" \
    "curl -sf http://localhost:8000/ | grep -q 'ready'"

test_item "Main workflow endpoint (GET /run-task/Ogre)" \
    "timeout 120 curl -sf http://localhost:8000/run-task/Ogre | grep -q 'completed'" \
    "no"

# Category 4: Database Checks
echo "" | tee -a "$TEST_REPORT"
echo "4. Database Checks" | tee -a "$TEST_REPORT"
echo "-------------------" | tee -a "$TEST_REPORT"

test_item "Database connection" \
    "docker-compose exec -T db psql -U new_docker_user -d new_docker_db -c 'SELECT 1;' > /dev/null"

test_item "listed_ads table exists" \
    "docker-compose exec -T db psql -U new_docker_user -d new_docker_db -c 'SELECT COUNT(*) FROM listed_ads;' > /dev/null"

test_item "removed_ads table exists" \
    "docker-compose exec -T db psql -U new_docker_user -d new_docker_db -c 'SELECT COUNT(*) FROM removed_ads;' > /dev/null"

# Test database data integrity
DB_LISTED_COUNT=$(docker-compose exec -T db psql -U new_docker_user -d new_docker_db -t -c "SELECT COUNT(*) FROM listed_ads;" 2>/dev/null | tr -d ' ' || echo "0")
DB_REMOVED_COUNT=$(docker-compose exec -T db psql -U new_docker_user -d new_docker_db -t -c "SELECT COUNT(*) FROM removed_ads;" 2>/dev/null | tr -d ' ' || echo "0")

echo "Database record counts:" | tee -a "$TEST_REPORT"
echo "  Listed ads: $DB_LISTED_COUNT" | tee -a "$TEST_REPORT"
echo "  Removed ads: $DB_REMOVED_COUNT" | tee -a "$TEST_REPORT"

# Category 5: Memory Checks
echo "" | tee -a "$TEST_REPORT"
echo "5. Memory Checks" | tee -a "$TEST_REPORT"
echo "-----------------" | tee -a "$TEST_REPORT"

# WS container memory
WS_MEMORY=$(docker stats --no-stream --format "{{.MemUsage}}" 2>/dev/null | grep ws | head -n 1 | awk -F'/' '{print $1}' | sed 's/MiB//' | tr -d ' ' || echo "0")
WS_MEMORY_LIMIT=$(docker stats --no-stream --format "{{.MemUsage}}" 2>/dev/null | grep ws | head -n 1 | awk -F'/' '{print $2}' | sed 's/GiB//' | tr -d ' ' || echo "2")

echo "WS container memory: ${WS_MEMORY} MB / ${WS_MEMORY_LIMIT} GB" | tee -a "$TEST_REPORT"

if [ "$WS_MEMORY" != "0" ]; then
    if [ "$WS_MEMORY" -lt 500 ]; then
        echo -e "${GREEN}✅ Memory excellent (< 500 MB)${NC}" | tee -a "$TEST_REPORT"
        ((PASSED++))
    elif [ "$WS_MEMORY" -lt 1000 ]; then
        echo -e "${YELLOW}⚠️  Memory acceptable (< 1 GB)${NC}" | tee -a "$TEST_REPORT"
        ((WARNINGS++))
    else
        echo -e "${RED}❌ Memory too high (> 1 GB)${NC}" | tee -a "$TEST_REPORT"
        ((FAILED++))
    fi
else
    echo -e "${YELLOW}⚠️  Could not determine memory usage${NC}" | tee -a "$TEST_REPORT"
    ((WARNINGS++))
fi

# DB container memory
DB_MEMORY=$(docker stats --no-stream --format "{{.MemUsage}}" 2>/dev/null | grep db | head -n 1 | awk -F'/' '{print $1}' | sed 's/MiB//' | tr -d ' ' || echo "0")
echo "DB container memory: ${DB_MEMORY} MB" | tee -a "$TEST_REPORT"

# Category 6: Log Checks
echo "" | tee -a "$TEST_REPORT"
echo "6. Log Checks" | tee -a "$TEST_REPORT"
echo "--------------" | tee -a "$TEST_REPORT"

# Check for errors in WS logs
if docker-compose logs ws | tail -100 | grep -qi "error\|exception\|traceback"; then
    echo -e "${YELLOW}⚠️  Errors found in WS logs (review manually)${NC}" | tee -a "$TEST_REPORT"
    ((WARNINGS++))

    # Show last 5 error lines
    echo "Last 5 error/exception lines:" | tee -a "$TEST_REPORT"
    docker-compose logs ws | tail -100 | grep -i "error\|exception" | tail -5 | tee -a "$TEST_REPORT"
else
    echo -e "${GREEN}✅ No critical errors in WS logs${NC}" | tee -a "$TEST_REPORT"
    ((PASSED++))
fi

# Check for OOM errors
if docker-compose logs ws | grep -qi "out of memory\|oom\|killed"; then
    echo -e "${RED}❌ OOM errors found in logs!${NC}" | tee -a "$TEST_REPORT"
    ((FAILED++))
else
    echo -e "${GREEN}✅ No OOM errors${NC}" | tee -a "$TEST_REPORT"
    ((PASSED++))
fi

# Category 7: File System Checks
echo "" | tee -a "$TEST_REPORT"
echo "7. File System Checks" | tee -a "$TEST_REPORT"
echo "----------------------" | tee -a "$TEST_REPORT"

test_item "Database data volume exists" \
    "docker volume ls | grep -q 'db_data'"

test_item "Backup tmp volume exists" \
    "docker volume ls | grep -q 'backup_tmp'" \
    "no"

# Check for recent backups
BACKUP_COUNT=$(ls -1 /tmp/pg_backup_*.sql 2>/dev/null | wc -l || echo "0")
echo "Recent database backups found: $BACKUP_COUNT" | tee -a "$TEST_REPORT"

# Category 8: Cron Jobs (if applicable)
if docker-compose ps cron | grep -q "Up"; then
    echo "" | tee -a "$TEST_REPORT"
    echo "8. Cron Jobs" | tee -a "$TEST_REPORT"
    echo "-------------" | tee -a "$TEST_REPORT"

    test_item "Cron daemon running" \
        "docker-compose exec -T cron ps aux | grep -q 'crond'" \
        "no"

    test_item "Backup script accessible" \
        "docker-compose exec -T cron test -x /scripts/backup_db.sh" \
        "no"

    test_item "S3 upload script accessible" \
        "docker-compose exec -T cron test -x /scripts/upload_backup_to_s3.sh" \
        "no"
fi

# Category 9: Git Status
echo "" | tee -a "$TEST_REPORT"
echo "9. Git Status" | tee -a "$TEST_REPORT"
echo "--------------" | tee -a "$TEST_REPORT"

CURRENT_COMMIT=$(git rev-parse HEAD)
CURRENT_BRANCH=$(git branch --show-current)
CURRENT_MSG=$(git log -1 --pretty=%B)

echo "Current branch: $CURRENT_BRANCH" | tee -a "$TEST_REPORT"
echo "Current commit: $CURRENT_COMMIT" | tee -a "$TEST_REPORT"
echo "Commit message: $CURRENT_MSG" | tee -a "$TEST_REPORT"

# Check if there are uncommitted changes
if git diff --quiet && git diff --cached --quiet; then
    echo -e "${GREEN}✅ Working directory clean${NC}" | tee -a "$TEST_REPORT"
    ((PASSED++))
else
    echo -e "${YELLOW}⚠️  Uncommitted changes detected${NC}" | tee -a "$TEST_REPORT"
    ((WARNINGS++))
fi

# Category 10: Performance Test (optional)
echo "" | tee -a "$TEST_REPORT"
echo "10. Performance Test" | tee -a "$TEST_REPORT"
echo "---------------------" | tee -a "$TEST_REPORT"

echo "Testing response time..." | tee -a "$TEST_REPORT"
START_TIME=$(date +%s)
if curl -sf http://localhost:8000/ > /dev/null 2>&1; then
    END_TIME=$(date +%s)
    RESPONSE_TIME=$((END_TIME - START_TIME))
    echo "Health endpoint response time: ${RESPONSE_TIME}s" | tee -a "$TEST_REPORT"

    if [ "$RESPONSE_TIME" -lt 5 ]; then
        echo -e "${GREEN}✅ Response time good (< 5s)${NC}" | tee -a "$TEST_REPORT"
        ((PASSED++))
    else
        echo -e "${YELLOW}⚠️  Response time slow (> 5s)${NC}" | tee -a "$TEST_REPORT"
        ((WARNINGS++))
    fi
else
    echo -e "${RED}❌ Health endpoint not responding${NC}" | tee -a "$TEST_REPORT"
    ((FAILED++))
fi

# Final Summary
echo "" | tee -a "$TEST_REPORT"
echo "=========================================" | tee -a "$TEST_REPORT"
echo "Test Results Summary" | tee -a "$TEST_REPORT"
echo "=========================================" | tee -a "$TEST_REPORT"
echo -e "${GREEN}Passed:   $PASSED${NC}" | tee -a "$TEST_REPORT"
echo -e "${YELLOW}Warnings: $WARNINGS${NC}" | tee -a "$TEST_REPORT"
echo -e "${RED}Failed:   $FAILED${NC}" | tee -a "$TEST_REPORT"
echo "" | tee -a "$TEST_REPORT"

# Recommendations
echo "Recommendations:" | tee -a "$TEST_REPORT"
echo "----------------" | tee -a "$TEST_REPORT"

if [ $FAILED -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}✅ All tests passed! Rollback was successful.${NC}" | tee -a "$TEST_REPORT"
    echo "Next steps:" | tee -a "$TEST_REPORT"
    echo "  1. Monitor application for 30 minutes" | tee -a "$TEST_REPORT"
    echo "  2. Check production metrics" | tee -a "$TEST_REPORT"
    echo "  3. Document incident" | tee -a "$TEST_REPORT"
    echo "  4. Plan proper fix" | tee -a "$TEST_REPORT"
    EXIT_CODE=0
elif [ $FAILED -eq 0 ]; then
    echo -e "${YELLOW}⚠️  Tests passed with warnings.${NC}" | tee -a "$TEST_REPORT"
    echo "Action required:" | tee -a "$TEST_REPORT"
    echo "  1. Review warnings above" | tee -a "$TEST_REPORT"
    echo "  2. Monitor closely for 1 hour" | tee -a "$TEST_REPORT"
    echo "  3. Be prepared to rollback further if needed" | tee -a "$TEST_REPORT"
    EXIT_CODE=0
else
    echo -e "${RED}❌ Critical tests failed!${NC}" | tee -a "$TEST_REPORT"
    echo "Immediate action required:" | tee -a "$TEST_REPORT"
    echo "  1. Review failed tests above" | tee -a "$TEST_REPORT"
    echo "  2. Check logs: docker-compose logs" | tee -a "$TEST_REPORT"
    echo "  3. May need to rollback further" | tee -a "$TEST_REPORT"
    echo "  4. Consider database restore if data issues" | tee -a "$TEST_REPORT"
    EXIT_CODE=1
fi

echo "" | tee -a "$TEST_REPORT"
echo "Full test report saved to: $TEST_REPORT" | tee -a "$TEST_REPORT"
echo "Completed: $(date)" | tee -a "$TEST_REPORT"
echo "=========================================" | tee -a "$TEST_REPORT"

exit $EXIT_CODE
