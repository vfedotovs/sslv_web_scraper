
#!/usr/bin/env bash

set -euo pipefail

# Check for required tools
command -v aws >/dev/null || { echo "❌ AWS CLI not installed"; exit 1; }
command -v fzf >/dev/null || { echo "❌ fzf not installed"; exit 1; }

# Select environment interactively
env=$(printf "prod\ndev\nstaging\nsandbox" | fzf --prompt="Select environment: ") || {
  echo "❌ No environment selected"; exit 1;
}

# Prompt for project/app name
read -rp "Enter project or app name (e.g. webapp, api): " project
if [[ -z "$project" ]]; then
  echo "❌ Project name cannot be empty"; exit 1
fi

# Format key name
date_stamp=$(date +%Y%m%d)
key_name="${env}-${project}-ec2-key-${date_stamp}"
key_filename="${key_name}.pem"

# Define directory and full path
key_dir="$HOME/.ssh/aws-keys"
mkdir -p "$key_dir"
key_path="${key_dir}/${key_filename}"

# 🛑 Check if local file already exists
if [[ -f "$key_path" ]]; then
  echo "❌ A key file already exists at: $key_path"
  echo "❌ Aborting to avoid overwriting your existing private key."
  exit 1
fi

# 🛑 Check if AWS key pair already exists
if aws ec2 describe-key-pairs --key-names "$key_name" >/dev/null 2>&1; then
  echo "❌ AWS key pair with name '$key_name' already exists in your account."
  echo "❌ Aborting to prevent conflict."
  exit 1
fi

# ✅ Create the AWS key pair
echo "🔑 Creating AWS EC2 key pair: $key_name"
aws ec2 create-key-pair \
  --key-name "$key_name" \
  --query 'KeyMaterial' \
  --output text > "$key_path"

chmod 400 "$key_path"

echo "✅ Key pair successfully created and saved at:"
echo "$key_path"


