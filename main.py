import asyncio
import base64
import functools
from typing import Optional, List, Tuple
from os import getenv
import json
import discord
import logging
from discord import app_commands
import ai
import mem
import carousel as carousel

# Timeout constants
DEFAULT_CLEAR_TIMEOUT = 60.0
DEFAULT_PROMPT_TIMEOUT = 240.0
DEFAULT_IMAGE_TIMEOUT = 240.0
DEFAULT_USER_INTERACTION_TIMEOUT = 90.0
DEFAULT_EXTENDED_USER_INTERACTION_TIMEOUT = 600.0

# Add this utility function after imports but before the client class
async def handle_text_overflow(text_type: str, text: str, channel_id: int) -> Tuple[str, Optional[str]]:
    """
    Handle text overflow by truncating and uploading to cloud storage if needed.
    
    Parameters:
    text_type (str): The type of text ("prompt" or "response")
    text (str): The original text
    channel_id (int): The channel ID
    
    Returns:
    tuple[str, Optional[str]]: (modified_text, cloud_url or None)
    """
    if len(text) > 1024:
        try:
            cloud_url = await asyncio.to_thread(
                ai.upload_response_to_cloud,
                text_type,
                channel_id,
                text
            )
            modified_text = text[:950] + f"**--[{text_type.capitalize()} too long! Use the button to see the full {text_type}.]--**"
            return modified_text, cloud_url
        except Exception as ex:
            logging.error(f"Error uploading {text_type} to cloud: {str(ex)}")
            modified_text = text[:950] + f"**--[{text_type.capitalize()} too long! Full {text_type} upload failed.]--**"
            return modified_text, None
    else:
        return text, None

# Global command counter (resets on restart)
_command_count = 0

def count_command(func):
    """Decorator that increments and logs the global command counter."""
    @functools.wraps(func)
    async def wrapper(interaction: discord.Interaction, *args, **kwargs):
        global _command_count
        _command_count += 1
        logging.info(f"Command '{func.__name__}' invoked. Count: {_command_count}")
        return await func(interaction, *args, **kwargs)
    return wrapper

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
        # Check if commands are already registered
        await self.tree.sync()
    
    async def register_commands(self, guild: discord.Guild):
        """
        Registers commands for a specific guild (server or DM).

        Parameters:
        guild (discord.Guild): The guild to register commands for.
        """
        await self.tree.sync(guild=guild)
        await self.change_presence(activity=discord.CustomActivity(name="/help for commands"))
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
@count_command
async def help(interaction: discord.Interaction):
    """
    Display a help message with available commands.
    """
    await interaction.response.defer() # Defer to create a "thinking" spinner and avoid timeout

    # Create the user slug for decorating the result embed
    embed_user = {
        "name": interaction.user.display_name,
        "id": interaction.user.id,
        "pfp": interaction.user.avatar
    }

    help_message = """
    You can interact with the bot using the following commands:

    ========================================

    `/prompt` - Submit a prompt and get a text response. You can include an image.
    `/create_image` - Generate an image using the AI.
    `/upload_image` - Upload an image to the bot.
    `/modify_image` - Modify an image using the AI.
    `/behavior` - Alter the behavior and personality of the text AI.
    `/clear` - Clear the bot's memory of the current channel, including images.
    `/help` - Display this message.

    ========================================

    If you need help or have questions, please contact `@aghs` on Discord.
    """
    help_view = carousel.InfoEmbedView(message=interaction.message,user=embed_user,title="/help",description=help_message,is_error=False,image_data=None)
    await help_view.initialize(interaction)

