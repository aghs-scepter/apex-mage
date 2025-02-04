#!/bin/bash

ENV_FILE="/app/.env"
SERVICE_SCRIPT="/path/to/start.sh"

if [ ! -f "$ENV_FILE" ]; then
    echo "Environment file not found! Please run the installation script first."
    exit 1
fi

# Read each line in the .env file
while IFS= read -r line; do
    # Skip empty lines and comments
    if [[ -z "$line" || "$line" == \#* ]]; then
        continue
    fi

    # Extract the key
    key=$(echo "$line" | cut -d '=' -f 1)

    # Ask the user if they want to update the key
    read -p "Do you want to update the key $key? (y/n) " update_key
    if [[ "$update_key" == "y" ]]; then
        read -p "Enter the new value for $key: " new_value
        # Update the key in the .env file
        sed -i '' "s/^$key=.*/$key=$new_value/" "$ENV_FILE"
    fi
done < "$ENV_FILE"

# Ask the user if they want to restart the service
read -p "Do you want to restart the service using the new keys? (y/n) " restart_service
if [[ "$restart_service" == "y" ]]; then
    bash "$SERVICE_SCRIPT"
fi