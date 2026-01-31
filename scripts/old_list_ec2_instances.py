#!/usr/bin/env python3.9

import boto3
from datetime import datetime

# Initialize boto3 client
client = boto3.client('ec2')

def get_instances():
    """Fetches all instances and organizes details for VMs with and without public IP."""
    response = client.describe_instances()
    aws_vms = []
    vm_seq_num = 1

    for reservation in response.get('Reservations', []):
        for instance in reservation.get('Instances', []):
            instance_data = get_instance_data(instance, vm_seq_num)
            aws_vms.append(instance_data)
            vm_seq_num += 1

    return aws_vms

def get_instance_data(instance, seq_num):
    """Extracts relevant instance details and organizes them in a list."""
    instance_id = instance['InstanceId']
    pem_key = instance.get('KeyName', 'N/A')
    launch_time = instance['LaunchTime']
    vm_state = instance['State']['Name']
    public_ip = instance.get('PublicIpAddress', '')

    return [seq_num, instance_id, launch_time.isoformat(), vm_state, public_ip, pem_key ]

def display_instances(instances):
    """Displays instance details."""
    for vm in instances:
        # Only print the public IP if available
        output = " | ".join(str(field) for field in vm[:5] if field) + (
            f" | {vm[5]}" if vm[5] else "")
        print(output)

def get_tag(tags, key='Name'):
    """Retrieves specific tag value based on the provided key."""
    if tags:
        for tag in tags:
            if tag['Key'] == key:
                return tag['Value']
    return ''

def display_instance_tags():
    """Displays instance tags and types."""
    conn = boto3.resource('ec2')
    instances = conn.instances.all()

    print("\nInstance-ID        :  Type  : Instance-TAG")
    for instance in instances:
        instance_tag = get_tag(instance.tags)
        print(instance.id, instance.instance_type, instance_tag)

message = """
### Connect to VM ###   ssh -i my-key.pem ec2-user@12.34.56.78

### Stop instance ###   aws ec2 stop-instances --instance-ids i-0e07a37e5274d08c7
### Start instance ###  aws ec2 start-instances --instance-ids i-1234567890abcdef0

### Delete instance ### aws ec2 terminate-instances --instance-ids i-0e07a37e5274d08c7

### Upload/downlod files to/from instance ... source destonation ###
Example of download  : scp -i my-key.pem ec2-user@34.56.78.98:/home/ec2-user/*.backup .

# List keypairs that can be used to connect to EC2 instances
aws ec2 describe-key-pairs | grep -E "Time|Name" | xargs -n 4 | sort -k 2

"""


if __name__ == "__main__":
    print("Fetching EC2 Instances...\n")
    aws_vms = get_instances()
    display_instances(aws_vms)
    display_instance_tags()
    print(message)

