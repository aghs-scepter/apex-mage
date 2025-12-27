"""Chat-related Discord slash commands."""

import asyncio
import base64
import io
import json
import sqlite3
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
    PresetSelectView,
    SummarizePreviewView,
)
from src.core.auto_summarization import (
    SUMMARIZATION_CONFIRMATION,
    THRESHOLD_WARNING,
    convert_context_to_chat_messages,
    get_auto_summarization_manager,
    perform_summarization,
)
from src.core.chart_utils import UserStats, generate_usage_chart
from src.core.conversation import convert_context_to_messages
from src.core.haiku import SummarizationError, haiku_summarize_conversation
from src.core.image_utils import compress_image
from src.core.logging import get_logger
from src.core.token_counting import check_token_threshold, count_tokens

if TYPE_CHECKING:
    from src.clients.discord.bot import DiscordBot

logger = get_logger(__name__)

# Timeout constants
DEFAULT_PROMPT_TIMEOUT = 240.0
DEFAULT_CLEAR_TIMEOUT = 60.0


class SetBehaviorGroup(app_commands.Group):
    """Command group for setting AI behavior."""

    def __init__(self, bot: "DiscordBot") -> None:
        """Initialize the set_behavior command group.

        Args:
            bot: The Discord bot instance.
        """
        super().__init__(name="set_behavior", description="Set AI behavior")
        self.bot = bot

    @app_commands.command(name="custom")
    @app_commands.describe(prompt="Description of the personality of the AI")
    async def custom(
        self,
        interaction: discord.Interaction,
        prompt: str,
        timeout: float | None = None,
    ) -> None:
        """Set a custom behavior prompt for the AI.

        Args:
            interaction: The Discord interaction.
            prompt: The custom behavior prompt.
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
                await self.bot.repo.create_channel(channel_id)
                await self.bot.repo.add_message(
                    channel_id, "Anthropic", "behavior", False, prompt
                )

                # Refresh context after adding message
                await self.bot.repo.get_visible_messages(channel_id, "All Models")

                display_prompt, full_prompt_url = await handle_text_overflow(
                    self.bot, "prompt", prompt, channel_id
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
                await self.bot.repo.add_message(
                    channel_id, "Anthropic", "assistant", False, response
                )

                display_response, full_response_url = await handle_text_overflow(
                    self.bot, "response", response, channel_id
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

        except Exception as e:
            logger.exception("unexpected_error", error=str(e))
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

    @app_commands.command(name="preset")
    async def preset(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """Select a saved behavior preset from a dropdown menu."""
        assert interaction.guild_id is not None, "Command must be used in a guild"
        assert interaction.channel_id is not None, "Command must be used in a channel"

        await interaction.response.defer()

        embed_user = create_embed_user(interaction)
        channel_id = interaction.channel_id
        guild_id = str(interaction.guild_id)

        # Fetch presets for this guild
        presets = await self.bot.repo.list_presets(guild_id)

        # If no presets exist, show a friendly message
        if not presets:
            info_view = InfoEmbedView(
                message=interaction.message,
                user=embed_user,
                title="No Presets Available",
                description=(
                    "No behavior presets found for this server.\n\n"
                    "Create one with `/behavior_preset create`"
                ),
                is_error=False,
            )
            await info_view.initialize(interaction)
            return

        async def on_preset_selected(
            select_interaction: discord.Interaction,
            preset_name: str | None,
            _prompt_text: str | None,
        ) -> None:
            """Handle preset selection callback."""
            try:
                await self.bot.repo.create_channel(channel_id)

                if preset_name is None:
                    # Default selected - clear behavior by setting empty prompt
                    # This effectively removes the system prompt
                    await self.bot.repo.add_message(
                        channel_id, "Anthropic", "behavior", False, ""
                    )
                    display_name = "Default"
                    display_prompt = "(No system prompt - using default AI behavior)"
                else:
                    # Get the preset's prompt text
                    preset = await self.bot.repo.get_preset(guild_id, preset_name)
                    if preset is None:
                        error_view = InfoEmbedView(
                            message=select_interaction.message,
                            user=embed_user,
                            title="Error",
                            description=f"Preset `{preset_name}` not found.",
                            is_error=True,
                        )
                        await error_view.initialize(select_interaction)
                        return

                    prompt_text = preset["prompt_text"]
                    await self.bot.repo.add_message(
                        channel_id, "Anthropic", "behavior", False, prompt_text
                    )
                    display_name = preset_name
                    display_prompt = prompt_text

                # Refresh context
                await self.bot.repo.get_visible_messages(channel_id, "All Models")

                # Handle text overflow for display
                display_prompt_truncated, full_prompt_url = await handle_text_overflow(
                    self.bot, "prompt", display_prompt, channel_id
                )

                success_notes = [
                    {"name": "Preset", "value": display_name},
                    {"name": "Behavior Instructions", "value": display_prompt_truncated},
                ]
                success_view = InfoEmbedView(
                    message=select_interaction.message,
                    user=embed_user,
                    title="Behavior Updated",
                    is_error=False,
                    notes=success_notes,
                    full_prompt_url=full_prompt_url,
                )
                await success_view.initialize(select_interaction)

            except Exception as e:
                logger.exception("command_error", error=str(e))
                error_view = InfoEmbedView(
                    message=select_interaction.message,
                    user=embed_user,
                    title="Error",
                    description="An error occurred while applying the preset.",
                    is_error=True,
                )
                await error_view.initialize(select_interaction)

        # Show the preset selection view
        preset_view = PresetSelectView(
            presets=presets,
            user=embed_user,
            channel_id=channel_id,
            on_select=on_preset_selected,
        )
        await preset_view.initialize(interaction)


class BehaviorPresetGroup(app_commands.Group):
    """Command group for managing behavior presets."""

    # Hard limit of presets per guild
    MAX_PRESETS_PER_GUILD = 15

    def __init__(self, bot: "DiscordBot") -> None:
        """Initialize the behavior_preset command group.

        Args:
            bot: The Discord bot instance.
        """
        super().__init__(name="behavior_preset", description="Manage behavior presets")
        self.bot = bot

    @app_commands.command(name="create", description="Create a new behavior preset")
    @app_commands.describe(
        name="Name for the preset",
        description="Short description of this preset",
        prompt="The behavior prompt text",
    )
    async def create(
        self,
        interaction: discord.Interaction,
        name: str,
        description: str,
        prompt: str,
    ) -> None:
        """Create a new behavior preset for this server.

        Args:
            interaction: The Discord interaction.
            name: Name for the preset.
            description: Short description of this preset.
            prompt: The behavior prompt text.
        """
        # Ensure command is used in a guild
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        embed_user = create_embed_user(interaction)
        guild_id = str(interaction.guild_id)

        try:
            # Check preset limit
            preset_count = await self.bot.repo.count_presets(guild_id)
            if preset_count >= self.MAX_PRESETS_PER_GUILD:
                error_view = InfoEmbedView(
                    message=interaction.message,
                    user=embed_user,
                    title="Preset Limit Reached",
                    description=(
                        f"This server has reached the maximum of "
                        f"{self.MAX_PRESETS_PER_GUILD} presets.\n\n"
                        f"Delete an existing preset with `/behavior_preset delete` "
                        f"before creating a new one."
                    ),
                    is_error=True,
                )
                await error_view.initialize(interaction)
                return

            # Create the preset
            await self.bot.repo.create_preset(
                guild_id=guild_id,
                name=name,
                description=description,
                prompt_text=prompt,
                created_by=interaction.user.name,
            )

            # Success message
            display_prompt, full_prompt_url = await handle_text_overflow(
                self.bot, "prompt", prompt, interaction.channel_id or 0
            )

            success_notes = [
                {"name": "Name", "value": name},
                {"name": "Description", "value": description},
                {"name": "Prompt", "value": display_prompt},
            ]
            success_view = InfoEmbedView(
                message=interaction.message,
                user=embed_user,
                title="Preset Created",
                description=f"Successfully created behavior preset `{name}`.",
                is_error=False,
                notes=success_notes,
                full_prompt_url=full_prompt_url,
            )
            await success_view.initialize(interaction)

        except sqlite3.IntegrityError:
            # Duplicate name error
            error_view = InfoEmbedView(
                message=interaction.message,
                user=embed_user,
                title="Duplicate Preset Name",
                description=(
                    f"A preset named `{name}` already exists in this server.\n\n"
                    f"Please choose a different name."
                ),
                is_error=True,
            )
            await error_view.initialize(interaction)

        except Exception as e:
            logger.exception("command_error", error=str(e))
            error_view = InfoEmbedView(
                message=interaction.message,
                user=embed_user,
                title="Error",
                description="An unexpected error occurred while creating the preset.",
                is_error=True,
            )
            await error_view.initialize(interaction)

    @app_commands.command(name="edit", description="Edit an existing behavior preset")
    @app_commands.describe(
        name="Name of the preset to edit",
        description="New description (optional)",
        prompt="New prompt text (optional)",
    )
    async def edit(
        self,
        interaction: discord.Interaction,
        name: str,
        description: str | None = None,
        prompt: str | None = None,
    ) -> None:
        """Edit an existing behavior preset.

        Only the bot owner (aghs), preset creator, or server admins can edit.

        Args:
            interaction: The Discord interaction.
            name: Name of the preset to edit.
            description: New description (optional).
            prompt: New prompt text (optional).
        """
        # Check guild context
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        guild_id = str(interaction.guild_id)

        # Fetch preset to verify it exists and get created_by
        preset = await self.bot.repo.get_preset(guild_id, name)

        if preset is None:
            await interaction.response.send_message(
                f"Preset `{name}` not found.",
                ephemeral=True,
            )
            return

        # Permission check: bot owner OR creator OR server admin
        is_bot_owner = interaction.user.name == "aghs"
        is_creator = interaction.user.name == preset["created_by"]
        is_admin = (
            hasattr(interaction.user, "guild_permissions")
            and interaction.user.guild_permissions.administrator
        )

        if not (is_bot_owner or is_creator or is_admin):
            await interaction.response.send_message(
                "You don't have permission to edit this preset. "
                "Only the bot owner, preset creator, or server admins can edit presets.",
                ephemeral=True,
            )
            return

        # Check if at least one field is provided
        if description is None and prompt is None:
            await interaction.response.send_message(
                "Please provide at least one field to update (description or prompt).",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        # Update the preset
        await self.bot.repo.update_preset(guild_id, name, description, prompt)

        embed_user = create_embed_user(interaction)

        # Build update notes
        update_notes = [{"name": "Preset", "value": name}]
        if description is not None:
            update_notes.append({"name": "New Description", "value": description})
        if prompt is not None:
            display_prompt, _ = await handle_text_overflow(
                self.bot, "prompt", prompt, interaction.channel_id or 0
            )
            update_notes.append({"name": "New Prompt", "value": display_prompt})

        info_view = InfoEmbedView(
            message=interaction.message,
            user=embed_user,
            title="Preset Updated",
            description=f"Behavior preset `{name}` has been updated.",
            is_error=False,
            notes=update_notes,
        )
        await info_view.initialize(interaction)

    @app_commands.command(name="list", description="List all behavior presets for this server")
    async def list_presets(self, interaction: discord.Interaction) -> None:
        """List all behavior presets for the current guild.

        Args:
            interaction: The Discord interaction.
        """
        # Check guild context
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        guild_id = str(interaction.guild_id)
        embed_user = create_embed_user(interaction)

        # Fetch presets for this guild
        presets = await self.bot.repo.list_presets(guild_id)

        # If no presets exist, show a friendly message
        if not presets:
            info_view = InfoEmbedView(
                message=interaction.message,
                user=embed_user,
                title="Behavior Presets",
                description=(
                    "No behavior presets found for this server.\n\n"
                    "Create one with `/behavior_preset create`"
                ),
                is_error=False,
            )
            await info_view.initialize(interaction)
            return

        # Build embed with preset list
        embed = discord.Embed(title="Behavior Presets", color=0x3498DB)

        for preset in presets:
            # Truncate description to ~50 chars for display
            desc = preset["description"]
            if len(desc) > 50:
                desc = desc[:50] + "..."
            embed.add_field(
                name=preset["name"],
                value=f"{desc}\n*Created by: {preset['created_by']}*",
                inline=False,
            )

        # Show count
        count = len(presets)
        embed.set_footer(text=f"Showing {count}/15 presets")

        await interaction.followup.send(embed=embed)

    async def _preset_name_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete handler for preset names.

        Args:
            interaction: The Discord interaction.
            current: The current input value to filter by.

        Returns:
            List of matching preset name choices.
        """
        if interaction.guild_id is None:
            return []

        guild_id = str(interaction.guild_id)
        presets = await self.bot.repo.list_presets(guild_id)

        # Filter presets by current input (case-insensitive)
        current_lower = current.lower()
        matching = [
            app_commands.Choice(name=p["name"], value=p["name"])
            for p in presets
            if current_lower in p["name"].lower()
        ]

        # Discord limits autocomplete to 25 choices
        return matching[:25]

    @app_commands.command(name="delete", description="Delete a behavior preset")
    @app_commands.describe(name="Name of the preset to delete")
    async def delete(
        self,
        interaction: discord.Interaction,
        name: str,
    ) -> None:
        """Delete a behavior preset.

        Only the bot owner (aghs), preset creator, or server admins can delete.

        Args:
            interaction: The Discord interaction.
            name: Name of the preset to delete.
        """
        # Check guild context
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        guild_id = str(interaction.guild_id)

        # Fetch preset to verify it exists and get created_by
        preset = await self.bot.repo.get_preset(guild_id, name)

        if preset is None:
            await interaction.response.send_message(
                f"Preset '{name}' not found.",
                ephemeral=True,
            )
            return

        # Permission check: bot owner OR creator OR server admin
        is_bot_owner = interaction.user.name == "aghs"
        is_creator = interaction.user.name == preset["created_by"]
        is_admin = (
            hasattr(interaction.user, "guild_permissions")
            and interaction.user.guild_permissions.administrator
        )

        if not (is_bot_owner or is_creator or is_admin):
            await interaction.response.send_message(
                "You don't have permission to delete this preset. "
                "Only the bot owner, preset creator, or server admins can delete presets.",
                ephemeral=True,
            )
            return

        # Delete the preset
        await self.bot.repo.delete_preset(guild_id, name)

        await interaction.response.send_message(
            f"Preset '{name}' has been deleted.",
        )

    @delete.autocomplete("name")
    async def delete_name_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete for the delete command's name parameter."""
        return await self._preset_name_autocomplete(interaction, current)

    @edit.autocomplete("name")
    async def edit_name_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete for the edit command's name parameter."""
        return await self._preset_name_autocomplete(interaction, current)

    @app_commands.command(name="view", description="View details of a behavior preset")
    @app_commands.describe(name="Name of the preset to view")
    async def view(
        self,
        interaction: discord.Interaction,
        name: str,
    ) -> None:
        """View the full details of a behavior preset.

        Anyone can view any preset in the server.

        Args:
            interaction: The Discord interaction.
            name: Name of the preset to view.
        """
        # Check guild context
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        guild_id = str(interaction.guild_id)

        # Fetch the preset
        preset = await self.bot.repo.get_preset(guild_id, name)

        if preset is None:
            await interaction.response.send_message(
                f"Preset `{name}` not found.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        embed_user = create_embed_user(interaction)

        # Build the embed with preset details
        embed = discord.Embed(
            title=f"Preset: {preset['name']}",
            color=0x3498DB,
        )

        # Add description field
        embed.add_field(
            name="Description",
            value=preset["description"],
            inline=False,
        )

        # Handle long prompt text - truncate if over 1000 characters
        prompt_text = preset["prompt_text"]
        full_prompt_url = None
        if len(prompt_text) > 1000:
            # Upload full prompt to GCS and truncate display
            try:
                display_prompt, full_prompt_url = await handle_text_overflow(
                    self.bot, "prompt", prompt_text, interaction.channel_id or 0
                )
            except Exception as e:
                logger.warning("text_overflow_upload_failed", error=str(e))
                # If upload fails, just truncate
                display_prompt = prompt_text[:1000] + "...\n*(truncated)*"
        else:
            display_prompt = prompt_text

        embed.add_field(
            name="Prompt",
            value=display_prompt,
            inline=False,
        )

        # Add metadata fields
        embed.add_field(
            name="Created By",
            value=preset["created_by"],
            inline=True,
        )
        embed.add_field(
            name="Created At",
            value=preset["created_at"],
            inline=True,
        )

        # Set footer with user info
        avatar = embed_user.get("pfp")
        if avatar is not None:
            embed.set_footer(
                text=f"Requested by {embed_user['name']}",
                icon_url=avatar,
            )
        else:
            embed.set_footer(text=f"Requested by {embed_user['name']}")

        # If we have a full prompt URL, add a button to view it
        if full_prompt_url:
            button_view = discord.ui.View()
            button_view.add_item(
                discord.ui.Button(
                    label="View Full Prompt",
                    url=full_prompt_url,
                    style=discord.ButtonStyle.link,
                )
            )
            await interaction.followup.send(embed=embed, view=button_view)
        else:
            await interaction.followup.send(embed=embed)

    @view.autocomplete("name")
    async def view_name_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete for the view command's name parameter."""
        return await self._preset_name_autocomplete(interaction, current)


def register_chat_commands(bot: "DiscordBot") -> None:
    """Register chat-related commands with the bot.

    Args:
        bot: The Discord bot instance.
    """

    @bot.tree.command()  # type: ignore[arg-type]
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
    `/set_behavior custom` - Set a custom behavior prompt for the AI.
    `/set_behavior preset` - Select a saved behavior preset.
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

    @bot.tree.command()  # type: ignore[arg-type]
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
                            if images and upload
                            else None
                        ),
                        notes=processing_notes,
                        full_prompt_url=full_prompt_url,
                    )
                    await processing_view.initialize(interaction)

                    display_prompt, full_prompt_url = await handle_text_overflow(
                        bot, "prompt", prompt, channel_id
                    )

                    # Get auto-summarization manager
                    summarization_manager = get_auto_summarization_manager()
                    summarization_performed = False
                    response_prefix = ""

                    # Check if auto-summarization is pending for this channel
                    if summarization_manager.should_summarize(channel_id):
                        # Perform auto-summarization before processing
                        try:
                            # Convert context to format for summarization
                            messages_for_summary = convert_context_to_chat_messages(
                                context
                            )

                            if messages_for_summary:
                                # Perform summarization
                                summary = await perform_summarization(
                                    messages_for_summary
                                )

                                # Clear existing messages and replace with summary
                                await bot.repo.clear_messages(channel_id, "All Models")
                                await bot.repo.create_channel(channel_id)

                                # Add the summary as an assistant message
                                await bot.repo.add_message(
                                    channel_id,
                                    "Anthropic",
                                    "assistant",
                                    False,
                                    summary,
                                )

                                # Re-add the current user prompt
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
                                        channel_id,
                                        "Anthropic",
                                        "prompt",
                                        False,
                                        prompt,
                                    )

                                # Refresh context with summarized version
                                context = await bot.repo.get_visible_messages(
                                    channel_id, "All Models"
                                )

                                summarization_performed = True
                                response_prefix = SUMMARIZATION_CONFIRMATION + "\n\n"

                            # Clear the pending flag
                            summarization_manager.clear_pending(channel_id)

                        except Exception as e:
                            logger.warning("auto_summarization_failed", error=str(e))
                            # If summarization fails, continue without it
                            # Clear the flag to avoid repeated failures
                            summarization_manager.clear_pending(channel_id)

                    # Convert context to ChatMessages and extract system prompt
                    chat_messages, system_prompt = convert_context_to_messages(context)
                    chat_response = await bot.ai_provider.chat(
                        chat_messages, system_prompt=system_prompt
                    )
                    response = chat_response.content

                    # Check token threshold after processing to set pending for next msg
                    # Only check if we didn't just perform summarization
                    if not summarization_performed:
                        _, threshold_exceeded = check_token_threshold(
                            system_prompt=system_prompt or "",
                            messages=[
                                {"role": m.role, "content": m.content}
                                for m in chat_messages
                            ],
                            current_prompt=prompt,
                        )

                        if threshold_exceeded:
                            # Set pending for next message and add warning to response
                            summarization_manager.set_pending(channel_id)
                            response = response + "\n\n" + THRESHOLD_WARNING

                    # Add confirmation prefix if summarization was performed
                    if response_prefix:
                        response = response_prefix + response

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
                            if images and upload
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

        except Exception as e:
            logger.exception("unexpected_error", error=str(e))
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

    # Register the set_behavior command group
    bot.tree.add_command(SetBehaviorGroup(bot))

    # Register the behavior_preset command group
    bot.tree.add_command(BehaviorPresetGroup(bot))

    @bot.tree.command()  # type: ignore[arg-type]
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
            user: dict[str, Any] | None,
            confirmed: bool,
        ) -> None:
            if confirmed:
                await bot.repo.clear_messages(channel_id, "All Models")
                # Clear any pending auto-summarization state
                summarization_manager = get_auto_summarization_manager()
                summarization_manager.clear_pending(channel_id)
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

    @bot.tree.command(
        description="Ban a user from using the bot. Only aghs can use this command."
    )
    @app_commands.describe(
        user="Discord user to ban",
        reason="Reason for the ban",
    )
    async def ban_user(
        interaction: discord.Interaction,
        user: discord.User,
        reason: str,
    ) -> None:
        """Ban a user from using the bot. Only aghs can use this command.

        Args:
            interaction: The Discord interaction.
            user: The Discord user to ban.
            reason: The reason for the ban.
        """
        # Check if invoker is the bot owner
        if interaction.user.name != "aghs":
            await interaction.response.send_message(
                "Only aghs can ban users.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        embed_user = create_embed_user(interaction)

        try:
            await bot.repo.add_ban(user.id, user.name, reason, interaction.user.name)

            info_view = InfoEmbedView(
                message=interaction.message,
                user=embed_user,
                title="User Banned",
                description=f"User {user.name} (ID: {user.id}) has been banned. Reason: {reason}",
                is_error=False,
            )
            await info_view.initialize(interaction)

        except sqlite3.IntegrityError:
            # User is already banned
            info_view = InfoEmbedView(
                message=interaction.message,
                user=embed_user,
                title="Ban User",
                description=f"User {user.name} is already banned.",
                is_error=False,
            )
            await info_view.initialize(interaction)

    @bot.tree.command(
        description="Unban a user from the bot. Only aghs can use this command."
    )
    @app_commands.describe(user="Discord user to unban")
    async def unban_user(interaction: discord.Interaction, user: discord.User) -> None:
        """Unban a user from the bot. Only aghs can use this command.

        Args:
            interaction: The Discord interaction.
            user: The Discord user to unban.
        """
        # Check if invoker is the bot owner
        if interaction.user.name != "aghs":
            await interaction.response.send_message(
                "Only aghs can unban users.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        embed_user = create_embed_user(interaction)

        # Check if user is actually banned
        is_banned = await bot.repo.is_user_banned(user.id)

        if not is_banned:
            info_view = InfoEmbedView(
                message=interaction.message,
                user=embed_user,
                title="Unban User",
                description=f"User {user.name} is not currently banned.",
                is_error=False,
            )
            await info_view.initialize(interaction)
            return

        # Remove the ban
        await bot.repo.remove_ban(user.id, interaction.user.name)

        info_view = InfoEmbedView(
            message=interaction.message,
            user=embed_user,
            title="User Unbanned",
            description=f"User {user.name} has been unbanned.",
            is_error=False,
        )
        await info_view.initialize(interaction)

    @bot.tree.command(
        description="Add a user to the whitelist. Only aghs can use this command."
    )
    @app_commands.describe(
        user="Discord user to add to whitelist",
        notes="Optional notes about this user",
    )
    async def whitelist_add(
        interaction: discord.Interaction,
        user: discord.User,
        notes: str | None = None,
    ) -> None:
        """Add a user to the whitelist. Only aghs can use this command.

        Args:
            interaction: The Discord interaction.
            user: The Discord user to whitelist.
            notes: Optional notes about this user.
        """
        # Check if invoker is the bot owner
        if interaction.user.name != "aghs":
            await interaction.response.send_message(
                "Only aghs can add users to the whitelist.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        embed_user = create_embed_user(interaction)

        # Check if user is already whitelisted
        is_whitelisted = await bot.repo.is_user_whitelisted(user.id)

        if is_whitelisted:
            info_view = InfoEmbedView(
                message=interaction.message,
                user=embed_user,
                title="Whitelist",
                description=f"User {user.name} is already whitelisted.",
                is_error=False,
            )
            await info_view.initialize(interaction)
            return

        # Add to whitelist
        await bot.repo.add_to_whitelist(
            user.id, user.name, interaction.user.name, notes
        )

        notes_display = [{"name": "User", "value": f"{user.name} ({user.id})"}]
        if notes:
            notes_display.append({"name": "Notes", "value": notes})

        info_view = InfoEmbedView(
            message=interaction.message,
            user=embed_user,
            title="User Whitelisted",
            description=f"User {user.name} has been added to the whitelist.",
            is_error=False,
            notes=notes_display,
        )
        await info_view.initialize(interaction)

    @bot.tree.command(
        description="Remove a user from the whitelist. Only aghs can use this command."
    )
    @app_commands.describe(user="Discord user to remove from whitelist")
    async def whitelist_remove(
        interaction: discord.Interaction,
        user: discord.User,
    ) -> None:
        """Remove a user from the whitelist. Only aghs can use this command.

        Args:
            interaction: The Discord interaction.
            user: The Discord user to remove from whitelist.
        """
        # Check if invoker is the bot owner
        if interaction.user.name != "aghs":
            await interaction.response.send_message(
                "Only aghs can remove users from the whitelist.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        embed_user = create_embed_user(interaction)

        # Check if user is actually whitelisted
        is_whitelisted = await bot.repo.is_user_whitelisted(user.id)

        if not is_whitelisted:
            info_view = InfoEmbedView(
                message=interaction.message,
                user=embed_user,
                title="Whitelist",
                description=f"User {user.name} is not currently whitelisted.",
                is_error=False,
            )
            await info_view.initialize(interaction)
            return

        # Remove from whitelist
        await bot.repo.remove_from_whitelist(user.id)

        info_view = InfoEmbedView(
            message=interaction.message,
            user=embed_user,
            title="User Removed from Whitelist",
            description=f"User {user.name} has been removed from the whitelist.",
            is_error=False,
        )
        await info_view.initialize(interaction)

    @bot.tree.command(
        description="List all whitelisted users. Only aghs can use this command."
    )
    async def whitelist_list(interaction: discord.Interaction) -> None:
        """List all whitelisted users. Only aghs can use this command.

        Args:
            interaction: The Discord interaction.
        """
        # Check if invoker is the bot owner
        if interaction.user.name != "aghs":
            await interaction.response.send_message(
                "Only aghs can view the whitelist.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        embed_user = create_embed_user(interaction)

        # Get all whitelisted users
        whitelist = await bot.repo.list_whitelist()

        if not whitelist:
            info_view = InfoEmbedView(
                message=interaction.message,
                user=embed_user,
                title="Whitelist",
                description="No users are currently whitelisted.",
                is_error=False,
            )
            await info_view.initialize(interaction)
            return

        # Build embed with whitelist
        embed = discord.Embed(title="Whitelisted Users", color=0x3498DB)

        for entry in whitelist:
            # Format each entry
            notes = entry.get("notes") or "No notes"
            added_at = entry.get("added_at", "Unknown")
            embed.add_field(
                name=f"{entry['username']} ({entry['user_id']})",
                value=f"Added by: {entry['added_by']}\nAdded: {added_at}\nNotes: {notes}",
                inline=False,
            )

        # Show count in footer
        embed.set_footer(text=f"Total: {len(whitelist)} user(s)")

        await interaction.followup.send(embed=embed)

    @bot.tree.command(  # type: ignore[arg-type]
        description="Check your access status (available to everyone)."
    )
    async def my_status(interaction: discord.Interaction) -> None:
        """Check your own access status (whitelisted, not whitelisted, or banned).

        This command is available to everyone and bypasses the whitelist check.

        Args:
            interaction: The Discord interaction.
        """
        user_id = interaction.user.id

        # Check ban status first (ban takes precedence)
        is_banned = await bot.repo.is_user_banned(user_id)

        if is_banned:
            reason = await bot.repo.get_ban_reason(user_id)
            reason_text = reason if reason else "No reason provided"
            await interaction.response.send_message(
                f"Banned: {reason_text}",
                ephemeral=True,
            )
            return

        # Check whitelist status
        is_whitelisted = await bot.repo.is_user_whitelisted(user_id)

        if is_whitelisted:
            await interaction.response.send_message(
                "Whitelisted",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "Not whitelisted. Contact @aghs for access.",
                ephemeral=True,
            )

    @bot.tree.command(  # type: ignore[arg-type]
        description="Summarize the current conversation context to reduce token usage."
    )
    @app_commands.describe(
        guidance="Optional focus for the summary (e.g., 'the authentication bug')"
    )
    @count_command
    async def summarize(
        interaction: discord.Interaction,
        guidance: str | None = None,
    ) -> None:
        """Summarize the conversation context with a preview and confirmation.

        Args:
            interaction: The Discord interaction.
            guidance: Optional focus area for the summary.
        """
        assert interaction.channel_id is not None, "Command must be used in a channel"
        channel_id = interaction.channel_id
        await interaction.response.defer()

        embed_user = create_embed_user(interaction)

        try:
            # Get current context
            await bot.repo.create_channel(channel_id)
            context = await bot.repo.get_visible_messages(channel_id, "All Models")

            # Filter to get only prompt and assistant messages for summarization
            messages_to_summarize = []
            for msg in context:
                msg_type = msg.get("message_type", "")
                msg_data = msg.get("message_data", "")
                if msg_type in ("prompt", "assistant") and msg_data:
                    role = "user" if msg_type == "prompt" else "assistant"
                    messages_to_summarize.append({"role": role, "content": msg_data})

            # Check if there's anything to summarize
            if len(messages_to_summarize) < 2:
                info_view = InfoEmbedView(
                    message=interaction.message,
                    user=embed_user,
                    title="Nothing to Summarize",
                    description=(
                        "There's not enough conversation history to summarize.\n\n"
                        "Have a conversation with the bot first, then use /summarize."
                    ),
                    is_error=False,
                )
                await info_view.initialize(interaction)
                return

            # Count original tokens
            original_text = "\n".join(
                f"{m['role']}: {m['content']}" for m in messages_to_summarize
            )
            original_tokens = count_tokens(original_text)

            # Show processing message
            processing_view = InfoEmbedView(
                message=interaction.message,
                user=embed_user,
                title="Generating Summary",
                description="Summarizing your conversation... (This may take a few seconds)",
                is_error=False,
            )
            await processing_view.initialize(interaction)

            # Generate summary using Haiku
            summary_text = await haiku_summarize_conversation(
                messages_to_summarize, guidance=guidance
            )

            # Count summary tokens
            summary_tokens = count_tokens(summary_text)

            # Define callbacks for the preview view
            async def on_confirm(confirm_interaction: discord.Interaction) -> None:
                """Apply the summarization."""
                try:
                    # Clear existing messages and add summary as new context
                    await bot.repo.clear_messages(channel_id, "All Models")

                    # Add the summary as a new message pair
                    await bot.repo.add_message(
                        channel_id,
                        "Anthropic",
                        "prompt",
                        False,
                        "[Previous conversation summarized]",
                    )
                    await bot.repo.add_message(
                        channel_id,
                        "Anthropic",
                        "assistant",
                        False,
                        summary_text,
                    )

                    # Show confirmation
                    success_view = InfoEmbedView(
                        message=confirm_interaction.message,
                        user=embed_user,
                        title="Context Summarized",
                        description="Context has been summarized.",
                        is_error=False,
                        notes=[
                            {
                                "name": "Token Reduction",
                                "value": f"~{original_tokens} -> ~{summary_tokens} tokens",
                            }
                        ],
                    )
                    await success_view.initialize(confirm_interaction)

                except Exception as e:
                    logger.exception("command_error", error=str(e))
                    error_view = InfoEmbedView(
                        message=confirm_interaction.message,
                        user=embed_user,
                        title="Summarization Error",
                        description="Failed to apply summarization. Please try again.",
                        is_error=True,
                    )
                    await error_view.initialize(confirm_interaction)

            async def on_cancel(cancel_interaction: discord.Interaction) -> None:
                """Cancel summarization - no action needed, view handles UI."""
                pass

            # Show preview with confirm/cancel buttons
            preview_view = SummarizePreviewView(
                user=embed_user,
                summary_text=summary_text,
                original_tokens=original_tokens,
                summary_tokens=summary_tokens,
                on_confirm=on_confirm,
                on_cancel=on_cancel,
            )
            await preview_view.initialize(interaction)

        except SummarizationError as e:
            error_view = InfoEmbedView(
                message=interaction.message,
                user=embed_user,
                title="Summarization Error",
                description=str(e),
                is_error=True,
            )
            await error_view.initialize(interaction)

        except Exception as e:
            logger.exception("command_error", error=str(e))
            error_view = InfoEmbedView(
                message=interaction.message,
                user=embed_user,
                title="Summarization Error",
                description="An unexpected error occurred while summarizing. Please try again.",
                is_error=True,
            )
            await error_view.initialize(interaction)

    @bot.tree.command(  # type: ignore[arg-type]
        description="Show usage statistics as a chart."
    )
    @app_commands.describe(
        server_only="If True, show stats for this server only. If False, show all servers."
    )
    @count_command
    async def show_usage(
        interaction: discord.Interaction,
        server_only: bool = True,
    ) -> None:
        """Display usage statistics as a chart.

        Shows a stacked bar chart of the top 5 users by usage score.
        Image commands are weighted 5x compared to text commands.

        Args:
            interaction: The Discord interaction.
            server_only: If True, filter stats by current guild. If False, show all.
        """
        await interaction.response.defer()

        embed_user = create_embed_user(interaction)

        try:
            # Get guild_id for filtering if server_only is True
            guild_id = interaction.guild_id if server_only else None

            # Get top users by usage
            raw_stats = await bot.repo.get_top_users_by_usage(guild_id, limit=5)
            # Cast to UserStats for type safety
            stats: list[UserStats] = [
                UserStats(
                    user_id=s["user_id"],
                    username=s["username"],
                    image_count=s["image_count"],
                    text_count=s["text_count"],
                    total_score=s["total_score"],
                )
                for s in raw_stats
            ]

            # Determine chart title
            if server_only and interaction.guild:
                title = f"Top Users - {interaction.guild.name}"
            elif server_only:
                title = "Top Users - This Server"
            else:
                title = "Top Users - All Servers"

            # Generate the chart
            image_bytes = await generate_usage_chart(stats, title=title)

            # Create Discord file and embed
            file = discord.File(io.BytesIO(image_bytes), filename="usage_chart.png")
            embed = discord.Embed(title="Usage Statistics", color=0x3498DB)
            embed.set_image(url="attachment://usage_chart.png")

            # Add scope info to embed
            scope_text = "This server only" if server_only else "All servers"
            embed.set_footer(text=f"Scope: {scope_text}")

            await interaction.followup.send(embed=embed, file=file)

        except Exception as e:
            logger.exception("command_error", error=str(e))
            error_view = InfoEmbedView(
                message=interaction.message,
                user=embed_user,
                title="Usage Stats Error",
                description="An unexpected error occurred while generating usage stats.",
                is_error=True,
            )
            await error_view.initialize(interaction)
