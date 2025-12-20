"""Image-related Discord slash commands."""

import asyncio
import base64
import json
from os import getenv
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands

from src.clients.discord.decorators import count_command
from src.clients.discord.utils import create_embed_user, handle_text_overflow
from src.clients.discord.views.carousel import (
    ImageEditPerformView,
    ImageEditTypeView,
    ImageSelectionTypeView,
    InfoEmbedView,
    MultiImageCarouselView,
)
from src.core.image_utils import (
    compress_image,
    format_image_response,
    image_strip_headers,
)
from src.core.logging import get_logger
from src.core.providers import ImageRequest

if TYPE_CHECKING:
    from src.clients.discord.bot import DiscordBot

logger = get_logger(__name__)

# Timeout constants
DEFAULT_IMAGE_TIMEOUT = 240.0
DEFAULT_USER_INTERACTION_TIMEOUT = 90.0
DEFAULT_EXTENDED_USER_INTERACTION_TIMEOUT = 600.0


def register_image_commands(bot: "DiscordBot") -> None:
    """Register image-related commands with the bot.

    Args:
        bot: The Discord bot instance.
    """

    @bot.tree.command()  # type: ignore[arg-type]
    @app_commands.describe(image="Image file to upload to the bot")
    @count_command
    async def upload_image(
        interaction: discord.Interaction, image: discord.Attachment
    ) -> None:
        """Upload an image to the bot for use in future prompting.

        Args:
            interaction: The Discord interaction.
            image: The image attachment to upload.
        """
        assert interaction.channel_id is not None, "Command must be used in a channel"
        channel_id = interaction.channel_id
        await interaction.response.defer()

        embed_user = create_embed_user(interaction)

        images = []
        file_extension = image.filename.split(".")[-1].lower()
        if file_extension in ["png", "jpg", "jpeg"]:
            file_data = await image.read()
            image_b64 = base64.b64encode(file_data).decode("utf-8")
            image_b64 = await asyncio.to_thread(compress_image, image_b64)

            filename_without_ext = image.filename.rsplit(".", 1)[0]
            new_filename = f"{filename_without_ext}.jpeg"

            image_data = {"filename": new_filename, "image": image_b64}
            images.append(image_data)
            await image.to_file()
            str_images = json.dumps(images)

            await bot.repo.create_channel(channel_id)
            await bot.repo.add_message_with_images(
                channel_id,
                "Anthropic",
                "prompt",
                False,
                "Uploaded Image",
                str_images,
            )

            success_message = (
                "This image was uploaded successfully. "
                "You can use it for future `/prompt` and `/modify_image` commands."
            )
            success_view = InfoEmbedView(
                message=interaction.message,
                user=embed_user,
                title="Upload successful",
                description=success_message,
                is_error=False,
                image_data=image_data,
            )
            await success_view.initialize(interaction)
        else:
            error_message = (
                "The uploaded file is not a valid image format. "
                "Please upload a `.png`, `.jpg`, or `.jpeg` file."
            )
            error_view = InfoEmbedView(
                message=interaction.message,
                user=embed_user,
                title="Upload error!",
                description=error_message,
                is_error=True,
                image_data=None,
            )
            await error_view.initialize(interaction)

    @bot.tree.command()  # type: ignore[arg-type]
    @app_commands.describe(prompt="Description of the image you want to generate")
    @count_command
    async def create_image(
        interaction: discord.Interaction,
        prompt: str,
        timeout: float | None = None,
    ) -> None:
        """Generate an image using the AI.

        Args:
            interaction: The Discord interaction.
            prompt: Description of the image to generate.
            timeout: The timeout for the request in seconds.
        """
        assert interaction.channel_id is not None, "Command must be used in a channel"
        channel_id = interaction.channel_id
        await interaction.response.defer()

        if timeout is None:
            timeout = DEFAULT_IMAGE_TIMEOUT

        embed_user = create_embed_user(interaction)

        try:
            async with asyncio.timeout(timeout):
                rate_check = await bot.rate_limiter.check(interaction.user.id, "image")

                if rate_check.allowed:
                    display_prompt, full_prompt_url = await handle_text_overflow(
                        bot, "prompt", prompt, channel_id
                    )

                    await bot.repo.create_channel(channel_id)
                    await bot.repo.add_message(
                        channel_id, "Fal.AI", "prompt", True, prompt
                    )

                    processing_message = (
                        "Generating an image... (This may take up to 180 seconds)"
                    )
                    processing_notes = [{"name": "Prompt", "value": display_prompt}]
                    processing_view = InfoEmbedView(
                        message=interaction.message,
                        user=embed_user,
                        title="Image generation in progress",
                        description=processing_message,
                        is_error=False,
                        notes=processing_notes,
                        full_prompt_url=full_prompt_url,
                    )
                    await processing_view.initialize(interaction)

                    generated_images = await bot.image_provider.generate(
                        ImageRequest(prompt=prompt)
                    )
                    generated_image = generated_images[0]
                    if generated_image.url is None:
                        raise ValueError("Generated image has no URL")
                    image_data = image_strip_headers(generated_image.url, "jpeg")
                    image_data = await asyncio.to_thread(compress_image, image_data)
                    str_image = json.dumps(
                        [{"filename": "image.jpeg", "image": image_data}]
                    )
                    await bot.repo.add_message_with_images(
                        channel_id,
                        "Fal.AI",
                        "prompt",
                        False,
                        "Image",
                        str_image,
                    )

                    await bot.rate_limiter.record(interaction.user.id, "image")

                    has_nsfw = generated_image.has_nsfw_content or False
                    output_filename, _ = format_image_response(
                        image_data, "jpeg", has_nsfw
                    )

                    # Upload image to GCS for download button
                    download_url: str | None = None
                    try:
                        download_url = await asyncio.to_thread(
                            bot.gcs_adapter.upload_generated_image,
                            channel_id,
                            image_data,
                        )
                        logger.info(
                            "image_uploaded_to_gcs",
                            channel_id=channel_id,
                            download_url=download_url,
                        )
                    except Exception as upload_error:
                        logger.error(
                            "gcs_upload_failed",
                            channel_id=channel_id,
                            error=str(upload_error),
                        )
                        # Continue without download URL - image still shows

                    output_message = (
                        "Your image was created successfully. "
                        "You can use it for future `/prompt` and `/modify_image` commands."
                    )
                    output_notes = [{"name": "Prompt", "value": display_prompt}]
                    output_view = InfoEmbedView(
                        message=interaction.message,
                        user=embed_user,
                        title="Image generation successful",
                        description=output_message,
                        is_error=False,
                        notes=output_notes,
                        full_prompt_url=full_prompt_url,
                        image_data={"filename": output_filename, "image": image_data},
                        download_url=download_url,
                    )
                    await output_view.initialize(interaction)
                else:
                    wait_msg = (
                        f" Try again in {int(rate_check.wait_seconds)} seconds."
                        if rate_check.wait_seconds
                        else ""
                    )
                    error_message = (
                        f"You're requesting too many images and have been rate-limited. "
                        f"The bot can handle a maximum of "
                        f"{getenv('FAL_RATE_LIMIT', '8')} `/create_image` requests "
                        f"per hour.{wait_msg}"
                    )

                    display_prompt, full_prompt_url = await handle_text_overflow(
                        bot, "prompt", prompt, channel_id
                    )

                    error_notes = [{"name": "Prompt", "value": display_prompt}]
                    error_view = InfoEmbedView(
                        message=interaction.message,
                        user=embed_user,
                        title="Image generation error!",
                        description=error_message,
                        is_error=True,
                        image_data=None,
                        notes=error_notes,
                        full_prompt_url=full_prompt_url,
                    )
                    await error_view.initialize(interaction)

        except TimeoutError:
            error_message = (
                f"The image generation request timed out after {timeout} seconds. "
                "Please try again."
            )

            display_prompt, full_prompt_url = await handle_text_overflow(
                bot, "prompt", prompt, channel_id
            )

            error_notes = [{"name": "Prompt", "value": display_prompt}]
            error_view = InfoEmbedView(
                message=interaction.message,
                user=embed_user,
                title="Image generation error!",
                description=error_message,
                is_error=True,
                image_data=None,
                notes=error_notes,
                full_prompt_url=full_prompt_url,
            )
            await error_view.initialize(interaction)

        except Exception:
            error_message = "An unexpected error occurred while processing your request."

            display_prompt, full_prompt_url = await handle_text_overflow(
                bot, "prompt", prompt, channel_id
            )

            error_notes = [{"name": "Prompt", "value": display_prompt}]
            error_view = InfoEmbedView(
                message=interaction.message,
                user=embed_user,
                title="Image generation error!",
                description=error_message,
                is_error=True,
                image_data=None,
                notes=error_notes,
                full_prompt_url=full_prompt_url,
            )
            await error_view.initialize(interaction)

    @bot.tree.command()  # type: ignore[arg-type]
    @app_commands.describe()
    @count_command
    async def modify_image(
        interaction: discord.Interaction,
        timeout: float | None = None,
    ) -> None:
        """Modify an existing image using the AI.

        Args:
            interaction: The Discord interaction.
            timeout: The timeout for user interaction in seconds.
        """
        assert interaction.channel_id is not None, "Command must be used in a channel"
        channel_id = interaction.channel_id
        await interaction.response.defer()

        if timeout is None:
            timeout = DEFAULT_USER_INTERACTION_TIMEOUT

        embed_user = create_embed_user(interaction)

        async def on_edit_complete(
            edit_interaction: discord.Interaction, result_data: dict[str, Any]
        ) -> None:
            """Handle image edit completion."""
            if result_data.get("error"):
                error_msg = result_data.get("message")
                error_view = InfoEmbedView(
                    message=interaction.message,
                    user=embed_user,
                    title="Image edit error!",
                    description=str(error_msg) if error_msg else "An error occurred during image editing.",
                    is_error=True,
                    image_data=None,
                )
                await error_view.initialize(edit_interaction)
            else:
                str_image = json.dumps([result_data])
                await bot.repo.add_message_with_images(
                    channel_id,
                    "Fal.AI",
                    "prompt",
                    False,
                    "Modified Image",
                    str_image,
                )

                success_message = (
                    "Your image was modified successfully. "
                    "You can use it for future `/prompt` and `/modify_image` commands."
                )
                # result_data contains filename, image, and prompt keys when successful
                image_data_typed: dict[str, str] = {
                    "filename": str(result_data.get("filename", "")),
                    "image": str(result_data.get("image", "")),
                }
                # Include prompt in success embed notes (like create_image does)
                prompt = result_data.get("prompt", "")
                output_notes = [{"name": "Prompt", "value": prompt}] if prompt else None
                success_view = InfoEmbedView(
                    message=interaction.message,
                    user=embed_user,
                    title="Image modified",
                    description=success_message,
                    is_error=False,
                    image_data=image_data_typed,
                    notes=output_notes,
                )
                await success_view.initialize(edit_interaction)

        async def on_edit_type_selected(
            edit_interaction: discord.Interaction, edit_type: str, prompt: str
        ) -> None:
            """Handle edit type and prompt selection."""
            if edit_type == "Cancel":
                # Embed already updated by the view's cancel handler
                # Just need to respond to the interaction if needed
                if not edit_interaction.response.is_done():
                    await edit_interaction.response.defer()
                return

            await edit_interaction.response.defer()

            # ImageEditPerformView now handles the processing embed with composite thumbnail
            if edit_interaction.message is None or not selected_images:
                raise RuntimeError("Message or selected_images is None/empty")
            perform_view = ImageEditPerformView(
                interaction=edit_interaction,
                message=edit_interaction.message,
                user=embed_user,
                image_data=selected_images[0],  # First image for display
                image_data_list=selected_images,  # All selected images
                edit_type=edit_type,
                prompt=prompt,
                on_complete=on_edit_complete,
                rate_limiter=bot.rate_limiter,
                image_provider=bot.image_provider,
                gcs_adapter=bot.gcs_adapter,
            )
            await perform_view.initialize(edit_interaction)

        selected_images: list[dict[str, str]] = []
        carousel_files: list[dict[str, str]] = []
        selected_indices: list[int] = []

        async def on_image_selected(
            img_interaction: discord.Interaction,
            image_data_list: list[dict[str, str]],
        ) -> None:
            """Handle image selection from multi-image carousel."""
            nonlocal selected_images, selected_indices

            if not image_data_list:
                # Empty list = cancelled
                # Embed already updated by the view's cancel handler
                return

            selected_images = image_data_list

            # Compute selected indices by finding the images in carousel_files
            selected_indices = []
            for img in image_data_list:
                for idx, f in enumerate(carousel_files):
                    if f["image"] == img["image"]:
                        selected_indices.append(idx)
                        break

            async def on_back(back_interaction: discord.Interaction) -> None:
                """Return to the carousel with preserved selection state."""
                carousel_view = MultiImageCarouselView(
                    interaction=back_interaction,
                    files=carousel_files,
                    user=embed_user,
                    message=back_interaction.message,
                    on_select=on_image_selected,
                    initial_selections=selected_indices,
                )
                await carousel_view.initialize(back_interaction)

            # Pass all selected images for composite thumbnail display
            edit_type_view = ImageEditTypeView(
                image_data=selected_images[0],
                user=embed_user,
                message=img_interaction.message,
                on_select=on_edit_type_selected,
                image_data_list=selected_images,
                on_back=on_back,
            )
            await edit_type_view.initialize(img_interaction)

        async def on_selection_type(
            sel_interaction: discord.Interaction, selection_type: str
        ) -> None:
            """Handle selection type choice."""
            nonlocal carousel_files

            if selection_type == "Cancel":
                # Embed already updated by the view's cancel handler
                # Just need to respond to the interaction if needed
                if not sel_interaction.response.is_done():
                    await sel_interaction.response.defer()
                return

            if selection_type == "Recent Images":
                await sel_interaction.response.defer()

                images = await bot.repo.get_images(channel_id, "All Models")
                carousel_files = images  # Store for back navigation

                # Use MultiImageCarouselView for multi-image selection
                carousel_view = MultiImageCarouselView(
                    interaction=sel_interaction,
                    files=images,
                    user=embed_user,
                    message=sel_interaction.message,
                    on_select=on_image_selected,
                )
                await carousel_view.initialize(sel_interaction)

        selection_view = ImageSelectionTypeView(
            interaction=interaction,
            user=embed_user,
            on_select=on_selection_type,
            repo=bot.repo,
        )
        await selection_view.initialize(interaction)
