#!/bin/bash

# Select key-pair using fzf
KEY_PAIR=$(aws ec2 describe-key-pairs --query 'KeyPairs[*].KeyName' --output text | tr '\t' '\n' | fzf --prompt="Select AWS Key Pair: ")

if [ -z "$KEY_PAIR" ]; then
  echo "No key-pair selected. Exiting."
  exit 1
fi

echo "AWS instance will be created with key-pair: $KEY_PAIR"

# To create EC2 instance using aws CLI
aws ec2 run-instances \
  --image-id ami-0063df405115669c3 \
  --security-group-ids sg-0dbf4ab1dcda0f609 \
  --instance-type t4g.small \
  --key-name "$KEY_PAIR" \
  --iam-instance-profile Name=VF-Custom-S3-SecretsManager-access \
  --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=16,VolumeType=gp3}'
