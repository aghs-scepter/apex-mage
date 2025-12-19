"""Chat-related Discord slash commands."""

import asyncio
import base64
import json
from os import getenv
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands

from src.adapters import WINDOW
from src.clients.discord.decorators import count_command
from src.clients.discord.utils import create_embed_user, handle_text_overflow
from src.clients.discord.views.carousel import (
    ClearHistoryConfirmationView,
    InfoEmbedView,
)
from src.core.image_utils import compress_image
from src.core.providers import ChatMessage

if TYPE_CHECKING:
    from src.clients.discord.bot import DiscordBot

# Timeout constants
DEFAULT_PROMPT_TIMEOUT = 240.0
DEFAULT_CLEAR_TIMEOUT = 60.0


def _convert_context_to_messages(
    context: list[dict[str, Any]],
) -> tuple[list[ChatMessage], str | None]:
    """Convert database context to ChatMessage list and extract system prompt.

    Args:
        context: List of message dicts from the repository.

    Returns:
        Tuple of (chat_messages, system_prompt) where system_prompt is the most
        recent behavior message or None.
    """
    messages: list[ChatMessage] = []
    system_prompt: str | None = None

    # Find the most recent behavior message (system prompt)
    for row in reversed(context):
        if row["message_type"] == "behavior":
            system_prompt = row["message_data"]
            break

    # Convert non-behavior messages to ChatMessages
    for row in context:
        msg_type = row["message_type"]
        if msg_type == "behavior":
            continue  # Skip behavior messages - they become system prompt

        # Map message_type to ChatMessage role
        if msg_type == "prompt":
            role = "user"
        elif msg_type == "assistant":
            role = "assistant"
        else:
            continue  # Skip unknown types

        messages.append(ChatMessage(role=role, content=row["message_data"]))

    return messages, system_prompt


