#!/bin/bash

set -e

REGISTRY="ghcr.io"
IMAGE="ghcr.io/aghs-scepter/apex-mage:latest"

echo "Starting application..."

# Check if GHCR_TOKEN is set for authentication
if [ -n "$GHCR_TOKEN" ]; then
    echo "Authenticating with GitHub Container Registry..."
    echo "$GHCR_TOKEN" | docker login "$REGISTRY" -u "$GITHUB_USERNAME" --password-stdin
fi

# Pull the latest image
echo "Pulling latest image from GHCR..."
if ! docker pull "$IMAGE"; then
    echo "Error: Failed to pull image from GHCR"
    echo "Make sure GHCR_TOKEN and GITHUB_USERNAME are set, or the image is public"
    exit 1
fi

# Check if the app container is already running
if [ "$(docker ps -q -f name=apex-mage)" ]; then
    echo "Application 'apex-mage' is already running. Stopping and recreating it..."
    docker stop apex-mage
    docker rm apex-mage
elif [ "$(docker ps -aq -f status=exited -f name=apex-mage)" ]; then
    # Remove the existing stopped container
    docker rm apex-mage
fi

# Run the container with the SQLite DB directory mounted and environment variables loaded
echo "Starting container..."
docker run -d --name apex-mage --restart unless-stopped \
    --env-file /app/.env \
    -e GOOGLE_APPLICATION_CREDENTIALS=/app/g_auth.json \
    -v /appdata:/app/data \
    -v /usr/bin/docker:/usr/bin/docker \
    -v /app/g_auth.json:/app/g_auth.json \
    --network host \
    "$IMAGE"

echo "Application started successfully."
