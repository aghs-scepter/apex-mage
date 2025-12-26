# Deployment Guide

This document covers automated deployment of Apex Mage to Google Compute Engine (GCE) via GitHub Actions.

## Overview

The deployment workflow automatically deploys the application when:
- A new GitHub release is published
- A manual deployment is triggered via workflow_dispatch

The workflow SSHs to the GCE VM and runs the deployment script, resulting in brief downtime (~5-15 seconds) during container restart.

## Required GitHub Secrets

The following secrets must be configured in your GitHub repository settings:

| Secret | Required | Description |
|--------|----------|-------------|
| `SSH_PRIVATE_KEY` | Yes | Private SSH key for authenticating to the GCE VM |
| `VM_IP` | Yes | IP address of the GCE VM (e.g., `35.123.45.67`) |
| `VM_USER` | Yes | SSH username for the VM (typically the GCE default user) |

## Setup Instructions

### 1. Generate an SSH Key Pair

Generate a dedicated SSH key pair for GitHub Actions deployment:

```bash
# Generate a new ED25519 key pair (recommended)
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/apex-mage-deploy

# Or use RSA if ED25519 is not supported
ssh-keygen -t rsa -b 4096 -C "github-actions-deploy" -f ~/.ssh/apex-mage-deploy
```

When prompted for a passphrase, press Enter to create a key without a passphrase (required for automated deployment).

This creates two files:
- `~/.ssh/apex-mage-deploy` - Private key (keep secret)
- `~/.ssh/apex-mage-deploy.pub` - Public key (add to VM)

### 2. Add the Public Key to the GCE VM

Add the public key to the VM's authorized_keys file:

```bash
# Copy the public key content
cat ~/.ssh/apex-mage-deploy.pub

# SSH to the VM and add the key
ssh <your-user>@<vm-ip>
echo "<paste-public-key-content>" >> ~/.ssh/authorized_keys
```

Alternatively, use the GCP Console:
1. Go to Compute Engine > VM instances
2. Click on your VM instance
3. Click "Edit"
4. Scroll to "SSH Keys" section
5. Click "Add item" and paste the public key content
6. Save

### 3. Configure GitHub Secrets

Add the required secrets to your GitHub repository:

1. Go to your repository on GitHub
2. Navigate to **Settings** > **Secrets and variables** > **Actions**
3. Click **New repository secret** for each secret:

#### SSH_PRIVATE_KEY
- Name: `SSH_PRIVATE_KEY`
- Value: The entire contents of the private key file
  ```bash
  cat ~/.ssh/apex-mage-deploy
  ```
  Copy the full output including `-----BEGIN OPENSSH PRIVATE KEY-----` and `-----END OPENSSH PRIVATE KEY-----`

#### VM_IP
- Name: `VM_IP`
- Value: The external IP address of your GCE VM

#### VM_USER
- Name: `VM_USER`
- Value: Your SSH username on the VM (typically your GCP username, e.g., `john_doe`)

### 4. Verify Setup

Test the SSH connection locally before triggering a deployment:

```bash
ssh -i ~/.ssh/apex-mage-deploy <vm-user>@<vm-ip>
```

If successful, you should be able to connect without a password prompt.

## Triggering Deployments

### Automatic Deployment (Release)

1. Create a new release on GitHub
2. The deployment workflow triggers automatically
3. Monitor the Actions tab for progress

### Manual Deployment

1. Go to **Actions** tab in your repository
2. Select the "Deploy" workflow
3. Click **Run workflow**
4. Select the branch and click **Run workflow**

## Troubleshooting

### SSH Connection Refused
- Verify the VM's external IP address is correct
- Check that the VM's firewall allows SSH (port 22)
- Ensure the public key is correctly added to the VM

### Permission Denied
- Verify the private key in GitHub Secrets is complete (including headers)
- Check that the public key matches the private key
- Ensure the authorized_keys file has correct permissions (600)

### Workflow Not Triggering
- Verify the workflow file exists at `.github/workflows/deploy.yml`
- Check that secrets are configured at the repository level (not environment level)

## Application Environment Variables

The following environment variables must be configured on the deployment VM. These are typically set in a `.env` file or in the container's environment.

### Required in Production

| Variable | Description |
|----------|-------------|
| `ENVIRONMENT` | Set to `production` for production deployments |
| `JWT_SECRET_KEY` | **Required in production.** Secret key for signing JWT tokens. Must be a strong, randomly-generated value (min 32 characters). The application will fail to start if this is not set when `ENVIRONMENT=production` or `APP_ENV=production`. |
| `DISCORD_BOT_TOKEN` | Discord bot authentication token |
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude |
| `FAL_KEY` | Fal.AI API key for image generation |

### Security Note: JWT_SECRET_KEY

The `JWT_SECRET_KEY` is critical for API authentication security:

- **Production enforcement**: The application will refuse to start in production mode without an explicit `JWT_SECRET_KEY`. This prevents accidental use of insecure default keys.
- **Key generation**: Use a cryptographically secure random generator:
  ```bash
  openssl rand -base64 32
  # Or:
  python -c "import secrets; print(secrets.token_urlsafe(32))"
  ```
- **Key rotation**: When rotating keys, existing tokens will become invalid. Plan accordingly.
- **Development mode**: In development (`ENVIRONMENT=development` or unset), a warning is logged but a default key is used for convenience.

## Security Considerations

- The SSH private key should be used exclusively for automated deployments
- Consider rotating the key periodically
- The deployment key should have minimal permissions on the VM
- Never commit private keys to the repository
- Always set `JWT_SECRET_KEY` explicitly in production environments