@client.tree.command()
@app_commands.describe(image="Image file to upload to the bot")
@count_command
async def upload_image(interaction: discord.Interaction, image: discord.Attachment):
    """
    Upload an image to the bot for use in future prompting and image generation.
    """
    await interaction.response.defer()

    # Create the user slug for decorating the result embed
    embed_user = {
        "name": interaction.user.display_name,
        "id": interaction.user.id,
        "pfp": interaction.user.avatar
    }

    images = [] # List to store image data for the DB
    # Check if the upload is an image in a valid format
    file_extension = image.filename.split('.')[-1].lower()
    if file_extension in ['png', 'jpg', 'jpeg']:
        file_data = await image.read()
        image_b64 = base64.b64encode(file_data).decode('utf-8')
        image_b64 = await ai.compress_image(image_b64) # Compress the image to reduce token count

        # Update the filename to ".jpeg" since we use that format to reduce costs
        filename_without_ext = image.filename.rsplit('.', 1)[0]
        new_filename = f"{filename_without_ext}.jpeg"

        # Format for DB storage
        image_data = { "filename": new_filename, "image": image_b64 }
        images.append(image_data)
        image_file = await image.to_file() # Since slash commands don't display attachments by default, the bot will re-upload them.
        str_images = json.dumps(images)

        # Create the origin channel if it doesn't exist in the DB, then add the uploaded image as a message
        mem.create_channel(interaction.channel.id)
        # Include images if required - image uploads are optional when calling this command
        mem.add_message_with_images(interaction.channel.id, 'Anthropic', 'prompt', False, "Uploaded Image", str_images)

        # Create a success message as an embed in Discord
        success_message = "This image was uploaded successfully. You can use it for future `/prompt` and `/modify_image` commands."
        success_view = carousel.InfoEmbedView(message=interaction.message,user=embed_user,title="Upload successful",description=success_message,is_error=False,image_data=image_data)
        await success_view.initialize(interaction)

    else:
        # Create an error message as an embed in Discord
        error_message = "The uploaded file is not a valid image format. Please upload a `.png`, `.jpg`, or `.jpeg` file."
        error_view = carousel.InfoEmbedView(message=interaction.message,user=embed_user,title="Upload error!",description=error_message,is_error=True,image_data=None)
        await error_view.initialize(interaction)
    
