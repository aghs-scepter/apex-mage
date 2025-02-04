# Apex Mage
**Apex Mage** is a versatile, self-hosted Discord bot that brings AI chat and image capabilities to your server and DMs.

Engage in natural conversation, analyze images, and generate art(?) using simple slash commands. You'll get context-aware responses while respecting user privacy through channel- and DM-specific chats that are kept completely separate.

Free and open source under a collaborative license - feel free to modify and enhance, with a gentle request to contribute improvements back to the community.

**If you need support or encounter issues with installation, [reach out to me on Discord](https://discord.com/users/833494957024870401)**

## Requirements
As a Discord bot, Apex Mage requires some setup via the [Discord Developer Portal](https://discord.com). Instructions for a basic bot setup are available [here](https://discordgsm.com/guide/how-to-get-a-discord-bot-token).

The bot's AI features require API keys for [Anthropic](https://console.anthropic.com) and [Fal.AI](https://fal.ai). When initially setting up the bot, you'll be prompted for these keys, so it would be wise to set up accounts on these services in advance. Instructions for are available for both [the Anthropic API](https://docs.anthropic.com/en/api/getting-started#accessing-the-api) and [the Fal.AI API](https://docs.fal.ai/authentication/key-based/).

Finally, you need a way to host the bot. I use [Google Cloud Platform](https://cloud.google.com)'s Compute Engine service for my hosting (specifically, an `e2-micro` instance), but you can use any Linux virtual machine.

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

- `/prompt` - Submits a prompt to the Anthropic API, returning a text response. Users can optionally include an image in `png`, `jpg`, or `jpeg` format with their prompt. Conversations with the bot are persistent, so users can refer to past text and images in follow-up prompts.

- `/create_image` - Submits a prompt to the Fal.AI API, returning an image as a message attachment. This command **does not include conversation context**, so prompts should include all of the information needed to generate the image.

- `/behavior` - Changes the behavior and personality of the text bot based on the submitted prompt. This only changes the behavior of the bot reached via the `/prompt` command and does not affect image generation.

- `/clear` - Resets the bot to default state. All prior prompts, responses, and images are cleared from memory, and the bot's text behavior is set to default.

- `/help` - Displays a list of commands with quick instructions for use.

## Support/Contact

**If you need support or encounter issues with installation, [reach out to me on Discord](https://discord.com/users/833494957024870401)**