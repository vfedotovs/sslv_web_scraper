#!/bin/bash

aws ec2 run-instances \
        --image-id ami-0fc970315c2d38f01 \
        --security-group-ids sg-0dbf4ab1dcda0f609 \
        --instance-type t2.micro \
        --key-name dev-ec2-key \
        --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=16,VolumeType=gp2}'



# Post install script
# sudo yum update -y
# sudo yum install git -y 
# sudo yum install -y docker
# sudo systemctl start docker
# sudo usermod -aG docker ec2-user

# Install latest docker compose:
# sudo curl -L https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m) -o /usr/local/bin/docker-compose
# sudo chmod +x /usr/local/bin/docker-compose
# docker-compose --version
