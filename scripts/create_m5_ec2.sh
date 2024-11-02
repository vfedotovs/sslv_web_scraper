#!/bin/bash

# To create EC2 instance using aws CLI
aws ec2 run-instances \
  --image-id ami-0063df405115669c3 \
  --security-group-ids sg-0dbf4ab1dcda0f609 \
  --instance-type t4g.small \
  --key-name your-keypair \
  --iam-instance-profile Name=VF-Custom-S3-SecretsManager-access \
  --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=16,VolumeType=gp3}'