@client.tree.command()
@app_commands.describe(prompt='Prompt for the AI to respond to')
@count_command
async def prompt(interaction: discord.Interaction, prompt: str, upload: Optional[discord.Attachment] = None, timeout: Optional[float] = None):
    """
    Submit a prompt to the AI and receive a response.
    
    Parameters:
    prompt (str): The prompt for the AI to respond to.
    upload (Optional[discord.Attachment]): An optional image attachment.
    timeout (Optional[float]): The timeout for the request in seconds. Defaults to DEFAULT_PROMPT_TIMEOUT.
    """
    await interaction.response.defer() # Defer to create a "thinking" spinner and avoid timeout

    # Use default timeout if none provided
    if timeout is None:
        timeout = DEFAULT_PROMPT_TIMEOUT

    # Create the user slug for decorating the result embed
    embed_user = {
        "name": interaction.user.display_name,
        "id": interaction.user.id,
        "pfp": interaction.user.avatar
    }

    try:
        async with asyncio.timeout(timeout):
            # Check if channel is within or outside of prompt rate limits
            within_rate_limit = await mem.enforce_text_rate_limits(interaction.channel.id)

            if within_rate_limit:
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
                
                # Process the prompt for potential overflow before showing the processing message
                display_prompt, full_prompt_url = await handle_text_overflow("prompt", prompt, interaction.channel.id)
                
                # Display a "processing" message while the image is being redrawn
                processing_message = "Thinking... (This may take up to 30 seconds)"
                processing_notes = [
                    {"name": "Prompt", "value": display_prompt}
                ]
                processing_view = carousel.InfoEmbedView(
                    message=interaction.message,
                    user=embed_user,
                    title="Prompt Response",
                    description=processing_message,
                    is_error=False,
                    image_data={"filename": upload.filename, "image": images[0]["image"]} if images else None,
                    notes=processing_notes,
                    full_prompt_url=full_prompt_url
                )
                await processing_view.initialize(interaction)

                # Process the prompt for potential overflow
                display_prompt, full_prompt_url = await handle_text_overflow("prompt", prompt, interaction.channel.id)
                
                # Get the AI response and record it in the database
                response = await ai.prompt('Anthropic', 'prompt', prompt, context)
                mem.add_message(interaction.channel.id, 'Anthropic', "assistant", False, response)
                
                # If old messages needed to be deactivated, notify the user
                if deactivate_old_messages:
                    note = ">Some older messages were removed from context. Use `/clear` to reset the bot!"

                # Handle response overflow
                display_response, full_response_url = await handle_text_overflow("response", response, interaction.channel.id)

                # Update the deferred message with the AI's response. Only include a file upload if required.
                if images:
                    info_notes = [
                        {"name": "Prompt", "value": display_prompt},
                        {"name": "Response", "value": display_response}
                    ]
                    info_view = carousel.InfoEmbedView(
                        message=interaction.message,
                        user=embed_user,
                        title="Prompt Response",
                        is_error=False,
                        image_data={"filename": image_file.filename, "image": images[0]["image"]},
                        notes=info_notes,
                        full_response_url=full_response_url,
                        full_prompt_url=full_prompt_url
                    )
                    await info_view.initialize(interaction)
                else:
                    info_notes = [
                        {"name": "Prompt", "value": display_prompt},
                        {"name": "Response", "value": display_response}
                    ]
                    info_view = carousel.InfoEmbedView(
                        message=interaction.message,
                        user=embed_user,
                        title="Prompt Response",
                        is_error=False,
                        notes=info_notes,
                        full_response_url=full_response_url,
                        full_prompt_url=full_prompt_url
                    )
                    await info_view.initialize(interaction)
            else:
                # If the channel is outside of the rate limit, tell users to chill tf out
                error_message = f"You're sending too many prompts and have been rate-limited. The bot can handle a maximum of {getenv('ANTHROPIC_RATE_LIMIT')} `/prompt` requests per hour. Please wait a few minutes before sending more prompts."
                error_notes = [
                    {"name": "Prompt", "value": prompt},
                ]
                error_view = carousel.InfoEmbedView(message=interaction.message,user=embed_user,title="Prompt error!",description=error_message,is_error=True,image_data=None,notes=error_notes)
                await error_view.initialize(interaction)

    except asyncio.TimeoutError:
        error_message = f"The request timed out after {timeout} seconds. Please try again."
        error_notes = [
            {"name": "Prompt", "value": prompt},
        ]
        error_view = carousel.InfoEmbedView(message=interaction.message,user=embed_user,title="Prompt error!",description=error_message,is_error=True,image_data=None,notes=error_notes)
        await error_view.initialize(interaction)
    
    except Exception as ex:
        error_message = f"An unexpected error occurred while processing your request."
        error_notes = [
            {"name": "Prompt", "value": prompt},
        ]
        error_view = carousel.InfoEmbedView(message=interaction.message,user=embed_user,title="Prompt error!",description=error_message,is_error=True,image_data=None,notes=error_notes)
        await error_view.initialize(interaction)

