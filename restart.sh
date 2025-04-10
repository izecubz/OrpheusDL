#!/bin/bash

# Stop the current container
docker-compose down

# Rebuild the container with the latest code
docker-compose build

# Start the container in detached mode
docker-compose up -d

# Show logs
docker-compose logs -f 