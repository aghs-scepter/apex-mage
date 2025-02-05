import base64
from typing import Optional
from os import getenv
import json
import discord
import logging
from discord import app_commands
import ai
import mem

class DiscordAiClient(discord.Client):
    """
    A custom Discord client that handles bot events and command registration.

    Attributes:
    tree (app_commands.CommandTree): The command tree for the bot.
    """
    def __init__(self):
        """
        Initialize the DiscordAiClient instance.
        """
        intents = discord.Intents.default()
        intents.messages = True # Add intent to allow server messages
        intents.dm_messages = True # Add intent to allow direct messages/PMs
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        """
        Synchronizes the command tree with Discord.
        """
        await self.tree.sync()
    
    async def register_commands(self, guild: discord.Guild):
        """
        Registers commands for a specific guild (server or DM).

        Parameters:
        guild (discord.Guild): The guild to register commands for.
        """
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        print(f"Registered commands for guild: {guild.name} (ID: {guild.id})")

    async def on_guild_join(self, guild: discord.Guild):
        """
        Handles command registration when the bot joins a new guild.

        Parameters:
        guild (discord.Guild): The guild the bot has joined.
        """
        await self.register_commands(guild)
        print(f"Joined new guild: {guild.name} (ID: {guild.id})")

client = DiscordAiClient()
mem.validate_vendors() # Validate vendors on bot startup

@client.event
async def on_ready():
    """
    On bot startup, log success and re-register commands for all guilds.
    """
    logging.debug(f'Logged in as {client.user} (ID: {client.user.id})')
    logging.debug('------')
    for guild in client.guilds:
        await client.register_commands(guild)

@client.tree.command()
@app_commands.describe()
async def help(interaction: discord.Interaction):
    """
    Display a help message with available commands.
    """
    await interaction.response.send_message(
        content="**Available Commands:**\n"
                "`/prompt` - Submit a prompt and get a text response. You can optionally include an image attachment.\n"
                "`/create_image` - Submit an image generation request to the AI.\n"
                "`/behavior` - Alter the behavior and personality of the text AI.\n"
                "`/clear` - Clear the bot's context for the current channel. It will forget everything, starting a new conversation with default behavior."
                "`/help` - Display this message."
    )

@client.tree.command()
@app_commands.describe(prompt='Prompt for the AI to respond to')
async def prompt(interaction: discord.Interaction, prompt: str, upload: Optional[discord.Attachment] = None):
    """
    Submit a prompt to the AI and receive a response.
    """
    await interaction.response.defer() # Defer to create a "thinking" spinner and avoid timeout

    # Process any images attached to the prompt into a list of b64 encoded strings
    images = []
    if upload:
        # Check if the upload is an image in a valid format
        file_extension = upload.filename.split('.')[-1].lower()
        if file_extension in ['png', 'jpg', 'jpeg']:
            file_data = await upload.read()
            image_b64 = base64.b64encode(file_data).decode('utf-8')
            image_b64 = await ai.compress_image(image_b64) # Compress the image to reduce token count

            # Update the filename to ".jpeg" since we use that format to reduce costs
            filename_without_ext = upload.filename.rsplit('.', 1)[0]
            new_filename = f"{filename_without_ext}.jpeg"

            images.append({ "filename": new_filename, "image": image_b64 })
            image_file = await upload.to_file() # Since slash commands don't display attachments by default, the bot will re-upload them.
    str_images = json.dumps(images)

    # Create the origin channel if it doesn't exist in the DB, then add the prompt message
    mem.create_channel(interaction.channel.id)
    # Include images if required - image uploads are optional when calling this command
    if images:
        mem.add_message_with_images(interaction.channel.id, 'Anthropic', 'prompt', False, prompt, str_images)
    else:
        mem.add_message(interaction.channel.id, 'Anthropic', 'prompt', False, prompt)

    # Get messages used as context for the prompt
    context = mem.get_visible_messages(interaction.channel.id, 'All Models')

    # Determine if we need to deactivate old messages
    deactivate_old_messages = False
    if len(context) >= mem.WINDOW:
        deactivate_old_messages = True # Use this to notify user that old messages were pruned
        mem.deactivate_old_messages(interaction.channel.id, 'All Models', mem.WINDOW)
    
    # Get the AI response and record it in the database
    response = await ai.prompt('Anthropic', 'prompt', prompt, context)
    mem.add_message(interaction.channel.id, 'Anthropic', "assistant", False, response)
    
    # Build the response message for Discord
    message = ""
    if deactivate_old_messages:
        message += "> `Note`: Some older messages were removed from context. Use `/clear` to reset the bot!\n"
    message += f'`Prompt:` {prompt}\n\n`Response:` {response}'

    if len(message) > 2000:
        message = message[:1975] + "--[response too long]--" # Discord has a 2000 character limit for messages

    # Update the deferred message with the AI's response. Only include a file upload if required.
    if images:
        await interaction.followup.send(content=message, file=image_file)
    else:
        await interaction.followup.send(content=message)

