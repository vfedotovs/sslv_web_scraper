#!/bin/bash
#
# Emergency Rollback Script
# Safely rolls back to previous commit with all safety checks
#
# Usage: ./emergency_rollback.sh [commit_hash]
#
# If no commit hash provided, rolls back to previous commit (HEAD~1)
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
BACKUP_DIR="/tmp/rollback_backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
TARGET_COMMIT="${1:-HEAD~1}"

echo "========================================="
echo "Emergency Rollback Script"
echo "========================================="
echo "Started: $(date)"
echo "Target commit: $TARGET_COMMIT"
echo ""

# Function to print colored messages
print_status() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ ERROR: $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  WARNING: $1${NC}"
}

# Function to ask for confirmation
confirm() {
    read -p "$1 (yes/no): " response
    case "$response" in
        [yY][eE][sS]|[yY]) return 0 ;;
        *) return 1 ;;
    esac
}

# Step 1: Pre-rollback checks
echo "Step 1: Pre-Rollback Checks"
echo "-----------------------------"

# Check if we're in a git repository
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    print_error "Not in a git repository!"
    exit 1
fi
print_status "Git repository confirmed"

# Check if target commit exists
if ! git rev-parse "$TARGET_COMMIT" > /dev/null 2>&1; then
    print_error "Target commit '$TARGET_COMMIT' does not exist!"
    exit 1
fi
print_status "Target commit exists"

# Show current and target commits
CURRENT_COMMIT=$(git rev-parse HEAD)
CURRENT_MSG=$(git log -1 --pretty=%B HEAD)
TARGET_HASH=$(git rev-parse "$TARGET_COMMIT")
TARGET_MSG=$(git log -1 --pretty=%B "$TARGET_COMMIT")

echo ""
echo "Current commit: $CURRENT_COMMIT"
echo "Message: $CURRENT_MSG"
echo ""
echo "Will rollback to: $TARGET_HASH"
echo "Message: $TARGET_MSG"
echo ""

# Confirm rollback
if ! confirm "Proceed with rollback?"; then
    echo "Rollback cancelled by user"
    exit 0
fi

# Step 2: Create backups
echo ""
echo "Step 2: Creating Backups"
echo "-------------------------"

mkdir -p "$BACKUP_DIR"

# Backup current commit hash
echo "$CURRENT_COMMIT" > "$BACKUP_DIR/commit_before_rollback_${TIMESTAMP}.txt"
print_status "Saved current commit hash"

# Create backup branch
BACKUP_BRANCH="backup-before-rollback-${TIMESTAMP}"
git branch "$BACKUP_BRANCH"
print_status "Created backup branch: $BACKUP_BRANCH"

# Backup database (if docker is running)
if docker-compose ps | grep -q "db.*Up"; then
    echo "Backing up database..."
    DB_BACKUP="$BACKUP_DIR/pg_backup_${TIMESTAMP}.sql"

    if docker exec -t $(docker ps -qf "name=db-1") pg_dump -U new_docker_user -d new_docker_db > "$DB_BACKUP" 2>/dev/null; then
        print_status "Database backup created: $DB_BACKUP"
    else
        print_warning "Database backup failed (container may not be running)"
    fi
else
    print_warning "Database container not running - skipping DB backup"
fi

# Save current logs
echo "Saving container logs..."
docker-compose logs ws > "$BACKUP_DIR/ws_logs_${TIMESTAMP}.txt" 2>/dev/null || print_warning "Could not save WS logs"
docker-compose logs db > "$BACKUP_DIR/db_logs_${TIMESTAMP}.txt" 2>/dev/null || print_warning "Could not save DB logs"
print_status "Logs saved to $BACKUP_DIR"

# Step 3: Stop containers
echo ""
echo "Step 3: Stopping Containers"
echo "-----------------------------"
if docker-compose ps | grep -q "Up"; then
    docker-compose down
    print_status "Containers stopped"
else
    print_warning "No containers running"
fi

# Step 4: Perform rollback
echo ""
echo "Step 4: Performing Git Rollback"
echo "---------------------------------"

# Check if commits are already pushed
UNPUSHED=$(git log origin/$(git branch --show-current)..HEAD --oneline 2>/dev/null || echo "")

