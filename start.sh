#!/bin/bash

echo "Starting application..."

# Check if the app container is already running
if [ ! "$(docker ps -q -f name=apex-mage)" ]; then
    # Check if the container has been built but isn't running
    if [ "$(docker ps -aq -f status=exited -f name=apex-mage)" ]; then
        # Remove the existing container
        docker rm apex-mage
    else
        docker build -t apex-mage .
        # Run a new container with the SQLite DB directory mounted and environment variables loaded
        docker run -d --name apex-mage --restart unless-stopped \
            --env-file /app/.env \
            -e GOOGLE_APPLICATION_CREDENTIALS=/app/g_auth.json \
            -v /appdata:/app/data \
            -v /usr/bin/docker:/usr/bin/docker \
            -v /app/g_auth.json:/app/g_auth.json \
            --network host \
            apex-mage

    fi
else
    echo "Application 'apex-mage' is already running. Stopping and recreating it..."
    docker stop apex-mage
    docker rm apex-mage
    docker build -t apex-mage .
    docker run -d --name apex-mage --restart unless-stopped \
        --env-file /app/.env \
        -e GOOGLE_APPLICATION_CREDENTIALS=/app/g_auth.json \
        -v /appdata:/app/data \
        -v /usr/bin/docker:/usr/bin/docker \
        -v /app/g_auth.json:/app/g_auth.json \
        --network host \
        apex-mage
fi

echo "Application started."