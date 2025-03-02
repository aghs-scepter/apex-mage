import asyncio
import base64
import binascii
import discord
from google.cloud import storage
import json
import io
import logging
from PIL import Image
from typing import List
from os import getenv
from uuid import uuid4
from anthropic import Anthropic
import fal_client
 
logging.debug("Loading allowed vendors...")
models = json.loads(open("allowed_vendors.json").read())
logging.debug("Allowed vendors loaded.")

async def create_clients():
    """
    Create and return an Anthropic client using the API key in allowed_vendors.json

    Returns:
    Anthropic: An instance of the Anthropic client.
    """
    logging.debug("Creating Anthropic client...")
    anthropic_client = Anthropic(api_key=getenv('ANTHROPIC_API_KEY'))
    logging.debug("Anthropic client created.")
    return anthropic_client

# Initialize the Anthropic client. We run it in an asyncio event loop to avoid blocking the main thread.
anthropic_client = asyncio.run(create_clients())

async def upload_image_falai(image_data: str, filename: str) -> str:
    """
    Upload an image to Fal.AI for use in image generation or modification.

    Parameters:
    image_data (str): The base64-encoded image data.
    filename (str): The filename of the image.

    Returns:
    str: The URL of the uploaded image.
    """
    logging.debug(f"Uploading image to Fal.AI...")

    response = fal_client.upload(
        data=image_data,
        content_type="jpeg",
        file_name=filename
    )

    logging.debug(f"Image uploaded.")
    return response

async def create_image(prompt: str) -> str:
    """
    Generate an image based on the given prompt using Fal.AI's API.

    Parameters:
    prompt (str): The prompt used to generate the image.

    Returns:
    dict: A dictionary containing the image URL and an indicator of whether the image contains NSFW content.
    """
    logging.debug(f"Generating image for prompt: {prompt}")

    def on_queue_update(update):
        """
        Callback function to handle queue updates

        Parameters:
        update: The update information from the Fal.AI queue.
        """
        logging.debug(f"Still in queue...")

    def subscribe_to_fal_client():
        """
        Subscribe to the Fal.AI client to generate an image. Fal.AI enforces a queue so we need to wait a variable amount of time for the image to be generated.

        Returns:
        dict: The result from the Fal.AI client once the image is generated.
        """
        return fal_client.subscribe(
            application=models["Fal.AI"]["model"]["create"],
            arguments={ "prompt": prompt , "enable_safety_checker": False, "sync_mode": True, "safety_tolerance": 5 },
            with_logs=True,
            on_queue_update=on_queue_update
        )
    
    # Run the Fal.AI subscription in a separate thread to avoid blocking the main thread
    result = await asyncio.to_thread(subscribe_to_fal_client)

    output = { "image": result["images"][0], "filename": "image.jpeg", "has_nsfw_concepts": result["has_nsfw_concepts"][0] }
    logging.debug(f"Image generated.")
    return output

async def modify_image(image_data: str, prompt: str, guidance_scale: float) -> str:
    """
    Modify an image based on the given prompt using Fal.AI's API.

    Parameters:
    image_data (str): The base64-encoded image data.
    prompt (str): The prompt used to modify the image.

    Returns:
    dict: A dictionary containing the modified image URL and an indicator of whether the image contains NSFW content.
    """
    logging.debug(f"Generating image for prompt: {prompt}")

    image_url = await upload_image_falai(base64.b64decode(image_data), "image.jpeg")

    def on_queue_update(update):
        """
        Callback function to handle queue updates

        Parameters:
        update: The update information from the Fal.AI queue.
        """
        logging.debug(f"Still in queue...")

    def subscribe_to_fal_client():
        """
        Subscribe to the Fal.AI client to modify an image. Fal.AI enforces a queue so we need to wait a variable amount of time for the image to be generated.

        Returns:
        dict: The result from the Fal.AI client once the image is generated.
        """
        return fal_client.subscribe(
            application=models["Fal.AI"]["model"]["modify"],
            arguments={ "control_image_url": image_url, "prompt": prompt , "num_inference_steps": 28, "guidance_scale": guidance_scale, "enable_safety_checker": False, "sync_mode": True, "safety_tolerance": 5 },
            with_logs=True,
            on_queue_update=on_queue_update
        )
    
    # Run the Fal.AI subscription in a separate thread to avoid blocking the main thread
    result = await asyncio.to_thread(subscribe_to_fal_client)

    output = { "image": result["images"][0], "filename": "image.jpeg", "has_nsfw_concepts": result["has_nsfw_concepts"][0] }
    logging.debug(f"Image modified.")
    return output

