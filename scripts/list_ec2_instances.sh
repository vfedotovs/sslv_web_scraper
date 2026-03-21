
#!/bin/bash

################################################################################
# Purpose: List EC2 instances using AWS CLI (no Python/boto3 dependency)
#
# Output: Instance details including ID, launch time, state, public IP,
#         key name, instance type, and Name tag
#
# Usage:
#   chmod +x scripts/list_ec2_instances.sh
#   ./scripts/list_ec2_instances.sh
################################################################################

set -euo pipefail

echo "Fetching EC2 Instances..."
echo ""

# Fetch all instances: seq | instance-id | launch-time | state | public-ip | key-name
aws ec2 describe-instances \
    --query 'Reservations[].Instances[].[InstanceId,LaunchTime,State.Name,PublicIpAddress,KeyName]' \
    --output text | \
    awk -v seq=1 '{
        id    = $1
        time  = $2
        state = $3
        ip    = ($4 == "None" ? "" : $4)
        key   = ($5 == "None" ? "N/A" : $5)

        line = seq " | " id " | " time " | " state
        if (ip != "") line = line " | " ip
        if (key != "N/A") line = line " | " key

        print line
        seq++
    }'

echo ""

# Fetch instance tags and types
echo "Instance-ID        :  Type  : Instance-TAG"

aws ec2 describe-instances \
    --query 'Reservations[].Instances[].[InstanceId,InstanceType,Tags[?Key==`Name`].Value|[0]]' \
    --output text | \
    awk '{
        id   = $1
        type = $2
        tag  = ($3 == "None" ? "" : $3)
        print id, type, tag
    }'

cat <<'EOF'

### Connect to VM ###   ssh -i my-key.pem ec2-user@12.34.56.78

### Stop instance ###   aws ec2 stop-instances --instance-ids i-0e07a37e5274d08c7
### Start instance ###  aws ec2 start-instances --instance-ids i-1234567890abcdef0

### Delete instance ### aws ec2 terminate-instances --instance-ids i-0e07a37e5274d08c7

### Upload/download files to/from instance ... source destination ###
Example of download  : scp -i my-key.pem ec2-user@34.56.78.98:/home/ec2-user/*.backup .

# List keypairs that can be used to connect to EC2 instances
aws ec2 describe-key-pairs | grep -E "Time|Name" | xargs -n 4 | sort -k 2

EOF