@client.tree.command()
@app_commands.describe(prompt='Description of the image you want to generate')
@count_command
async def create_image(interaction: discord.Interaction, prompt: str, timeout: Optional[float] = None):
    """
    Submit an image gen request to the AI and receive a response as a file attachment.

    Parameters:
    prompt (str): The prompt for the AI.
    timeout (Optional[float]): The timeout for the request in seconds. Defaults to DEFAULT_IMAGE_TIMEOUT.
    """
    await interaction.response.defer() # Defer to create a "thinking" spinner and avoid timeout

    # Use default timeout if none provided
    if timeout is None:
        timeout = DEFAULT_IMAGE_TIMEOUT

    # Create the user slug for decorating the result embed
    embed_user = {
        "name": interaction.user.display_name,
        "id": interaction.user.id,
        "pfp": interaction.user.avatar
    }

    try:
        async with asyncio.timeout(timeout):
            # Check if channel is within or outside of prompt rate limits
            within_rate_limit = await mem.enforce_image_rate_limits(interaction.channel.id)

            if within_rate_limit:
                # Process the prompt for potential overflow
                display_prompt, full_prompt_url = await handle_text_overflow("prompt", prompt, interaction.channel.id)
                
                # Create the origin channel if it doesn't exist in the DB, then add the prompt message
                mem.create_channel(interaction.channel.id)
                mem.add_message(interaction.channel.id, 'Fal.AI', 'prompt', True, prompt)

                # Display a "processing" message while the image is being redrawn
                processing_message = "Generating an image... (This may take up to 180 seconds)"
                processing_notes = [
                    {"name": "Prompt", "value": display_prompt}
                ]
                processing_view = carousel.InfoEmbedView(
                    message=interaction.message,
                    user=embed_user,
                    title="Image generation in progress",
                    description=processing_message,
                    is_error=False,
                    notes=processing_notes,
                    full_prompt_url=full_prompt_url
                )
                await processing_view.initialize(interaction)

                # Get the AI response and record it in the database. For images, a placeholder is used in place of a message.
                response = await ai.create_image(prompt)
                image_data = await ai.image_strip_headers(response["image"]["url"], "jpeg")
                image_data = await ai.compress_image(image_data) # Compress the image to reduce token count
                str_image = json.dumps([{ "filename": "image.jpeg", "image": image_data }])
                # Dear reader, I am so sorry for this. But Anthropic's API freaks the fuck out if you specify that a bot, rather than a user, uploaded an image as context.
                mem.add_message_with_images(interaction.channel.id, 'Fal.AI', "prompt", False, "Image", str_image)
                
                # Format the image response as a Discord file object
                output_filename, output_file = await ai.format_image_response(image_data, "jpeg", response["has_nsfw_concepts"]) # Fal.AI returns jpeg-format image files
                
                # Update the deferred message with the prompt text and the image file attached
                output_message = "Your image was created successfully. You can use it for future `/prompt` and `/modify_image` commands."
                output_notes = [
                    {"name": "Prompt", "value": display_prompt}
                ]
                output_view = carousel.InfoEmbedView(
                    message=interaction.message,
                    user=embed_user,
                    title="Image generation successful",
                    description=output_message, 
                    is_error=False,
                    notes=output_notes,
                    full_prompt_url=full_prompt_url,
                    image_data={"filename": output_filename, "image": image_data}
                )
                await output_view.initialize(interaction)
            else:
                # If the channel is outside of the rate limit, tell users to chill tf out
                error_message = f"You're requesting too many images and have been rate-limited. The bot can handle a maximum of {getenv('FAL_RATE_LIMIT')} `/create_image` requests per hour. Please wait a few minutes before sending more requests."

                # Process the prompt for potential overflow in error view
                display_prompt, full_prompt_url = await handle_text_overflow("prompt", prompt, interaction.channel.id)
                
                error_notes = [
                    {"name": "Prompt", "value": display_prompt},
                ]
                error_view = carousel.InfoEmbedView(
                    message=interaction.message,
                    user=embed_user,
                    title="Image generation error!",
                    description=error_message,
                    is_error=True,
                    image_data=None,
                    notes=error_notes,
                    full_prompt_url=full_prompt_url
                )
                await error_view.initialize(interaction)

    except asyncio.TimeoutError:
        error_message = f"The image generation request timed out after {timeout} seconds. Please try again."

        # Process the prompt for potential overflow in error view
        display_prompt, full_prompt_url = await handle_text_overflow("prompt", prompt, interaction.channel.id)
        
        error_notes = [
            {"name": "Prompt", "value": display_prompt},
        ]
        error_view = carousel.InfoEmbedView(
            message=interaction.message,
            user=embed_user,
            title="Image generation error!",
            description=error_message,
            is_error=True,
            image_data=None,
            notes=error_notes,
            full_prompt_url=full_prompt_url
        )
        await error_view.initialize(interaction)
    
    except Exception as ex:
        error_message = f"An unexpected error occurred while processing your request."

        # Process the prompt for potential overflow in error view
        display_prompt, full_prompt_url = await handle_text_overflow("prompt", prompt, interaction.channel.id)
        
        error_notes = [
            {"name": "Prompt", "value": display_prompt},
        ]
        error_view = carousel.InfoEmbedView(
            message=interaction.message,
            user=embed_user,
            title="Image generation error!",
            description=error_message,
            is_error=True,
            image_data=None,
            notes=error_notes,
            full_prompt_url=full_prompt_url
        )
        await error_view.initialize(interaction)

