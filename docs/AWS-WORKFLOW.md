AWS Workflow Checklist to create infrastructure
===============================================

### 1. Setup AWS cli 

```sh

# More information on prereqs and how to create IAM account 
# https://docs.aws.amazon.com/cli/latest/userguide/getting-started-prereqs.html
$ aws configure list

$ aws configure
AWS Access Key ID [None]: AKIAIOSFODNN7EXAMPLE
AWS Secret Access Key [None]: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
Default region name [None]: us-west-2
Default output format [None]: json

```


### 2. Create key-pair 
```sh
aws ec2 describe-key-pairs
aws ec2 create-key-pair \
    --key-name ProdKeyPair \
    --query 'KeyMaterial' \
    --output text > ProdKeyPair.pem
```


### 3. Create security group that allows SSH access to EC2 instance 
To create security group VPC id is needed 

```sh
# Find default vpc or create new
aws ec2 describe-vpcs --output=table | grep -E "IsDefault|VpcId"

# Map vpc to security group
aws ec2  describe-security-groups \
    --output=json \
        | grep -E "Description|GroupName|sg-|vpc-" \
        | tr '\n' ' ' | sed -e 's/\"Description"/\n\"Description\"/g'

# Create custom security group
aws ec2 create-security-group \
    --group-name my-sg \
    --description "My security group" \
    --vpc-id vpc-1a2b3c4d

# Describe new created security group
aws ec2 describe-security-groups --group-ids sg-903004f8

# The following command adds another rule to enable SSH to instances in the same security group.
aws ec2 authorize-security-group-ingress \
    --group-id sg-903004f8 \
    --protocol tcp --port 22 --cidr x.x.x.x/x
```


### 4. Launch new EC2 instance
To create instance security group ID and key-name is REQUIRED:
```sh
aws ec2 run-instances \
        --image-id ami-0fc970315c2d38f01 \
        --security-group-ids sg-0dbf4ab1dcda0f609 \
        --instance-type t2.micro \
        --key-name <ProdKeyPair> \
        --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=16,VolumeType=gp2}'

# Describe instance after creation to get public IP that will be needed to connect with ssh
aws ec2 describe-instances --output=table

# Connect to instance  
ssh -i test-key.pem ec2-user@34.247.191.28

# Stop instance - does not delete
aws ec2 stop-instances --instance-ids i-0e07a37e5274d08c7

# Start instance
aws ec2 start-instances --instance-ids i-1234567890abcdef0

# Delete instance
aws ec2 terminate-instances --instance-ids i-0e07a37e5274d08c7

# Upload/downlod files to/from instance ... source destonation 
# Example of download:
scp -i test-key.pem ec2-user@34.242.93.197:/home/ec2-user/some_filen_ame.txt .
```


### 5. Some usefull S3 scripts
```sh
https://docs.aws.amazon.com/cli/latest/userguide/bash_s3_code_examples.html
```


### 6. Run post install script

```sh
sudo yum update -y
sudo yum install git -y 
sudo yum install -y docker
sudo systemctl start docker
sudo usermod -aG docker ec2-user

# Install latest docker compose:
sudo curl -L https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m) -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
docker-compose --version
```

### 6. Install minikube - (Work in progress)
