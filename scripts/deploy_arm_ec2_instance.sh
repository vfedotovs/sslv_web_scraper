#!/bin/bash

################################################################################
# Purpose: Interactive script to deploy an AWS ARM EC2 instance
#
# Features:
#   - Pre-checks AWS credentials
#   - Interactively creates a new AWS key pair and stores it locally
#   - Interactively selects AMI, security group, and IAM profile
#   - Deploys an ARM EC2 instance (t4g.small)
#
# Usage:
#   chmod +x scripts/deploy_ec2_arm_instance.sh
#   ./scripts/deploy_ec2_arm_instance.sh
################################################################################

set -euo pipefail

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

INSTANCE_TYPE="t4g.small"
KEY_DIR="$HOME/.ssh"

info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; }

################################################################################
# Step 1: Pre-check AWS credentials
################################################################################
echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  AWS ARM EC2 Instance Deployment${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

info "Checking AWS credentials..."

if ! command -v aws &> /dev/null; then
    error "AWS CLI is not installed. Please install it first."
    exit 1
fi

if ! AWS_IDENTITY=$(aws sts get-caller-identity 2>&1); then
    error "AWS credentials are not configured or are invalid."
    echo "  $AWS_IDENTITY"
    echo ""
    echo "  Please configure credentials with: aws configure"
    exit 1
fi

ACCOUNT_ID=$(echo "$AWS_IDENTITY" | grep -o '"Account": "[^"]*"' | cut -d'"' -f4)
ARN=$(echo "$AWS_IDENTITY" | grep -o '"Arn": "[^"]*"' | cut -d'"' -f4)
success "AWS credentials valid"
echo "  Account: $ACCOUNT_ID"
echo "  Identity: $ARN"
echo ""

# Check the default region is set
AWS_REGION=$(aws configure get region 2>/dev/null || true)
if [ -z "$AWS_REGION" ]; then
    warn "No default AWS region set."
    read -rp "Enter AWS region (e.g. eu-west-1): " AWS_REGION
    if [ -z "$AWS_REGION" ]; then
        error "Region is required."
        exit 1
    fi
fi
info "Using region: $AWS_REGION"
echo ""

################################################################################
# Step 2: Key pair — use existing or create new
################################################################################
echo -e "${BLUE}--- Key Pair Setup ---${NC}"
echo ""
echo "  1) Create a new key pair"
echo "  2) Use an existing key pair"
echo ""
read -rp "Select option [1/2]: " KEY_OPTION

case "$KEY_OPTION" in
    1)
        read -rp "Enter a name for the new key pair: " KEY_NAME
        if [ -z "$KEY_NAME" ]; then
            error "Key pair name cannot be empty."
            exit 1
        fi

        # Check if key pair already exists in AWS
        if aws ec2 describe-key-pairs --key-names "$KEY_NAME" &> /dev/null; then
            error "Key pair '$KEY_NAME' already exists in AWS. Choose a different name or use option 2."
            exit 1
        fi

        mkdir -p "$KEY_DIR"
        KEY_FILE="$KEY_DIR/${KEY_NAME}.pem"

        info "Creating key pair '$KEY_NAME'..."
        aws ec2 create-key-pair \
            --key-name "$KEY_NAME" \
            --key-type ed25519 \
            --query 'KeyMaterial' \
            --output text > "$KEY_FILE"

        chmod 400 "$KEY_FILE"
        success "Key pair created and saved to: $KEY_FILE"
        ;;
    2)
        info "Fetching existing key pairs..."
        KEYS=$(aws ec2 describe-key-pairs --query 'KeyPairs[*].KeyName' --output text | tr '\t' '\n' | sort)

        if [ -z "$KEYS" ]; then
            error "No existing key pairs found. Please create one (option 1)."
            exit 1
        fi

        echo ""
        echo "Available key pairs:"
        INDEX=1
        declare -a KEY_ARRAY
        while IFS= read -r k; do
            KEY_ARRAY+=("$k")
            echo "  $INDEX) $k"
            ((INDEX++))
        done <<< "$KEYS"

        echo ""
        read -rp "Select key pair number: " KEY_NUM
        if ! [[ "$KEY_NUM" =~ ^[0-9]+$ ]] || [ "$KEY_NUM" -lt 1 ] || [ "$KEY_NUM" -gt "${#KEY_ARRAY[@]}" ]; then
            error "Invalid selection."
            exit 1
        fi

        KEY_NAME="${KEY_ARRAY[$((KEY_NUM - 1))]}"
        success "Using key pair: $KEY_NAME"
        ;;
    *)
        error "Invalid option."
        exit 1
        ;;
