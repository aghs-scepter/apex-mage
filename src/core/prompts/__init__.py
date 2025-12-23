"""System prompts for AI-powered features.

This package contains tunable system prompts for various AI-powered
functionality in the bot, organized by feature area.

Modules:
    refinement: Prompts for refining user input into model-friendly prompts.
    summarization: Prompts for summarizing conversation history.
"""

from src.core.prompts.refinement import (
    IMAGE_GENERATION_REFINEMENT_PROMPT,
    IMAGE_MODIFICATION_REFINEMENT_PROMPT,
)
from src.core.prompts.summarization import (
    SUMMARIZATION_PROMPT,
    build_summarization_prompt,
)

__all__ = [
    "IMAGE_GENERATION_REFINEMENT_PROMPT",
    "IMAGE_MODIFICATION_REFINEMENT_PROMPT",
    "SUMMARIZATION_PROMPT",
    "build_summarization_prompt",
]
