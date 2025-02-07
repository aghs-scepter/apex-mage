#!/bin/bash

echo "========================================="
echo "Apex Mage  Copyright (C) 2025  Kev Silver"
echo "This program comes with ABSOLUTELY NO WARRANTY. This software is free for non-commercial use, and you are welcome to redistribute it under certain conditions; read the LICENSE file for details."
echo "========================================="

# Create appdata (persistent DB storage) directory if it doesn't exist
mkdir -p /appdata

# Dialogue prompting user for API keys and optional settings
echo "To use this application, you need to provide a Discord bot token and API keys for each AI service."
echo "These keys are ONLY STORED LOCALLY and are not shared over the internet except when making requests to each service's API."
echo "Press any key to continue."
read -n1 -s
echo ""

echo "You will be prompted for each required API key. Check the README for more info if you don't have them, it includes all of the info you need to get keys for each service."
echo "Press any key to continue."
read -n1 -s
echo ""

echo "Enter your Discord bot token:"
read -r DISCORD_BOT_TOKEN
echo ""

echo "Enter your Anthropic API key:"
read -r ANTHROPIC_API_KEY
echo ""

echo "Enter your Fal.AI API key:"
read -r FAL_KEY
echo ""

echo "There are additional settings you can configure, such as rate-limits for requests to prevent API abuse. The defaults are sensible, but you can customize them. Would you like to configure these settings now? (Y/n)"
read -r CONFIGURE_SETTINGS
CONFIGURE_SETTINGS=${CONFIGURE_SETTINGS:-Y}
CONFIGURE_SETTINGS=$(echo "$CONFIGURE_SETTINGS" | tr '[:upper:]' '[:lower:]')
echo ""

if [ "$CONFIGURE_SETTINGS" = "y" ]; then
    echo "Enter the maximum number of requests per hour for the Anthropic text API (default: 30):"
    read -r ANTHROPIC_RATE_LIMIT
    ANTHROPIC_RATE_LIMIT=${ANTHROPIC_RATE_LIMIT:-30}
    echo ""

    echo "Enter the maximum number of requests per hour for the Fal.AI image API (default: 8):"
    read -r FAL_RATE_LIMIT
    FAL_RATE_LIMIT=${FAL_RATE_LIMIT:-8}
    echo ""

    echo "Enter the number of images to keep in context when prompting the AI. Lower number = cheaper prompts; I don't advise dropping this below 2. (default: 5):"
    read -r IMAGE_CONTEXT_SIZE
    IMAGE_CONTEXT_SIZE=${IMAGE_CONTEXT_SIZE:-5}
    echo ""

elif [ "$CONFIGURE_SETTINGS" = "n" ]; then
    echo "Using default settings..."
    ANTHROPIC_RATE_LIMIT=30
    FAL_RATE_LIMIT=8
    IMAGE_CONTEXT_SIZE=5
    echo ""

else
    echo "Invalid input, expected either Y or N. Using default settings..."
    ANTHROPIC_RATE_LIMIT=30
    FAL_RATE_LIMIT=8
    IMAGE_CONTEXT_SIZE=5
    echo ""
fi

# Save values to .env file
cat <<EOF > /app/.env
DISCORD_BOT_TOKEN=$DISCORD_BOT_TOKEN
ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY
FAL_KEY=$FAL_KEY
ANTHROPIC_RATE_LIMIT=$ANTHROPIC_RATE_LIMIT
FAL_RATE_LIMIT=$FAL_RATE_LIMIT
IMAGE_CONTEXT_SIZE=$IMAGE_CONTEXT_SIZE
EOF

echo "Your API keys and settings have been saved to /app/.env. You can run update-keys.sh to update these keys and settings at any time."
echo "Press any key to continue."
read -n1 -s
echo ""

echo "Starting installation..."

# Check if Docker is installed. If not, grab it and install.
if ! command -v docker &> /dev/null
then
    echo "Docker not found. Installing Docker..."
    # Update package information, ensure that APT works with the https method, and that CA certificates are installed.
    sudo apt-get update
    sudo apt-get install -y apt-transport-https ca-certificates curl software-properties-common

    # Add the Docker repository GPG key
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -

    # Add the Docker repository
    sudo add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"

    # Update the package database with Docker packages from the newly added repo
    sudo apt-get update

    # Install Docker
    sudo apt-get install -y docker-ce
fi

echo ""
echo "========================================="
echo "Installation complete. The application will now start."
echo "You can manually restart the bot at any time by running the start.sh script."
echo "If you have any issues, please check the README for troubleshooting tips. It also includes contact info if you need to reach out to me for help."
echo "Press any key to continue."
read -n1 -s

# Double-check that the startup script is executable
chmod +x start.sh

# Run the startup script
exec ./start.sh