esac
echo ""

################################################################################
# Step 3: Select AMI
################################################################################
echo -e "${BLUE}--- AMI Selection ---${NC}"
echo ""

# Fetch recent Amazon Linux 2023 ARM64 AMIs
info "Fetching Amazon Linux 2023 ARM64 AMIs..."
AMIS=$(aws ec2 describe-images \
    --owners amazon \
    --filters \
        "Name=name,Values=al2023-ami-2023*-kernel-*-arm64" \
        "Name=state,Values=available" \
        "Name=architecture,Values=arm64" \
    --query 'Images | sort_by(@, &CreationDate) | reverse(@) | [0:5].[ImageId,Name]' \
    --output text 2>/dev/null || true)

if [ -z "$AMIS" ]; then
    warn "Could not fetch AMIs automatically."
    read -rp "Enter AMI ID manually: " AMI_ID
else
    echo ""
    echo "Recent Amazon Linux 2023 ARM64 AMIs:"
    INDEX=1
    declare -a AMI_IDS
    declare -a AMI_NAMES
    while IFS=$'\t' read -r id name; do
        AMI_IDS+=("$id")
        AMI_NAMES+=("$name")
        echo "  $INDEX) $id - $name"
        ((INDEX++))
    done <<< "$AMIS"

    echo ""
    read -rp "Select AMI number [1]: " AMI_NUM
    AMI_NUM=${AMI_NUM:-1}
    if ! [[ "$AMI_NUM" =~ ^[0-9]+$ ]] || [ "$AMI_NUM" -lt 1 ] || [ "$AMI_NUM" -gt "${#AMI_IDS[@]}" ]; then
        error "Invalid selection."
        exit 1
    fi

    AMI_ID="${AMI_IDS[$((AMI_NUM - 1))]}"
    success "Using AMI: $AMI_ID (${AMI_NAMES[$((AMI_NUM - 1))]})"
fi
echo ""

################################################################################
# Step 4: Select Security Group
################################################################################
echo -e "${BLUE}--- Security Group Selection ---${NC}"
echo ""

info "Fetching security groups..."
SG_LIST=$(aws ec2 describe-security-groups \
    --query 'SecurityGroups[*].[GroupId,GroupName]' \
    --output text 2>/dev/null || true)

if [ -z "$SG_LIST" ]; then
    warn "Could not fetch security groups."
    read -rp "Enter Security Group ID: " SG_ID
else
    INDEX=1
    declare -a SG_IDS
    while IFS=$'\t' read -r sgid sgname; do
        SG_IDS+=("$sgid")
        echo "  $INDEX) $sgid - $sgname"
        ((INDEX++))
    done <<< "$SG_LIST"

    echo ""
    read -rp "Select security group number: " SG_NUM
    if ! [[ "$SG_NUM" =~ ^[0-9]+$ ]] || [ "$SG_NUM" -lt 1 ] || [ "$SG_NUM" -gt "${#SG_IDS[@]}" ]; then
        error "Invalid selection."
        exit 1
    fi

    SG_ID="${SG_IDS[$((SG_NUM - 1))]}"
    success "Using security group: $SG_ID"
fi
echo ""

################################################################################
# Step 5: IAM Instance Profile (optional)
################################################################################
echo -e "${BLUE}--- IAM Instance Profile (optional) ---${NC}"
echo ""

info "Fetching IAM instance profiles..."
IAM_PROFILES=$(aws iam list-instance-profiles \
    --query 'InstanceProfiles[*].InstanceProfileName' \
    --output text 2>/dev/null | tr '\t' '\n' | sort || true)

