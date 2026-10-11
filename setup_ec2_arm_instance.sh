#!/bin/bash

################################################################################
# Purpose: Automate AWS ARM EC2 instance software installation before
#          deployment of application
#
# Target: Amazon Linux 2023 ARM64 (aarch64) instances
#
# Installs:
#   - git
#   - make
#   - docker
#   - docker compose (latest)
#   - docker buildx (v0.30.1)
#
# Usage:
#   chmod +x setup_ec2_arm_instance.sh
#   ./setup_ec2_arm_instance.sh
################################################################################

set -e  # Exit on error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Track installation status
declare -A INSTALLATION_STATUS

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}AWS ARM EC2 Instance Setup Script${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

################################################################################
# Step 1: Install git, make, docker
################################################################################
echo -e "${YELLOW}[1/4] Installing git, make, and docker...${NC}"
if sudo dnf install -y git make docker; then
    INSTALLATION_STATUS["git"]="SUCCESS"
    INSTALLATION_STATUS["make"]="SUCCESS"
    INSTALLATION_STATUS["docker"]="SUCCESS"
    echo -e "${GREEN}✓ git, make, docker installed successfully${NC}"
else
    echo -e "${RED}✗ Failed to install git, make, docker${NC}"
    exit 1
fi
echo ""

################################################################################
# Step 2: Start and enable Docker service
################################################################################
echo -e "${YELLOW}[2/4] Starting and enabling Docker service...${NC}"
if sudo systemctl start docker && sudo systemctl enable docker; then
    INSTALLATION_STATUS["docker-service"]="SUCCESS"
    echo -e "${GREEN}✓ Docker service started and enabled${NC}"
else
    echo -e "${RED}✗ Failed to start Docker service${NC}"
    exit 1
fi
echo ""

################################################################################
# Step 3: Install Docker Compose (latest for ARM64)
################################################################################
echo -e "${YELLOW}[3/4] Installing Docker Compose (latest)...${NC}"

# Create docker cli-plugins directory if it doesn't exist
mkdir -p ~/.docker/cli-plugins

# Download latest docker-compose for ARM64
if curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-aarch64 \
    -o ~/.docker/cli-plugins/docker-compose; then
    echo -e "${GREEN}✓ Docker Compose downloaded${NC}"
else
    echo -e "${RED}✗ Failed to download Docker Compose${NC}"
    INSTALLATION_STATUS["docker-compose"]="FAILED"
fi

# Make it executable (user)
chmod +x ~/.docker/cli-plugins/docker-compose

# Make it executable (system-wide)
if [ -f /usr/libexec/docker/cli-plugins/docker-compose ]; then
    sudo chmod +x /usr/libexec/docker/cli-plugins/docker-compose
fi

# Verify installation
if docker compose version &> /dev/null; then
    INSTALLATION_STATUS["docker-compose"]="SUCCESS"
    echo -e "${GREEN}✓ Docker Compose installed successfully${NC}"
else
    echo -e "${RED}✗ Docker Compose installation verification failed${NC}"
    INSTALLATION_STATUS["docker-compose"]="FAILED"
fi
echo ""

################################################################################
# Step 4: Install Docker Buildx (v0.30.1 for ARM64)
################################################################################
echo -e "${YELLOW}[4/4] Installing Docker Buildx (v0.30.1)...${NC}"

# Download docker-buildx for ARM64
if curl -L https://github.com/docker/buildx/releases/download/v0.30.1/buildx-v0.30.1.linux-arm64 \
    -o ~/.docker/cli-plugins/docker-buildx; then
    echo -e "${GREEN}✓ Docker Buildx downloaded${NC}"
else
    echo -e "${RED}✗ Failed to download Docker Buildx${NC}"
    INSTALLATION_STATUS["docker-buildx"]="FAILED"
fi

# Make it executable
chmod +x ~/.docker/cli-plugins/docker-buildx

# Verify installation
if docker buildx version &> /dev/null; then
    INSTALLATION_STATUS["docker-buildx"]="SUCCESS"
    echo -e "${GREEN}✓ Docker Buildx installed successfully${NC}"
else
    echo -e "${RED}✗ Docker Buildx installation verification failed${NC}"
    INSTALLATION_STATUS["docker-buildx"]="FAILED"
fi
echo ""

################################################################################
# Verification: Check all installed software versions
################################################################################
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Installation Verification Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Function to check and display version
check_version() {
    local software=$1
    local command=$2

    echo -n "Checking $software... "
    if version_output=$($command 2>&1); then
        echo -e "${GREEN}✓${NC}"
        echo "  Version: $version_output"
    else
        echo -e "${RED}✗ FAILED${NC}"
        echo "  Error: Could not retrieve version"
    fi
    echo ""
}

# Check git
check_version "Git" "git --version"

# Check make
check_version "Make" "make --version | head -n1"

# Check docker
check_version "Docker" "docker --version"

# Check docker service status
echo -n "Checking Docker service... "
if sudo systemctl is-active --quiet docker; then
    echo -e "${GREEN}✓ Running${NC}"
    echo "  Status: Active"
else
    echo -e "${RED}✗ Not running${NC}"
    echo "  Status: Inactive"
fi
echo ""

# Check docker compose
check_version "Docker Compose" "docker compose version"

# Check docker buildx
check_version "Docker Buildx" "docker buildx version"

################################################################################
# Final Summary
################################################################################
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Installation Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Count successes and failures
SUCCESS_COUNT=0
FAILED_COUNT=0

for key in "${!INSTALLATION_STATUS[@]}"; do
    status="${INSTALLATION_STATUS[$key]}"
    if [ "$status" == "SUCCESS" ]; then
        echo -e "${GREEN}✓${NC} $key: ${GREEN}SUCCESS${NC}"
        ((SUCCESS_COUNT++))
    else
        echo -e "${RED}✗${NC} $key: ${RED}FAILED${NC}"
        ((FAILED_COUNT++))
    fi
done

echo ""
echo -e "${BLUE}----------------------------------------${NC}"
echo -e "Total: $SUCCESS_COUNT succeeded, $FAILED_COUNT failed"
echo -e "${BLUE}----------------------------------------${NC}"
echo ""

if [ $FAILED_COUNT -eq 0 ]; then
    echo -e "${GREEN}All installations completed successfully!${NC}"
    echo ""
    echo -e "${YELLOW}Next steps:${NC}"
    echo "  1. Add your user to docker group: sudo usermod -aG docker \$USER"
    echo "  2. Log out and log back in for group changes to take effect"
    echo "  3. Verify docker without sudo: docker ps"
    echo ""
    exit 0
else
    echo -e "${RED}Some installations failed. Please check the errors above.${NC}"
    exit 1
fi
