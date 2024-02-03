#!/bin/bash

# Define the cron job command
cron_command="/path/to/command"

# Define the cron schedule
cron_schedule="0 0 * * *"

# Add the cron job to the crontab
(
	crontab -l
	echo "$cron_schedule $cron_command"
) | crontab -

# Usage
# sudo ./add_cron.sh
