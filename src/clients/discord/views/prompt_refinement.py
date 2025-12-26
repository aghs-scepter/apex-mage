"""Views for prompt refinement in the create_image command.

This module provides UI components for the opt-in prompt refinement flow:
1. PromptRefinementView: Shows the initial prompt with [Refine with AI] button
2. PromptComparisonView: Shows original vs refined for comparison
3. PromptEditModal: Modal for editing the refined prompt
"""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

import discord

from src.clients.discord.constants import (
    EMBED_COLOR_ERROR,
    EMBED_COLOR_INFO,
    USER_INTERACTION_TIMEOUT,
)
from src.clients.discord.utils import get_user_info
from src.core.logging import get_logger

logger = get_logger(__name__)
# Threshold for long prompt warning
LONG_PROMPT_THRESHOLD = 500


class PromptRefinementView(discord.ui.View):
    """View that shows a prompt with option to refine using AI.

    This view displays the user's original prompt and offers an opt-in
    [Refine with AI] button. If clicked, it calls haiku_complete() with
    the refinement prompt and transitions to PromptComparisonView.

    Attributes:
        prompt: The original user prompt.
        user: User info dict with name, id, and pfp keys.
        message: The Discord message to edit.
        on_generate: Callback when user chooses to generate with a prompt.
    """

    def __init__(
        self,
        prompt: str,
        user: dict[str, Any] | None = None,
        message: discord.Message | None = None,
        on_generate: (
            Callable[[discord.Interaction, str], Coroutine[Any, Any, None]] | None
        ) = None,
    ) -> None:
        super().__init__(timeout=USER_INTERACTION_TIMEOUT)
        self.prompt = prompt
        self.user = user
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.embed: discord.Embed | None = None
        self.message = message
        self.on_generate = on_generate

    async def initialize(self, interaction: discord.Interaction) -> None:
        """Create and display the prompt review embed."""
        # Check for long prompt
        is_long_prompt = len(self.prompt) > LONG_PROMPT_THRESHOLD
        warning_text = ""
        if is_long_prompt:
            warning_text = (
                "\n\n**Warning:** Long prompt detected. Refinement may truncate."
            )

        # Truncate prompt for display if needed
        display_prompt = self.prompt
        if len(display_prompt) > 1000:
            display_prompt = display_prompt[:997] + "..."

        self.embed = discord.Embed(
            title="Review Your Prompt",
            description=(
                f"Your prompt:\n```\n{display_prompt}\n```"
                f"{warning_text}\n\n"
                "Click **Refine with AI** to improve your prompt, "
                "or **Generate** to use it as-is."
            ),
            color=EMBED_COLOR_INFO,
        )
        self.embed.set_author(
            name=f"{self.username} (via Apex Mage)",
            url="https://github.com/aghs-scepter/apex-mage",
            icon_url=self.pfp,
        )

        self.message = await interaction.followup.send(
            embed=self.embed,
            view=self,
            wait=True,
        )
        logger.debug("view_initialized", view="PromptRefinementView")

    def hide_buttons(self) -> None:
        """Remove all buttons from the view."""
        self.clear_items()

    @discord.ui.button(label="Refine with AI", style=discord.ButtonStyle.primary)
    async def refine_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["PromptRefinementView"],
    ) -> None:
        """Refine the prompt using Haiku AI."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        self.stop()

        # Show processing state with original prompt (E4-T2)
        display_prompt = self.prompt
        if len(display_prompt) > 500:
            display_prompt = display_prompt[:497] + "..."
        if self.embed:
            self.embed.description = (
                f"Refining your prompt with AI...\n\n"
                f"**Original prompt:**\n```\n{display_prompt}\n```"
            )
        self.hide_buttons()
        if self.message:
            await self.message.edit(embed=self.embed, view=self)

        # Call Haiku to refine the prompt
        from src.core.haiku import HaikuError, haiku_complete
        from src.core.prompts.refinement import IMAGE_GENERATION_REFINEMENT_PROMPT

        refined_prompt: str | None = None
        error_message: str | None = None

        # Try up to 2 times (initial + 1 retry)
        for attempt in range(2):
            try:
                refined_prompt = await haiku_complete(
                    system_prompt=IMAGE_GENERATION_REFINEMENT_PROMPT,
                    user_message=self.prompt,
                    max_tokens=512,
                )
                break  # Success, exit retry loop
            except HaikuError as e:
                logger.warning(
                    "haiku_refinement_failed",
                    view="PromptRefinementView",
                    attempt=attempt + 1,
                    error=str(e),
                )
                if attempt == 0:
                    # First failure, will retry
                    await asyncio.sleep(1)
                else:
                    # Second failure, give up
                    error_message = str(e)

        if refined_prompt:
            # Success: Show comparison view
            comparison_view = PromptComparisonView(
                original_prompt=self.prompt,
                refined_prompt=refined_prompt,
                user=self.user,
                message=self.message,
                on_generate=self.on_generate,
            )
            await comparison_view.initialize(interaction)
        else:
            # Failure: Show error with fallback option
            if self.embed:
                self.embed.title = "Refinement Failed"
                self.embed.description = (
                    f"Failed to refine prompt: {error_message or 'Unknown error'}\n\n"
                    "You can still generate with your original prompt."
                )
                self.embed.color = EMBED_COLOR_ERROR

            # Create a simple fallback view with just "Use Original" button
            fallback_view = PromptRefinementFallbackView(
                prompt=self.prompt,
                user=self.user,
                message=self.message,
                on_generate=self.on_generate,
            )
            if self.message:
                await self.message.edit(embed=self.embed, view=fallback_view)

    @discord.ui.button(label="Generate", style=discord.ButtonStyle.success)
    async def generate_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["PromptRefinementView"],
    ) -> None:
        """Generate image with the original prompt."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        # Defer the interaction before long-running image generation
        await interaction.response.defer()

        self.stop()
        self.hide_buttons()
        if self.message:
            await self.message.edit(view=self)

        if self.on_generate:
            await self.on_generate(interaction, self.prompt)

    @discord.ui.button(label="X", style=discord.ButtonStyle.danger)
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["PromptRefinementView"],
    ) -> None:
        """Cancel the operation."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        self.stop()
        self.hide_buttons()

        if self.embed:
            self.embed.title = "Cancelled"
            self.embed.description = "Image generation was cancelled."
        if self.message:
            await self.message.edit(embed=self.embed, view=self)

    async def on_timeout(self) -> None:
        """Handle view timeout."""
        self.hide_buttons()
        if self.embed:
            self.embed.title = "Session Expired"
            self.embed.description = "This interaction has timed out. Please start again."
        if self.message:
            try:
                await self.message.edit(embed=self.embed, view=self)
            except Exception:
                pass


class PromptRefinementFallbackView(discord.ui.View):
    """Simple fallback view when refinement fails.

    Shows a single "Use Original" button to proceed with the original prompt.
    """

    def __init__(
        self,
        prompt: str,
        user: dict[str, Any] | None = None,
        message: discord.Message | None = None,
        on_generate: (
            Callable[[discord.Interaction, str], Coroutine[Any, Any, None]] | None
        ) = None,
    ) -> None:
        super().__init__(timeout=USER_INTERACTION_TIMEOUT)
        self.prompt = prompt
        self.user = user
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.message = message
        self.on_generate = on_generate

    def hide_buttons(self) -> None:
        """Remove all buttons from the view."""
        self.clear_items()

    @discord.ui.button(label="Use Original", style=discord.ButtonStyle.primary)
    async def use_original_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["PromptRefinementFallbackView"],
    ) -> None:
        """Generate with the original prompt."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        # Defer the interaction before long-running image generation
        await interaction.response.defer()

        self.stop()
        self.hide_buttons()
        if self.message:
            await self.message.edit(view=self)

        if self.on_generate:
            await self.on_generate(interaction, self.prompt)

    async def on_timeout(self) -> None:
        """Handle view timeout."""
        self.hide_buttons()
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


