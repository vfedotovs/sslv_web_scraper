
#!/bin/bash

# Deploy instances
instances=("ogre" "sigulda" "salaspils")

for instance in "${instances[@]}"; do
  echo "Deploying $instance city web scraper instance... "
  docker-compose --project-name $instance --env-file .env.$instance up -d
done

echo "All cilty web scraper container instances deployed successfully..."
