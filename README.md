# Apex Mage

[![CI](https://github.com/aghs-scepter/apex-mage/actions/workflows/ci.yml/badge.svg)](https://github.com/aghs-scepter/apex-mage/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/aghs-scepter/apex-mage)](https://github.com/aghs-scepter/apex-mage/releases/latest)
[![License](https://img.shields.io/badge/license-non--commercial-blue)](LICENSE)

**Apex Mage** is a self-hosted Discord bot that brings AI chat and image capabilities to your server and DMs.

Chat naturally with Claude, generate and edit images, and manage conversation behavior with simple slash commands. Conversations are kept separate per-channel for privacy, and everything runs on your own infrastructure.

Free and open source under a non-commercial license. Feel free to modify and enhance, with a gentle request to contribute improvements back.

**If you need support or encounter issues, [reach out to me on Discord](https://discord.com/users/833494957024870401)**

## Requirements

As a Discord bot, Apex Mage requires some setup via the [Discord Developer Portal](https://discord.com/developers). Instructions for a basic bot setup are available [here](https://discordgsm.com/guide/how-to-get-a-discord-bot-token).

The bot's AI features require API keys for [Anthropic](https://console.anthropic.com) and [Fal.AI](https://fal.ai). When initially setting up the bot, you'll be prompted for these keys, so it would be wise to set up accounts on these services in advance. Instructions are available for both [the Anthropic API](https://docs.anthropic.com/en/api/getting-started#accessing-the-api) and [the Fal.AI API](https://docs.fal.ai/authentication/key-based/).

Finally, you need a way to host the bot. I use [Google Cloud Platform](https://cloud.google.com)'s Compute Engine service for my own hosting (specifically, an `e2-micro` instance), but you can use any Linux virtual machine as long as it can accept HTTP and HTTPS traffic from the internet.

## Quickstart

**NOTE**: This guide assumes that you've set up your developer accounts with Discord, Anthropic, and Fal.AI, and have a Linux virtual machine running.

### 0. Sudo makes this easier

Run `sudo -s` to open a superuser shell.

### 1. Create the app directory and clone the repository

Create the home directory for the app's repository:

```
mkdir -p /app
```

Clone the repository into the folder and navigate to it:

```
git clone https://github.com/aghs-scepter/apex-mage.git /app
```
```
cd /app
```

### 2. Run the install script

The installer will prompt you for your API keys, download dependencies (e.g. Docker), then build and run the bot app:

```
bash install.sh
```

### 3. Test your deployment

In Discord, invite your bot to a server and give it a test command, such as:

```
/prompt prompt:hello world!
```

## Commands

Users can interact with Apex Mage via the slash commands below.

### Chat

- `/prompt` - Chat with the AI. You can optionally include an image in `png`, `jpg`, or `jpeg` format. Conversations are persistent, so you can refer to past messages and images in follow-up prompts.

- `/clear` - Clears the bot's memory of the current channel. All prior prompts, responses, and images are forgotten.

- `/summarize` - Summarizes the conversation to reduce token usage. Useful for long conversations that are hitting context limits.

### Images

- `/create_image` - Generates an image from your text description. The bot offers to refine your prompt before generating.

- `/modify_image` - Edits an existing image. You can pick from recent images in the channel or search Google Images. Supports using up to 3 reference images.

- `/describe_this` - Gets an AI description of an image, useful for generating similar images later. You can upload directly or select from recent/Google images.

- `/upload_image` - Uploads an image to the bot's context for use in future prompts.

### Behavior

- `/set_behavior custom` - Sets a custom personality/behavior for the AI in the current channel.

- `/set_behavior preset` - Selects a saved behavior preset from a dropdown menu.

- `/behavior_preset create` - Creates a new behavior preset for your server.

- `/behavior_preset list` - Lists all behavior presets available on your server.

- `/behavior_preset view` - Views the full details of a specific preset.

- `/behavior_preset edit` - Edits an existing preset (creator or admin only).

- `/behavior_preset delete` - Deletes a preset (creator or admin only).

### Other

- `/my_status` - Checks if you're whitelisted or banned.

- `/show_usage` - Shows usage statistics as a chart.

- `/help` - Displays a quick reference of available commands.

## License

This software is free for non-commercial use. If you would like to use this software commercially, please refer to [the license](LICENSE) for information on what qualifies as commercial use and how to get in contact with me.

## Support/Contact

**If you need support or encounter issues with installation, [reach out to me on Discord](https://discord.com/users/833494957024870401)**