@client.tree.command()
@app_commands.describe(prompt='Description of the personality of the AI')
@count_command
async def behavior(interaction: discord.Interaction, prompt: str, timeout: Optional[float] = None):
    """
    Submit a behavior change prompt to the AI which will take effect for future prompts.

    Parameters:
    prompt (str): The behavior change prompt to submit.
    timeout (Optional[float]): The timeout for the request in seconds. Defaults to DEFAULT_PROMPT_TIMEOUT.
    """
    await interaction.response.defer() # Defer to create a "thinking" spinner and avoid timeout

    # Use default timeout if none provided
    if timeout is None:
        timeout = DEFAULT_PROMPT_TIMEOUT

    # Create the user slug for decorating the result embed
    embed_user = {
        "name": interaction.user.display_name,
        "id": interaction.user.id,
        "pfp": interaction.user.avatar
    }

    try:
        async with asyncio.timeout(timeout):
            # Create the origin channel if it doesn't exist in the DB, then add the prompt message
            mem.create_channel(interaction.channel.id)
            mem.add_message(interaction.channel.id, 'Anthropic', 'behavior', False, prompt)

            # Get messages used as context for the prompt
            context = mem.get_visible_messages(interaction.channel.id, 'All Models')

            # Process the prompt for potential overflow before showing any processing message
            display_prompt, full_prompt_url = await handle_text_overflow("prompt", prompt, interaction.channel.id)

            # If you want to add a processing message, include it here
            processing_message = "Updating bot behavior... (This may take a few seconds)"
            processing_notes = [
                {"name": "Prompt", "value": display_prompt}
            ]
            processing_view = carousel.InfoEmbedView(
                message=interaction.message,
                user=embed_user,
                title="Behavior Change",
                description=processing_message,
                is_error=False,
                notes=processing_notes,
                full_prompt_url=full_prompt_url
            )
            await processing_view.initialize(interaction)

            # Record the behavior change in the database. This is a little weird, but is stored as a "message" for consistency.
            response = await ai.prompt('Anthropic', 'behavior', prompt, context)
            mem.add_message(interaction.channel.id, 'Anthropic', "assistant", False, response)

            # Update the deferred message with the prompt text and acknowledgement of the behavior change
            success_message = "The bot's behavior has been updated. Future responses will reflect this change."
            success_notes = [
                {"name": "Prompt", "value": display_prompt},
            ]
            success_view = carousel.InfoEmbedView(message=interaction.message,user=embed_user,title="Behavior change successful",description=success_message,is_error=False,image_data=None,notes=success_notes,full_prompt_url=full_prompt_url)
            await success_view.initialize(interaction)

    except asyncio.TimeoutError:
        error_message = f"The request timed out after {timeout} seconds. Please try again."
        error_notes = [
            {"name": "Prompt", "value": prompt},
        ]
        error_view = carousel.InfoEmbedView(message=interaction.message,user=embed_user,title="Behavior change error!",description=error_message,is_error=True,image_data=None,notes=error_notes)
        await error_view.initialize(interaction)
    
    except Exception as ex:
        error_message = f"An unexpected error occurred while processing your request."
        error_notes = [
            {"name": "Prompt", "value": prompt},
        ]
        error_view = carousel.InfoEmbedView(message=interaction.message,user=embed_user,title="Behavior error!",description=error_message,is_error=True,image_data=None,notes=error_notes)
        await error_view.initialize(interaction)