async def prompt(vendor: str, prompt_type: str, prompt: str, context) -> str:
    """
    Route the prompt to the appropriate vendor model. Currently only supports Anthropic.

    Parameters:
    vendor (str): The vendor to use. The exact model is determined by the vendor's entry in `allowed_vendors.json`.
    prompt_type (str): The type of prompt. Can be 'behavior' or 'prompt'.
    prompt (str): The prompt used to generate the response.
    context: The context for processing the prompt. This includes past messages exchanged with the bot.

    Returns:
    str: The response generated by the vendor model.
    """
    logging.debug(f"Prompting {vendor} model with prompt: {prompt}")
    if vendor == "Anthropic":
        return await prompt_anthropic(prompt_type, prompt, context)
    else:
        raise ValueError(f"Vendor {vendor} not supported.")

async def prompt_anthropic(prompt_type: str, prompt: str, context) -> str:
    """
    Generate a textual response based on the given prompt using the Anthropic API.

    Parameters:
    prompt_type (str): The type of prompt. Can be 'behavior' (no API call, only a config change) or 'prompt' (API call expecting a result).
    prompt (str): The prompt used to generate the response.

    Returns:
    str: The response generated by the Anthropic API.
    """
    model = models["Anthropic"]["model"]
    
    # If this is a behavior modification prompt, acknowledge the new system prompt
    if prompt_type == 'behavior':
        return f"I will use the following system prompt for future interactions:\n\n{prompt}"
    
    # For regular prompts, format the prompt and get system context
    formatted_prompt, system_prompt = await format_prompt_anthropic(prompt_type, prompt, context)
    
    # Retry vars
    max_retries = 4
    backoff_factor = 2

    for retry in range(max_retries):
        try:
            response = anthropic_client.messages.create(
                model=model,
                max_tokens=8192,
                system=system_prompt,
                messages=formatted_prompt
            )
            return response.content[0].text
        except Exception as ex:
            if "529" in str(ex): # Anthropic can throw 529 errors when servers are overloaded
                sleep_time = backoff_factor ** retry
                logging.warning(f"Anthropic client returned a 529 error. Retrying in {sleep_time:.2f} seconds...")
                await asyncio.sleep(sleep_time)
            else:
                raise ex

    raise Exception("Max retries exceeded for Anthropic API call")

async def format_prompt_anthropic(prompt_type: str, prompt: str, context) -> tuple[str, str]:
    """
    Format the behavior setting and combined prompt + context to fit the Anthropic API requirements.

    Parameters:
    prompt_type (str): The type of prompt. Can be 'behavior' or 'prompt'.
    prompt (str): The prompt used to generate the response.
    context: The context for processing the prompt. This includes past messages exchanged with the bot.

    Returns:
    tuple[str, str]: A tuple containing the formatted prompt and the behavior definition.
    """
    logging.debug(f"Prompt: {prompt}")
    logging.debug(f"Context: {context}")
    formatted_prompt = []
    messages_with_recent_images = []
    image_context_size = int(getenv("IMAGE_CONTEXT_SIZE"))
    
    # Fetch the most recent system prompt from context if it exists, otherwise use default
    system_prompt = "You are an informational kiosk-like bot in an environment in which users have relatively short attention spans. You offer concise responses to prompts, offering detailed explanations only when necessary in response to follow-up questions on the same topic. Try to keep responses limited to 150 words or less unless providing code or technical documentation responses, avoid using bulleted or numbered lists, and use Discord message syntax when responding. Remember: Standard markdown syntax will NOT work in Discord, you must use Discord's own message syntax. Do not use emojis unless specifically prompted to include them."
    if context:
        for row in reversed(context):
            if row["message_images"] != "[]":
                if len(messages_with_recent_images) < image_context_size:
                    messages_with_recent_images.append(row["channel_message_id"])
            if row["message_type"] == "behavior":
                system_prompt = row["message_data"]
                break

    # Building the context for the prompt
    if context:
        for row in context:
            if row["message_type"] != "behavior":
                # The interaction type of the message (system-generated, user prompt, etc.)
                interaction_type = await convert_to_interaction_type(row["message_type"])

                # Start building the content for the prompt
                prompt_content = []

                # If the message contains recent images, add them to the prompt
                if row["channel_message_id"] in messages_with_recent_images:
                    images = json.loads(row["message_images"])
                    for idx, image in enumerate(images):
                        file_extension = image["filename"].split(".")[-1]
                        media_label = { "type": "text", "text": f"Image {idx + 1}" }
                        media = {"type": "image", "source": {"type": "base64", "media_type": f"image/{file_extension}", "data": image["image"]}}
                        prompt_content.append(media_label)
                        prompt_content.append(media)
                else:
                    # Add the text content of the message to the prompt
                    prompt_content.append({ "type": "text", "text": row["message_data"] })

                # Construct the final prompt for the API
                contextual_prompt = { "role": interaction_type, "content": prompt_content }
                formatted_prompt.append(contextual_prompt)

    return formatted_prompt, system_prompt

