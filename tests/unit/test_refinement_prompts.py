"""Unit tests for the refinement system prompts.

These tests verify that the refinement prompts are properly defined and
produce the expected style of output when used with the Haiku API.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.prompts.refinement import (
    IMAGE_GENERATION_REFINEMENT_PROMPT,
    IMAGE_MODIFICATION_REFINEMENT_PROMPT,
)


class TestPromptConstants:
    """Tests for the prompt constant definitions."""

    def test_generation_prompt_is_string(self) -> None:
        """Test that IMAGE_GENERATION_REFINEMENT_PROMPT is a non-empty string."""
        assert isinstance(IMAGE_GENERATION_REFINEMENT_PROMPT, str)
        assert len(IMAGE_GENERATION_REFINEMENT_PROMPT) > 0

    def test_modification_prompt_is_string(self) -> None:
        """Test that IMAGE_MODIFICATION_REFINEMENT_PROMPT is a non-empty string."""
        assert isinstance(IMAGE_MODIFICATION_REFINEMENT_PROMPT, str)
        assert len(IMAGE_MODIFICATION_REFINEMENT_PROMPT) > 0

    def test_generation_prompt_instructs_concise_output(self) -> None:
        """Test that the generation prompt emphasizes concise output."""
        prompt_lower = IMAGE_GENERATION_REFINEMENT_PROMPT.lower()
        assert "concise" in prompt_lower or "brief" in prompt_lower

    def test_generation_prompt_instructs_output_only(self) -> None:
        """Test that the generation prompt instructs to output only the prompt."""
        assert "ONLY the refined prompt" in IMAGE_GENERATION_REFINEMENT_PROMPT

    def test_modification_prompt_instructs_output_only(self) -> None:
        """Test that the modification prompt instructs to output only the instruction."""
        assert "ONLY the refined edit instruction" in IMAGE_MODIFICATION_REFINEMENT_PROMPT

    def test_modification_prompt_includes_action_verbs(self) -> None:
        """Test that the modification prompt mentions action verbs."""
        assert "action verbs" in IMAGE_MODIFICATION_REFINEMENT_PROMPT.lower()

    def test_generation_prompt_mentions_comma_separated(self) -> None:
        """Test that generation prompt specifies comma-separated format."""
        assert "comma-separated" in IMAGE_GENERATION_REFINEMENT_PROMPT.lower()

    def test_prompts_are_different(self) -> None:
        """Test that generation and modification prompts are distinct."""
        assert IMAGE_GENERATION_REFINEMENT_PROMPT != IMAGE_MODIFICATION_REFINEMENT_PROMPT


class TestGenerationPromptIntegration:
    """Integration-style tests showing expected behavior with mocked Haiku API.

    These tests demonstrate the expected input/output patterns for the
    generation refinement prompt.
    """

    @pytest.mark.asyncio
    async def test_refines_simple_prompt(self) -> None:
        """Test that a simple prompt gets refined with technical details."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            # Simulate Haiku returning a refined prompt
            mock_response = MagicMock()
            mock_response.content = [
                MagicMock(text="Orange tabby cat, knitted beanie hat, sitting pose, neutral gray background, centered composition")
            ]

            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                from src.core.haiku import haiku_complete

                result = await haiku_complete(
                    system_prompt=IMAGE_GENERATION_REFINEMENT_PROMPT,
                    user_message="a cat wearing a hat",
                )

            # Verify the result is technical and concise
            assert result is not None
            assert len(result) < 200  # Should be concise
            # Verify Haiku was called with the refinement prompt
            call_kwargs = mock_client.messages.create.call_args.kwargs
            assert call_kwargs["system"] == IMAGE_GENERATION_REFINEMENT_PROMPT

    @pytest.mark.asyncio
    async def test_refines_vague_prompt(self) -> None:
        """Test that a vague prompt gets refined with specific details."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = [
                MagicMock(text="Cyberpunk cityscape, neon pink and blue lights, rain-slicked streets, night, wide angle, dense skyscrapers")
            ]

            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                from src.core.haiku import haiku_complete

                result = await haiku_complete(
                    system_prompt=IMAGE_GENERATION_REFINEMENT_PROMPT,
                    user_message="futuristic city",
                )

            assert "cityscape" in result.lower() or "city" in result.lower()


class TestModificationPromptIntegration:
    """Integration-style tests showing expected behavior with mocked Haiku API.

    These tests demonstrate the expected input/output patterns for the
    modification refinement prompt.
    """

    @pytest.mark.asyncio
    async def test_refines_simple_edit(self) -> None:
        """Test that a simple edit description gets refined with specifics."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = [
                MagicMock(text="Reduce brightness 40%, increase contrast 20%, add subtle shadow overlay")
            ]

            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                from src.core.haiku import haiku_complete

                result = await haiku_complete(
                    system_prompt=IMAGE_MODIFICATION_REFINEMENT_PROMPT,
                    user_message="make it darker",
                )

            # Verify the result is specific and action-oriented
            assert result is not None
            assert len(result) < 150  # Should be concise
            # Verify Haiku was called with the modification prompt
            call_kwargs = mock_client.messages.create.call_args.kwargs
            assert call_kwargs["system"] == IMAGE_MODIFICATION_REFINEMENT_PROMPT

    @pytest.mark.asyncio
    async def test_refines_object_addition(self) -> None:
        """Test that object addition requests get refined."""
        with patch("src.core.haiku.AsyncAnthropic") as mock_client_class:
            mock_response = MagicMock()
            mock_response.content = [
                MagicMock(text="Add red baseball cap on subject's head, adjust shadows to match existing lighting")
            ]

            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                from src.core.haiku import haiku_complete

                result = await haiku_complete(
                    system_prompt=IMAGE_MODIFICATION_REFINEMENT_PROMPT,
                    user_message="add a hat",
                )

            # Verify the result uses action verbs
            result_lower = result.lower()
            assert any(verb in result_lower for verb in ["add", "place", "insert"])


class TestPromptExportedFromPackage:
    """Tests verifying prompts are correctly exported from the package."""

    def test_can_import_from_package(self) -> None:
        """Test that prompts can be imported from src.core.prompts."""
        from src.core.prompts import (
            IMAGE_GENERATION_REFINEMENT_PROMPT as gen_prompt,
        )
        from src.core.prompts import (
            IMAGE_MODIFICATION_REFINEMENT_PROMPT as mod_prompt,
        )

        assert gen_prompt is not None
        assert mod_prompt is not None

    def test_package_exports_match_module(self) -> None:
        """Test that package exports match the module definitions."""
        from src.core.prompts import IMAGE_GENERATION_REFINEMENT_PROMPT as pkg_gen
        from src.core.prompts import IMAGE_MODIFICATION_REFINEMENT_PROMPT as pkg_mod
        from src.core.prompts.refinement import IMAGE_GENERATION_REFINEMENT_PROMPT as mod_gen
        from src.core.prompts.refinement import IMAGE_MODIFICATION_REFINEMENT_PROMPT as mod_mod

        assert pkg_gen is mod_gen
        assert pkg_mod is mod_mod