def register_chat_commands(bot: "DiscordBot") -> None:
    """Register chat-related commands with the bot.

    Args:
        bot: The Discord bot instance.
    """

    @bot.tree.command()
    @app_commands.describe()
    @count_command
    async def help(interaction: discord.Interaction) -> None:
        """Display a help message with available commands."""
        await interaction.response.defer()

        embed_user = create_embed_user(interaction)

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
        help_view = InfoEmbedView(
            message=interaction.message,
            user=embed_user,
            title="/help",
            description=help_message,
            is_error=False,
            image_data=None,
        )
        await help_view.initialize(interaction)

    @bot.tree.command()
    @app_commands.describe(prompt="Prompt for the AI to respond to")
    @count_command
    async def prompt(
        interaction: discord.Interaction,
        prompt: str,
        upload: discord.Attachment | None = None,
        timeout: float | None = None,
    ) -> None:
        """Submit a prompt to the AI and receive a response.

        Args:
            interaction: The Discord interaction.
            prompt: The prompt for the AI to respond to.
            upload: An optional image attachment.
            timeout: The timeout for the request in seconds.
        """
        assert interaction.channel_id is not None, "Command must be used in a channel"
        channel_id = interaction.channel_id
        await interaction.response.defer()

        if timeout is None:
            timeout = DEFAULT_PROMPT_TIMEOUT

        embed_user = create_embed_user(interaction)

        try:
            async with asyncio.timeout(timeout):
                rate_check = await bot.rate_limiter.check(interaction.user.id, "chat")

                if rate_check.allowed:
                    images = []
                    if upload:
                        file_extension = upload.filename.split(".")[-1].lower()
                        if file_extension in ["png", "jpg", "jpeg"]:
                            file_data = await upload.read()
                            image_b64 = base64.b64encode(file_data).decode("utf-8")
                            # compress_image is sync, run in thread to avoid blocking
                            image_b64 = await asyncio.to_thread(compress_image, image_b64)

                            filename_without_ext = upload.filename.rsplit(".", 1)[0]
                            new_filename = f"{filename_without_ext}.jpeg"

                            images.append({"filename": new_filename, "image": image_b64})
                            await upload.to_file()
                    str_images = json.dumps(images)

                    await bot.repo.create_channel(channel_id)
                    if images:
                        await bot.repo.add_message_with_images(
                            channel_id,
                            "Anthropic",
                            "prompt",
                            False,
                            prompt,
                            str_images,
                        )
                    else:
                        await bot.repo.add_message(
                            channel_id, "Anthropic", "prompt", False, prompt
                        )

                    context = await bot.repo.get_visible_messages(
                        channel_id, "All Models"
                    )

                    deactivate_old_messages = False
                    if len(context) >= WINDOW:
                        deactivate_old_messages = True
                        await bot.repo.deactivate_old_messages(
                            channel_id, "All Models", WINDOW
                        )

                    display_prompt, full_prompt_url = await handle_text_overflow(
                        bot, "prompt", prompt, channel_id
                    )

                    processing_message = "Thinking... (This may take up to 30 seconds)"
                    processing_notes = [{"name": "Prompt", "value": display_prompt}]
                    processing_view = InfoEmbedView(
                        message=interaction.message,
                        user=embed_user,
                        title="Prompt Response",
                        description=processing_message,
                        is_error=False,
                        image_data=(
                            {"filename": upload.filename, "image": images[0]["image"]}
                            if images
                            else None
                        ),
                        notes=processing_notes,
                        full_prompt_url=full_prompt_url,
                    )
                    await processing_view.initialize(interaction)

                    display_prompt, full_prompt_url = await handle_text_overflow(
                        bot, "prompt", prompt, channel_id
                    )

                    # Convert context to ChatMessages and extract system prompt
                    chat_messages, system_prompt = _convert_context_to_messages(context)
                    chat_response = await bot.ai_provider.chat(
                        chat_messages, system_prompt=system_prompt
                    )
                    response = chat_response.content
                    await bot.repo.add_message(
                        channel_id, "Anthropic", "assistant", False, response
                    )

                    await bot.rate_limiter.record(interaction.user.id, "chat")

                    if deactivate_old_messages:
                        pass  # Could add note about pruned messages

                    display_response, full_response_url = await handle_text_overflow(
                        bot, "response", response, channel_id
                    )

                    info_notes = [
                        {"name": "Prompt", "value": display_prompt},
                        {"name": "Response", "value": display_response},
                    ]
                    info_view = InfoEmbedView(
                        message=interaction.message,
                        user=embed_user,
                        title="Prompt Response",
                        is_error=False,
                        image_data=(
                            {"filename": upload.filename, "image": images[0]["image"]}
                            if images
                            else None
                        ),
                        notes=info_notes,
                        full_response_url=full_response_url,
                        full_prompt_url=full_prompt_url,
                    )
                    await info_view.initialize(interaction)
                else:
                    wait_msg = (
                        f" Try again in {int(rate_check.wait_seconds)} seconds."
                        if rate_check.wait_seconds
                        else ""
                    )
                    error_message = (
                        f"You're sending too many prompts and have been rate-limited. "
                        f"The bot can handle a maximum of "
                        f"{getenv('ANTHROPIC_RATE_LIMIT', '30')} `/prompt` requests "
                        f"per hour.{wait_msg}"
                    )
                    error_notes = [{"name": "Prompt", "value": prompt}]
                    error_view = InfoEmbedView(
                        message=interaction.message,
                        user=embed_user,
                        title="Prompt error!",
                        description=error_message,
                        is_error=True,
                        image_data=None,
                        notes=error_notes,
                    )
                    await error_view.initialize(interaction)

        except TimeoutError:
            error_message = (
                f"The request timed out after {timeout} seconds. Please try again."
            )
            error_notes = [{"name": "Prompt", "value": prompt}]
            error_view = InfoEmbedView(
                message=interaction.message,
                user=embed_user,
                title="Prompt error!",
                description=error_message,
                is_error=True,
                image_data=None,
                notes=error_notes,
            )
            await error_view.initialize(interaction)

        except Exception:
            error_message = "An unexpected error occurred while processing your request."
            error_notes = [{"name": "Prompt", "value": prompt}]
            error_view = InfoEmbedView(
                message=interaction.message,
                user=embed_user,
                title="Prompt error!",
                description=error_message,
                is_error=True,
                image_data=None,
                notes=error_notes,
            )
            await error_view.initialize(interaction)

    @bot.tree.command()
    @app_commands.describe(prompt="Description of the personality of the AI")
    @count_command
    async def behavior(
        interaction: discord.Interaction,
        prompt: str,
        timeout: float | None = None,
    ) -> None:
        """Submit a behavior change prompt for future AI responses.

        Args:
            interaction: The Discord interaction.
            prompt: The behavior change prompt.
            timeout: The timeout for the request in seconds.
        """
        assert interaction.channel_id is not None, "Command must be used in a channel"
        channel_id = interaction.channel_id
        await interaction.response.defer()

        if timeout is None:
            timeout = DEFAULT_PROMPT_TIMEOUT

        embed_user = create_embed_user(interaction)

        try:
            async with asyncio.timeout(timeout):
                await bot.repo.create_channel(channel_id)
                await bot.repo.add_message(
                    channel_id, "Anthropic", "behavior", False, prompt
                )

                # Refresh context after adding message (result not used, but triggers DB update)
                await bot.repo.get_visible_messages(
                    channel_id, "All Models"
                )

                display_prompt, full_prompt_url = await handle_text_overflow(
                    bot, "prompt", prompt, channel_id
                )

                processing_message = (
                    "Updating behavior... (This may take up to 30 seconds)"
                )
                processing_notes = [{"name": "Prompt", "value": display_prompt}]
                processing_view = InfoEmbedView(
                    message=interaction.message,
                    user=embed_user,
                    title="Behavior Update",
                    description=processing_message,
                    is_error=False,
                    notes=processing_notes,
                    full_prompt_url=full_prompt_url,
                )
                await processing_view.initialize(interaction)

                # Behavior prompts just acknowledge the new setting, no API call needed
                response = (
                    f"I will use the following system prompt for future interactions:"
                    f"\n\n{prompt}"
                )
                await bot.repo.add_message(
                    channel_id, "Anthropic", "assistant", False, response
                )

                display_response, full_response_url = await handle_text_overflow(
                    bot, "response", response, channel_id
                )

                success_notes = [
                    {"name": "Behavior Instructions", "value": display_prompt},
                    {"name": "AI Acknowledgment", "value": display_response},
                ]
                success_view = InfoEmbedView(
                    message=interaction.message,
                    user=embed_user,
                    title="Behavior Updated",
                    is_error=False,
                    notes=success_notes,
                    full_response_url=full_response_url,
                    full_prompt_url=full_prompt_url,
                )
                await success_view.initialize(interaction)

        except TimeoutError:
            error_message = (
                f"The request timed out after {timeout} seconds. Please try again."
            )
            error_notes = [{"name": "Prompt", "value": prompt}]
            error_view = InfoEmbedView(
                message=interaction.message,
                user=embed_user,
                title="Behavior error!",
                description=error_message,
                is_error=True,
                image_data=None,
                notes=error_notes,
            )
            await error_view.initialize(interaction)

        except Exception:
            error_message = "An unexpected error occurred while processing your request."
            error_notes = [{"name": "Prompt", "value": prompt}]
            error_view = InfoEmbedView(
                message=interaction.message,
                user=embed_user,
                title="Behavior error!",
                description=error_message,
                is_error=True,
                image_data=None,
                notes=error_notes,
            )
            await error_view.initialize(interaction)

    @bot.tree.command()
    @app_commands.describe()
    @count_command
    async def clear(
        interaction: discord.Interaction,
        timeout: float | None = None,
    ) -> None:
        """Clear the bot's memory of the current channel.

        Args:
            interaction: The Discord interaction.
            timeout: The timeout for the operation in seconds.
        """
        assert interaction.channel_id is not None, "Command must be used in a channel"
        channel_id = interaction.channel_id
        await interaction.response.defer()

        if timeout is None:
            timeout = DEFAULT_CLEAR_TIMEOUT

        embed_user = create_embed_user(interaction)

        async def on_clear_selection(
            clear_interaction: discord.Interaction,
            user: dict,
            confirmed: bool,
        ) -> None:
            if confirmed:
                await bot.repo.deactivate_all_messages(channel_id)
                success_message = (
                    "The bot's memory for this channel has been cleared. "
                    "All prior messages and images have been forgotten."
                )
                success_view = InfoEmbedView(
                    message=interaction.message,
                    user=embed_user,
                    title="History Cleared",
                    description=success_message,
                    is_error=False,
                    image_data=None,
                )
                await success_view.initialize(clear_interaction)
            else:
                cancel_message = "History clear operation was cancelled."
                cancel_view = InfoEmbedView(
                    message=interaction.message,
                    user=embed_user,
                    title="Operation Cancelled",
                    description=cancel_message,
                    is_error=False,
                    image_data=None,
                )
                await cancel_view.initialize(clear_interaction)

        confirmation_view = ClearHistoryConfirmationView(
            interaction=interaction,
            user=embed_user,
            on_select=on_clear_selection,
        )
        await confirmation_view.initialize(interaction)