async def convert_to_interaction_type(prompt_type: str) -> str:
    """
    Convert human-readable prompt types to the interaction types used by the Anthropic API.

    Parameters:
    prompt_type (str): The human-readable prompt type.

    Returns:
    str: The interaction type used by the Anthropic API.
    """
    if prompt_type == 'prompt':
        return "user"
    elif prompt_type == 'behavior':
        return "system"
    elif prompt_type == 'assistant':
        return "assistant"
    else:
        raise ValueError(f"Prompt type {prompt_type} not recognized.")
    
async def image_strip_headers(image_data: str, file_extension: str) -> str:
    """
    Strip the header from a base64-encoded image.

    Parameters:
    image_data (str): The base64-encoded image data.

    Returns:
    str: The image data with the header removed.
    """
    if image_data.startswith(f"data:image/{file_extension};base64,"):
        return image_data[len(f"data:image/{file_extension};base64,"):]
    return image_data

async def compress_image(image_data_b64: str, max_size=(512, 512), quality=75) -> str:
    """
    Compress an image to reduce its size (saving on API costs) while maintaining quality.

    Parameters:
    image_data (str): The base64-encoded image data.
    max_size (tuple): The maximum size of the image in pixels.
    quality (int): The quality of the compressed image. Range: 1-100.

    Returns:
    str: The base64-encoded compressed image data.
    """
    try:
        image_data = base64.b64decode(image_data_b64)
    except binascii.Error:
        # Add extra padding only if initial decode fails
        while len(image_data_b64) % 4:
            image_data_b64 += '='
        return base64.b64decode(image_data_b64)
    img = Image.open(io.BytesIO(image_data))

    # Convert RGBA or P modes to RGB if necessary
    if img.mode in ('RGBA', 'P'):
        img = img.convert('RGB')

    # Calculate new dimensions while maintaining aspect ratio
    ratio = min(max_size[0]/img.size[0], max_size[1]/img.size[1])
    new_size = tuple([int(x*ratio) for x in img.size])

    # Resize and compress the image
    img = img.resize(new_size, Image.Resampling.LANCZOS)
    
    # Save to BytesIO buffer
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG', quality=quality, optimize=True)
    
    # Convert back to base64
    compressed_image_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
    
    return compressed_image_b64

async def format_latest_images_list(image_rows: list) -> List[dict]:
    """
    Format image contents of the rows into a list of image data dicts.

    Parameters:
    image_rows (list): A list of rows containing image data.

    Returns:
    List[dict]: A list of dicts containing images and their metadata.
    """
    logging.debug(f"Formatting image list...")
    image_files = []

    # Iterate through the image rows and create a dict for each image
    for index, row in enumerate(reversed(image_rows)): # Query returns reverse-chronological; Reverse here to get chronological order
        image_message_id = row["channel_message_id"]
        image_data = json.loads(row["message_images"])[0]["image"]
        image_files.append({
                "message_id": image_message_id,
                "filename": f"image_{index + 1}.jpeg",
                "image": image_data
        })

    return image_files

