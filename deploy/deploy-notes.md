

Requirements for manual deployment:
[ ] aws ec2 instance and S3 bucket for configuration files and DB backup 
[ ] ansible needs to be installed
[ ] inventory.yml file need to be updated/populated
[ ] playbook file that contains list of thaks that will be performed agenst ec2 instance target
[ ] (optional) bash script (setup_inventory.sh) that populates inventory.yml file automatically in fzf way

[ ] how to run example:
ansible-playbook -i inventory.yml deploy_webscraper_app.yml --list-tasks

ansible-playboot -i inventory.yml deploy_webscraper_app.yml

[ ] ensure that no secrets are leaked in inventory and in playbook file
[ ] (optional)Update GitHub Actions Secrets from CLI via script using  gh
```sh

use fzf to select IP and private key file name to update github actions secrets
gh secret set DEV_EC2_IP --repo your-username/XYZ --body "1.2.3.4"

gh secret set DEV_EC2_SSH_KEY --repo your-username/XYZ < ~/.ssh/your-private-key.pem
or 
gh secret set DEV_EC2_SSH_KEY --repo your-username/XYZ --body "$(cat ~/.ssh/dev-key.pem)"

GitHub CLI doesn’t show secret values (for security), but you can list secret names:

gh secret list --repo your-username/XYZ
```