class PromptEditModal(discord.ui.Modal, title="Edit Refined Prompt"):
    """Modal for editing a refined prompt."""

    def __init__(
        self,
        refined_prompt: str,
        on_submit: Callable[[discord.Interaction, str], Coroutine[Any, Any, None]],
    ) -> None:
        super().__init__(timeout=None)
        self.on_submit_callback = on_submit

        self.prompt: discord.ui.TextInput[PromptEditModal] = discord.ui.TextInput(
            label="Edit the refined prompt:",
            style=discord.TextStyle.paragraph,
            default=refined_prompt,
            max_length=2000,
            required=True,
        )
        self.add_item(self.prompt)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle modal submission."""
        await self.on_submit_callback(interaction, self.prompt.value)

    async def on_error(  # type: ignore[override]
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
        """Handle modal errors."""
        logger.error("modal_error", view="PromptEditModal", error=str(error))
        try:
            await interaction.response.send_message(
                "An error occurred. Please try again.",
                ephemeral=True,
            )
        except discord.errors.InteractionResponded:
            await interaction.followup.send(
                "An error occurred. Please try again.",
                ephemeral=True,
            )


class PromptComparisonView(discord.ui.View):
    """View that shows original vs refined prompt for comparison.

    Displays both prompts and offers buttons to:
    - Use Refined: Generate with the refined prompt
    - Edit Refined: Open a modal to edit the refined prompt
    - Use Original: Generate with the original prompt

    Attributes:
        original_prompt: The user's original prompt.
        refined_prompt: The AI-refined prompt.
        user: User info dict.
        message: The Discord message to edit.
        on_generate: Callback when user chooses to generate.
    """

    def __init__(
        self,
        original_prompt: str,
        refined_prompt: str,
        user: dict[str, Any] | None = None,
        message: discord.Message | None = None,
        on_generate: (
            Callable[[discord.Interaction, str], Coroutine[Any, Any, None]] | None
        ) = None,
    ) -> None:
        super().__init__(timeout=USER_INTERACTION_TIMEOUT)
        self.original_prompt = original_prompt
        self.refined_prompt = refined_prompt
        self.user = user
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.embed: discord.Embed | None = None
        self.message = message
        self.on_generate = on_generate

    async def initialize(self, interaction: discord.Interaction) -> None:
        """Create and display the comparison embed."""
        # Truncate prompts for display if needed
        display_original = self.original_prompt
        if len(display_original) > 500:
            display_original = display_original[:497] + "..."

        display_refined = self.refined_prompt
        if len(display_refined) > 500:
            display_refined = display_refined[:497] + "..."

        self.embed = discord.Embed(
            title="Prompt Comparison",
            description="Compare your original prompt with the AI-refined version.",
            color=EMBED_COLOR_INFO,
        )
        self.embed.set_author(
            name=f"{self.username} (via Apex Mage)",
            url="https://github.com/aghs-scepter/apex-mage",
            icon_url=self.pfp,
        )
        self.embed.add_field(
            name="Original Prompt",
            value=f"```\n{display_original}\n```",
            inline=False,
        )
        self.embed.add_field(
            name="Refined Prompt",
            value=f"```\n{display_refined}\n```",
            inline=False,
        )

        if self.message:
            await self.message.edit(embed=self.embed, view=self)
        logger.debug("view_initialized", view="PromptComparisonView")

    def hide_buttons(self) -> None:
        """Remove all buttons from the view."""
        self.clear_items()

    @discord.ui.button(label="Use Refined", style=discord.ButtonStyle.success)
    async def use_refined_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["PromptComparisonView"],
    ) -> None:
        """Generate with the refined prompt."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        # Defer the interaction before long-running image generation
        await interaction.response.defer()

        self.stop()
        self.hide_buttons()
        if self.message:
            await self.message.edit(view=self)

        if self.on_generate:
            await self.on_generate(interaction, self.refined_prompt)

    @discord.ui.button(label="Edit Refined", style=discord.ButtonStyle.primary)
    async def edit_refined_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["PromptComparisonView"],
    ) -> None:
        """Open modal to edit the refined prompt."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        async def on_edit_submit(
            modal_interaction: discord.Interaction, edited_prompt: str
        ) -> None:
            """Handle edited prompt submission."""
            # Defer the modal interaction before long-running image generation
            await modal_interaction.response.defer()

            self.stop()
            self.hide_buttons()
            if self.message:
                await self.message.edit(view=self)

            if self.on_generate:
                await self.on_generate(modal_interaction, edited_prompt)

        modal = PromptEditModal(
            refined_prompt=self.refined_prompt,
            on_submit=on_edit_submit,
        )
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Use Original", style=discord.ButtonStyle.secondary)
    async def use_original_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["PromptComparisonView"],
    ) -> None:
        """Generate with the original prompt."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        # Defer the interaction before long-running image generation
        await interaction.response.defer()

        self.stop()
        self.hide_buttons()
        if self.message:
            await self.message.edit(view=self)

        if self.on_generate:
            await self.on_generate(interaction, self.original_prompt)

    @discord.ui.button(label="X", style=discord.ButtonStyle.danger)
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["PromptComparisonView"],
    ) -> None:
        """Cancel the operation."""
        if self.user_id != interaction.user.id:
            await interaction.response.send_message(
                f"Only the original requester ({self.username}) can use this.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        self.stop()
        self.hide_buttons()

        if self.embed:
            self.embed.title = "Cancelled"
            self.embed.description = "Image generation was cancelled."
            self.embed.clear_fields()
        if self.message:
            await self.message.edit(embed=self.embed, view=self)

    async def on_timeout(self) -> None:
        """Handle view timeout."""
        self.hide_buttons()
        if self.embed:
            self.embed.title = "Session Expired"
            self.embed.description = "This interaction has timed out. Please start again."
        if self.message:
            try:
                await self.message.edit(embed=self.embed, view=self)
            except Exception:
                pass