IAM_PROFILE_ARG=""
if [ -n "$IAM_PROFILES" ]; then
    echo "  0) None"
    INDEX=1
    declare -a PROFILE_ARRAY
    while IFS= read -r p; do
        PROFILE_ARRAY+=("$p")
        echo "  $INDEX) $p"
        ((INDEX++))
    done <<< "$IAM_PROFILES"

    echo ""
    read -rp "Select IAM instance profile number [0 for none]: " PROF_NUM
    PROF_NUM=${PROF_NUM:-0}

    if [ "$PROF_NUM" -ne 0 ] 2>/dev/null; then
        if [ "$PROF_NUM" -ge 1 ] && [ "$PROF_NUM" -le "${#PROFILE_ARRAY[@]}" ]; then
            IAM_PROFILE="${PROFILE_ARRAY[$((PROF_NUM - 1))]}"
            IAM_PROFILE_ARG="--iam-instance-profile Name=$IAM_PROFILE"
            success "Using IAM profile: $IAM_PROFILE"
        else
            error "Invalid selection."
            exit 1
        fi
    else
        info "No IAM instance profile selected."
    fi
else
    warn "Could not fetch IAM profiles. Continuing without one."
fi
echo ""

################################################################################
# Step 6: EBS Volume Size
################################################################################
echo -e "${BLUE}--- EBS Volume ---${NC}"
echo ""
read -rp "EBS volume size in GB [16]: " VOLUME_SIZE
VOLUME_SIZE=${VOLUME_SIZE:-16}
success "Using EBS volume: ${VOLUME_SIZE}GB (gp3)"
echo ""

################################################################################
# Step 7: Confirm and Deploy
################################################################################
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Deployment Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "  Instance type:  $INSTANCE_TYPE"
echo "  AMI:            $AMI_ID"
echo "  Key pair:       $KEY_NAME"
echo "  Security group: $SG_ID"
echo "  IAM profile:    ${IAM_PROFILE:-none}"
echo "  EBS volume:     ${VOLUME_SIZE}GB gp3"
echo "  Region:         $AWS_REGION"
echo ""

read -rp "Proceed with deployment? [y/N]: " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    warn "Deployment cancelled."
    exit 0
fi

echo ""
info "Launching EC2 instance..."

# Build the command
RUN_CMD=(aws ec2 run-instances
    --image-id "$AMI_ID"
    --instance-type "$INSTANCE_TYPE"
    --key-name "$KEY_NAME"
    --security-group-ids "$SG_ID"
    --block-device-mappings "DeviceName=/dev/xvda,Ebs={VolumeSize=$VOLUME_SIZE,VolumeType=gp3}"
)

if [ -n "$IAM_PROFILE_ARG" ]; then
    RUN_CMD+=(--iam-instance-profile "Name=$IAM_PROFILE")
fi

RESULT=$("${RUN_CMD[@]}" 2>&1)

if [ $? -ne 0 ]; then
    error "Failed to launch instance:"
    echo "  $RESULT"
    exit 1
fi

INSTANCE_ID=$(echo "$RESULT" | grep -o '"InstanceId": "[^"]*"' | head -1 | cut -d'"' -f4)
success "Instance launched: $INSTANCE_ID"
echo ""

info "Waiting for instance to get a public IP..."
sleep 5

PUBLIC_IP=$(aws ec2 describe-instances \
    --instance-ids "$INSTANCE_ID" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text 2>/dev/null || echo "N/A")

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Deployment Complete${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "  Instance ID: $INSTANCE_ID"
echo "  Public IP:   $PUBLIC_IP"
echo ""

if [ "$KEY_OPTION" == "1" ]; then
    echo -e "${YELLOW}Connect with:${NC}"
    echo "  ssh -i $KEY_FILE ec2-user@$PUBLIC_IP"
else
    echo -e "${YELLOW}Connect with:${NC}"
    echo "  ssh -i ~/.ssh/${KEY_NAME}.pem ec2-user@$PUBLIC_IP"
fi
echo ""