@client.tree.command()
@app_commands.describe()
@count_command
async def clear(interaction: discord.Interaction, timeout: Optional[float] = None):
    """
    Clear the bot's context for the current channel, starting with empty context and default behavior.
    
    Parameters:
    timeout (Optional[float]): The timeout for the request in seconds. Defaults to DEFAULT_CLEAR_TIMEOUT.
    """
    await interaction.response.defer() # Defer to create a "thinking" spinner and avoid timeout

    # Use default timeout if none provided
    if timeout is None:
        timeout = DEFAULT_CLEAR_TIMEOUT

    # Create the user slug for decorating the result embed
    embed_user = {
        "name": interaction.user.display_name,
        "id": interaction.user.id,
        "pfp": interaction.user.avatar
    }

    async def handle_clear_history(interaction: discord.Interaction, user: dict, confirm_clear: bool):
        """
        Handle the user's choice to clear the bot's context for the current channel.

        Parameters:
        interaction (discord.Interaction): The interaction object for the command.
        user (dict): The user object for the command.
        """
        try:
            async with asyncio.timeout(timeout):
                if confirm_clear:
                    # Create the origin channel if it doesn't exist in the DB, then clear any existing context
                    mem.create_channel(interaction.channel.id)
                    mem.clear_messages(interaction.channel.id, 'All Models')

                    # Update the deferred message with a confirmation that the bot's context has been cleared
                    success_message = "History cleared. The bot has forgotten previous messages and has been reset to default behavior."
                    success_view = carousel.InfoEmbedView(message=interaction.message,user=user,title="Clear history successful",description=success_message,is_error=False,image_data=None)
                    await success_view.initialize(interaction)
                else:
                    # Update the deferred message with a confirmation that the bot's context has not been cleared
                    success_message = "Cancelled the `/clear` command. The bot's context remains unchanged."
                    success_view = carousel.InfoEmbedView(message=interaction.message,user=user,title="Clear history cancelled",description=success_message,is_error=True,image_data=None)
                    await success_view.initialize(interaction)
        
        except asyncio.TimeoutError:
            error_message = f"The request timed out after {timeout} seconds. Please try again."
            error_view = carousel.InfoEmbedView(message=interaction.message,user=user,title="Clear history error!",description=error_message,is_error=True,image_data=None)
            await error_view.initialize(interaction)
        
        except Exception as ex:
            logging.error(f"{ex}")
            error_message = f"An unexpected error occurred while processing your request: {ex}."
            error_view = carousel.InfoEmbedView(message=interaction.message,user=user,title="Clear history error!",description=error_message,is_error=True,image_data=None)
            await error_view.initialize(interaction)

    clear_view = carousel.ClearHistoryConfirmationView(interaction=interaction, user=embed_user, on_select=handle_clear_history)
    await clear_view.initialize(interaction)
    