@client.tree.command()
@app_commands.describe(prompt='Description of the image you want to generate')
async def create_image(interaction: discord.Interaction, prompt: str):
    """
    Submit an image gen request to the AI and receive a response as a file attachment.

    Parameters:
    prompt (str): The prompt for the AI.
    """
    await interaction.response.defer() # Defer to create a "thinking" spinner and avoid timeout

    # Create the origin channel if it doesn't exist in the DB, then add the prompt message
    mem.create_channel(interaction.channel.id)
    mem.add_message(interaction.channel.id, 'Fal.AI', 'prompt', True, prompt)

    # Get the AI response and record it in the database. For images, a placeholder is used in place of a message.
    response = await ai.create_image(prompt)
    image_data = await ai.image_strip_headers(response["image"]["url"], "jpeg")
    image_data = await ai.compress_image(image_data) # Compress the image to reduce token count
    str_image = json.dumps([{ "filename": "image.jpeg", "image": image_data }])
    # Dear reader, I am so sorry for this. But Anthropic's API freaks the fuck out if you specify that a bot, rather than a user, uploaded an image as context.
    mem.add_message_with_images(interaction.channel.id, 'Fal.AI', "prompt", False, "Image", str_image)
    
    # Format the image response as a Discord file object
    output_file = await ai.format_image_response(image_data, "jpeg", response["has_nsfw_concepts"]) # Fal.AI returns jpeg-format image files
    
    # Update the deferred message with the prompt text and the image file attached
    await interaction.followup.send(content=f'`Prompt:` {prompt}\n\n`Response:`', file=output_file)

@client.tree.command()
@app_commands.describe(prompt='Description of the personality of the AI')
async def behavior(interaction: discord.Interaction, prompt: str):
    """
    Submit a behavior change prompt to the AI which will take effect for future prompts.

    Parameters:
    prompt (str): The behavior change prompt to submit.
    """
    await interaction.response.defer() # Defer to create a "thinking" spinner and avoid timeout

    # Create the origin channel if it doesn't exist in the DB, then add the prompt message
    mem.create_channel(interaction.channel.id)
    mem.add_message(interaction.channel.id, 'Anthropic', 'behavior', False, prompt)

    # Get messages used as context for the prompt
    context = mem.get_visible_messages(interaction.channel.id, 'All Models')

    # Record the behavior change in the database. This is a little weird, but is stored as a "message" for consistency.
    response = await ai.prompt('Anthropic', 'behavior', prompt, context)
    mem.add_message(interaction.channel.id, 'Anthropic', "assistant", False, response)

    # Update the deferred message with the prompt text and acknowledgement of the behavior change
    message = f'`Behavior Update:` {prompt}\n\n`Response:` New behavior set.'
    await interaction.followup.send(content=message)

@client.tree.command()
@app_commands.describe()
async def clear(interaction: discord.Interaction):
    """
    Clear the bot's context for the current channel, starting with empty context and default behavior.
    """
    mem.create_channel(interaction.channel.id)
    mem.clear_messages(interaction.channel.id, 'All Models')
    await interaction.response.send_message(f'History cleared. The bot has forgotten previous messages and has been reset to default behavior.')

if __name__ == "__main__":
    client.run(getenv("DISCORD_BOT_TOKEN"))