async def format_image_response(image_data_b64: str, file_extension: str, nsfw: bool) -> str:
    """
    Convert the raw image response from Fal.AI to a Discord file object that can be attached to a message.

    Parameters:
    response (dict): The raw image response from Fal.AI.

    Returns:
    discord.File: A Discord file object containing the image.
    """
    logging.debug(f"Formatting image response...")
    
    # Decode the base64 data and create a file object
    image_data = base64.b64decode(image_data_b64)
    image_file = io.BytesIO(image_data)
    if nsfw:
        output_filename = f"SPOILER_{uuid4()}.jpeg" # The "SPOILER_" prefix will hide the image by default in Discord chats
    else:
        output_filename = f"{uuid4()}.jpeg"
    
    return output_filename, discord.File(image_file, filename=output_filename)

async def generate_embed(user: str, prompt: str, response: str, note: str = None, error: str = None, inline: bool = True, filename: str = None) -> discord.Embed:
    """
    Generate an embed to display results of a bot slash command.

    Returns:
    discord.Embed: An embed containing the prompt and response, including image if one is provided.
    """
    embed = discord.Embed()

    # Setting author info to link to the bot's GitHub repository
    embed.set_author(name=f'{user["name"]} (via Apex Mage)', url="https://github.com/aghs-scepter/apex-mage", icon_url=f'{user["pfp"]}')

    # If an image was provided, add it to the embed
    if filename:
        embed.set_image(url=f"attachment://{filename}")

    # Add bot notes, e.g. context truncations and reminders
    if note:
        embed.add_field(name="Note", value=note, inline=False) # Notes are always inline=False

    # If no error message is provided, include the prompt and response fields
    if not error:
        embed.color = 0x1CBFA1
        embed.add_field(name="Prompt", value=prompt, inline=inline)
        embed.add_field(name="Response", value=response, inline=inline)

    # If this is an error message, ignore the response field and include an error section instead.
    else:
        embed.color = 0xE91515
        embed.add_field(name="Prompt", value=prompt, inline=False) # Error messages are always inline=False
        embed.add_field(name="!! Error !!", value=error, inline=False)
    
    return embed

async def generate_embed_informational(user: str, note_title: str, note: str, error: str = None) -> discord.Embed:
    """
    Generate an embed to display results of a bot slash command.

    Returns:
    discord.Embed: An embed containing the prompt and response, including image if one is provided.
    """
    embed = discord.Embed()

    # Setting author info to link to the bot's GitHub repository
    embed.set_author(name=f'{user["name"]} (via Apex Mage)', url="https://github.com/aghs-scepter/apex-mage", icon_url=f'{user["pfp"]}')

    # Add bot notes, e.g. context truncations and reminders
    # If no error message is provided, display the note
    if not error:
        embed.color = 0x1CBFA1
        embed.add_field(name=note_title, value=note, inline=False)
    
    else:
        embed.color = 0xE91515
        embed.add_field(name="!! Error !!", value=error, inline=False)
    
    return embed
    
def upload_response_to_cloud(channel_id: int, response: str) -> str:
    """
    Upload a text response from the AI to Google Cloud Storage for later retrieval.

    Parameters:
    channel_id (int): The ID of the channel where the response was generated.
    message_id (int): The ID of the message containing the response.
    response (str): The response to upload.

    Returns:
    str: The URL of the uploaded response.
    """
    logging.debug(f"Uploading prompt response to cloud...")

    try:
        # Create a storage client and get the bucket
        storage_client = storage.Client()
        bucket = storage_client.bucket("apex-mage-data")

        # Create a blob
        blob = bucket.blob(f"overflow_responses/{channel_id}/{uuid4()}/response.md")

        # Upload the response and fetch the URL
        blob.upload_from_string(
            response,
            content_type="text/markdown"
        )
        url = blob.public_url

        logging.debug(f"Response uploaded.")
        return url
    except Exception as ex:
        logging.error(f"Failed to upload response to cloud: {str(ex)}")
        raise