@client.tree.command()
@app_commands.describe()
@count_command
async def modify_image(interaction: discord.Interaction, timeout: Optional[float] = None):
    """
    Select a recent image to modify using the AI. This command can accept images through a few avenues:
    - select their most recently selected image
    - select a recent image from the channel using a carousel
    - upload an image directly

    Parameters:
    interaction (discord.Interaction): The interaction object for the command.
    timeout (Optional[float]): The timeout for the request in seconds. Defaults to DEFAULT_IMAGE_TIMEOUT.
    """
    await interaction.response.defer() # Defer to create a "thinking" spinner and avoid timeout
    
    # Use default timeout if none provided
    if timeout is None:
        timeout = DEFAULT_IMAGE_TIMEOUT
    
    # Create the user slug for decorating the result embed
    user = {
        "name": interaction.user.display_name,
        "id": interaction.user.id,
        "pfp": interaction.user.avatar
    }

    ### User decides how to select an image ###
    type_selection_result = asyncio.Future()

    async def handle_image_selection(interaction: discord.Interaction, button_selected: str):
        """
        Handle the user's choice to select their most recently uploaded image for modification.

        Parameters:
        interaction (discord.Interaction): The interaction object for the command.
        user (dict): The user object for the command.
        """
        await interaction.response.defer()
        if button_selected == "Recent Images":
            type_selection_result.set_result("Recent Images")
        elif button_selected == "Cancel":
            type_selection_result.set_result("Cancel")
        return

    # First, the user needs to specify their image selection mode
    selection_mode = carousel.ImageSelectionTypeView(
        interaction=interaction,
        user=user,
        on_select=handle_image_selection)
    await selection_mode.initialize(interaction)

    try:
        # Wait for the result with a timeout
        type_selection = await asyncio.wait_for(type_selection_result, timeout=DEFAULT_USER_INTERACTION_TIMEOUT)
        original_message = selection_mode.message
    except asyncio.TimeoutError:
        error_message = f"The request timed out after {DEFAULT_USER_INTERACTION_TIMEOUT} seconds. Please try again."
        error_view = carousel.InfoEmbedView(message=None,user=user,title="Image selection error!",description=error_message,is_error=True,image_data=None)
        await error_view.initialize(interaction)
        return
    
    ### User selects and confirms an image ###

    if type_selection == "Cancel":
        # If the user cancels the image selection, display a message and exit.
        edit_view = carousel.InfoEmbedView(message=original_message,user=user,title="Image modification cancelled",description="Cancelled the `/modify_image` command. No image was selected.",is_error=True,image_data=None)
        await edit_view.initialize(interaction)
        return
    
    elif type_selection == "Recent Images":
        # If the user wants to select from a set of recent images, show them the image carousel
        image_selection_result = asyncio.Future()

        async def handle_image_selection_for_edit(interaction: discord.Interaction, selected_image: dict):
            """
            Handle the user's choice to modify the selected image.

            Parameters:
            interaction (discord.Interaction): The interaction object for the command.
            user (dict): The user object for the command.
            selected_image (dict): The selected image object for modification.
            """
            await interaction.response.defer()
            image_selection_result.set_result(selected_image)
        
        # Get the latest images from the database and format them for the carousel view
        latest_images = mem.get_latest_images(interaction.channel.id, "All Models", 5)
        image_files = await ai.format_latest_images_list(latest_images)

        selector_view = carousel.ImageCarouselView(
            interaction=interaction,
            user=user,
            files=image_files,
            message=original_message,
            on_select=handle_image_selection_for_edit
        )
        await selector_view.initialize(interaction)

        try:
            # Wait for the result with a timeout
            image_selection = await asyncio.wait_for(image_selection_result, timeout=DEFAULT_USER_INTERACTION_TIMEOUT)
            if not image_selection:
                info_message = "Request cancelled by a user. No image was modified."
                info_view = carousel.InfoEmbedView(message=original_message,user=user,title="Image modification cancelled",description=info_message,is_error=True,image_data=None)
                await info_view.initialize(interaction)
                return
        
        except asyncio.TimeoutError:
            error_message = f"The request timed out after {DEFAULT_USER_INTERACTION_TIMEOUT} seconds. Please try again."
            error_view = carousel.InfoEmbedView(message=original_message,user=user,title="Image selection error!",description=error_message,is_error=True,image_data=None)
            await error_view.initialize(interaction)
            return
    
    ### User selects a type of modification for the image ###
    edit_type_result = asyncio.Future()

    async def handle_image_edit_request(interaction: discord.Interaction, edit_type: str, prompt: str):
        """
        Handle the user's choice of image editing type for their image.
        """
        await interaction.response.defer()
        edit_type_result.set_result({"edit_type": edit_type, "prompt": prompt})
    
    edit_view = carousel.ImageEditTypeView(image_data=image_selection, user=user, message=original_message, on_select=handle_image_edit_request)
    await edit_view.initialize(interaction)

    try:
        # Wait for the result with a timeout
        edit_type = await asyncio.wait_for(edit_type_result, timeout=DEFAULT_EXTENDED_USER_INTERACTION_TIMEOUT)
    except asyncio.TimeoutError:
        error_message = f"The request timed out after {DEFAULT_EXTENDED_USER_INTERACTION_TIMEOUT} seconds. Please try again."
        error_view = carousel.InfoEmbedView(message=original_message,user=user,title="Image modification error!",description=error_message,is_error=True,image_data=None)
        await error_view.initialize(interaction)
    
    if edit_type["edit_type"] == "Cancel":
        # If the user cancels the image modification, display a message and exit.
        info_message = "Request cancelled by a user. No image was modified."
        info_view = carousel.InfoEmbedView(message=original_message,user=user,title="Image modification cancelled",description=info_message,is_error=True,image_data=None)
        await info_view.initialize(interaction)
        return
    elif edit_type["edit_type"] in ("Adjust", "Redraw"):
        # If the user requested a redraw, the image is edited with their prompt and a very loose association to the original image
        image_redraw_result = asyncio.Future()

        async def handle_image_redraw(interaction: discord.Interaction, result_image: dict):
            """
            Handle the user's choice to modify the selected image.

            Parameters:
            interaction (discord.Interaction): The interaction object for the command.
            user (dict): The user object for the command.
            prompt (str): The prompt for the AI.
            """
            image_redraw_result.set_result(result_image)
        
        # Process the prompt for potential overflow
        display_prompt, full_prompt_url = await handle_text_overflow("prompt", edit_type["prompt"], interaction.channel.id)
        
        # Display a "processing" message while the image is being redrawn
        processing_message = "Please wait while your image is being modified. This may take up to 90 seconds..."
        processing_notes = [
            {"name": "Prompt", "value": display_prompt}
        ]
        processing_view = carousel.InfoEmbedView(message=original_message,user=user,title="Image modification in progress",description=processing_message,is_error=False,image_data=image_selection,notes=processing_notes,full_prompt_url=full_prompt_url)
        await processing_view.initialize(interaction)
        
        # Ask the user for a prompt to redraw the image
        image_redraw_view = carousel.ImageEditPerformView(interaction=interaction,image_data=image_selection, edit_type=edit_type["edit_type"], user=user, message=original_message, on_complete=handle_image_redraw)
        await image_redraw_view.initialize(interaction)

        try:
            # Wait for the result with a timeout
            image_redraw = await asyncio.wait_for(image_redraw_result, timeout=DEFAULT_USER_INTERACTION_TIMEOUT)
        except asyncio.TimeoutError:
            error_message = f"The request timed out after {DEFAULT_USER_INTERACTION_TIMEOUT} seconds. Please try again."
            error_view = carousel.InfoEmbedView(message=original_message,user=user,title="Image modification error!",description=error_message,is_error=True,image_data=None)
            await error_view.initialize(interaction)
            return
        
        str_image = json.dumps([image_redraw])
        # Dear reader, I am so sorry for this. But Anthropic's API freaks the fuck out if you specify that a bot, rather than a user, uploaded an image as context.
        mem.add_message_with_images(interaction.channel.id, 'Fal.AI', "prompt", False, "Modified Image", str_image)
    
        # Create an embed containing the final product of the image redraw
        success_message = "Image modification complete."
        notes = [
            {"name": "Prompt", "value": display_prompt}
        ]
        success_view = carousel.InfoEmbedView(message=original_message,user=user,title="Image modification successful",description=success_message,is_error=False,notes=notes,image_data=image_redraw,full_prompt_url=full_prompt_url)
        await success_view.initialize(interaction)
        return

if __name__ == "__main__":
    client.run(getenv("DISCORD_BOT_TOKEN"))