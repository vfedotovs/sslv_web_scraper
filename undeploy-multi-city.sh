
#!/bin/bash

# Undeploy instances
instances=("ogre" "sigulda" "salaspils")

for instance in "${instances[@]}"; do
  echo "Stopping and removing $instance city web scraper instance..."
  docker-compose --project-name $instance --env-file .env.$instance down -v
done

echo "All city web scraper container instances undeployed successfully."

