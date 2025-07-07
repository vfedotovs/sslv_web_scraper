


aws ec2 describe-instances \
  --query 'Reservations[*].Instances[*].{ID:InstanceId,Launch:LaunchTime,IP:PublicIpAddress,Key:KeyName}' \
  --output table