if [ -z "$UNPUSHED" ]; then
    echo "Commits are already pushed to remote"
    echo "Using safe git revert method..."

    # Count commits between target and HEAD
    COMMITS_TO_REVERT=$(git rev-list --count $TARGET_HASH..HEAD)

    if [ "$COMMITS_TO_REVERT" -eq 0 ]; then
        print_error "Already at target commit!"
        exit 1
    fi

    echo "Will revert $COMMITS_TO_REVERT commit(s)"

    # Revert commits (creates new commit)
    if git revert --no-edit $TARGET_HASH..HEAD; then
        print_status "Reverted commits successfully"
    else
        print_error "Revert failed - may have conflicts"
        echo "Please resolve conflicts manually, then run:"
        echo "  git revert --continue"
        exit 1
    fi
else
    echo "Commits NOT pushed yet (safe to reset)"

    if confirm "Use git reset --hard? (WARNING: This will delete unpushed commits)"; then
        git reset --hard "$TARGET_HASH"
        print_status "Reset to target commit"
    else
        echo "Using safe git revert instead..."
        git revert --no-edit $TARGET_HASH..HEAD
        print_status "Reverted commits"
    fi
fi

# Step 5: Rebuild and restart containers
echo ""
echo "Step 5: Rebuilding Containers"
echo "-------------------------------"
docker-compose up -d --build

echo "Waiting for containers to start (30 seconds)..."
sleep 30

# Step 6: Verification
echo ""
echo "Step 6: Post-Rollback Verification"
echo "------------------------------------"

VERIFICATION_FAILED=0

# Check container status
echo -n "Checking containers... "
if docker-compose ps | grep -q "Up"; then
    print_status "Containers running"
else
    print_error "Containers not running!"
    VERIFICATION_FAILED=1
fi

# Check health endpoint
echo -n "Testing health endpoint... "
if curl -sf http://localhost:8000/ > /dev/null; then
    print_status "Health check passed"
else
    print_error "Health check failed!"
    VERIFICATION_FAILED=1
fi

# Check memory
WS_MEMORY=$(docker stats --no-stream --format "{{.MemUsage}}" 2>/dev/null | grep ws | awk -F'/' '{print $1}' | sed 's/MiB//' || echo "0")
echo -n "Checking memory usage... "
if [ "$WS_MEMORY" != "0" ] && [ "$WS_MEMORY" -lt 1000 ]; then
    print_status "Memory: ${WS_MEMORY} MB (within limits)"
else
    print_warning "Memory: ${WS_MEMORY} MB (verify this is acceptable)"
fi

# Check logs for errors
echo -n "Checking logs for errors... "
if docker-compose logs ws | tail -50 | grep -qi "error\|exception\|traceback"; then
    print_warning "Errors found in logs - review manually"
else
    print_status "No critical errors in logs"
fi

# Step 7: Summary
echo ""
echo "========================================="
echo "Rollback Summary"
echo "========================================="
echo "Previous commit: $CURRENT_COMMIT"
echo "Current commit:  $(git rev-parse HEAD)"
echo "Backup branch:   $BACKUP_BRANCH"
echo "Backups saved:   $BACKUP_DIR"
echo ""

if [ $VERIFICATION_FAILED -eq 0 ]; then
    print_status "ROLLBACK SUCCESSFUL!"
    echo ""
    echo "Next steps:"
    echo "1. Run comprehensive tests: ./scripts/rollback/test_after_rollback.sh"
    echo "2. Monitor application for 30 minutes"
    echo "3. If stable, push changes: git push origin $(git branch --show-current)"
    echo "4. Document incident in docs/incidents/"
else
    print_error "ROLLBACK COMPLETED WITH WARNINGS"
    echo ""
    echo "Action required:"
    echo "1. Review errors above"
    echo "2. Check logs: docker-compose logs"
    echo "3. May need to restore from backup"
fi

echo ""
echo "To restore if needed:"
echo "  git checkout $BACKUP_BRANCH"
echo "  git checkout -b recovery-attempt"
echo ""
echo "Completed: $(date)"
echo "========================================="
