"""System prompts for refining user input into model-friendly prompts.

This module provides tunable prompt constants for AI-assisted prompt refinement.
The prompts are designed to work with Claude Haiku to transform rough user
input into precise, technical prompts suitable for image generation models
like fal.ai's "nano banana pro".

Example usage:
    from src.core.prompts.refinement import IMAGE_GENERATION_REFINEMENT_PROMPT
    from src.core.haiku import haiku_complete

    refined = await haiku_complete(
        system_prompt=IMAGE_GENERATION_REFINEMENT_PROMPT,
        user_message="a cat wearing a hat",
    )
    # Returns: "Orange tabby cat, knitted beanie hat, sitting pose, neutral background"

Prompt Design Principles:
    - Concise output: No flowery language or verbose descriptions
    - Technical focus: Use terminology image models understand
    - Action-oriented: For edits, specify exact transformations
    - Model-aware: Optimized for diffusion-based image generators
"""

# System prompt for refining image generation prompts.
#
# This prompt instructs Haiku to transform rough user descriptions into
# precise, technical prompts optimized for image generation models.
#
# Input: User's rough description (e.g., "a sunset over mountains")
# Output: Detailed, comma-separated technical prompt
#
# Example transformations:
#   "cat" -> "domestic cat, orange tabby, sitting, white background, centered"
#   "futuristic city" -> "cyberpunk cityscape, neon lights, rain, night, wide angle"
#   "portrait of a woman" -> "woman portrait, headshot, studio lighting, neutral expression"
#
IMAGE_GENERATION_REFINEMENT_PROMPT = """You are an image prompt optimizer. Transform rough descriptions into precise, technical prompts for image generation.

Rules:
1. Output ONLY the refined prompt, nothing else
2. Use comma-separated descriptors
3. Be concise - no flowery language
4. Include: subject, style, composition, lighting when relevant
5. Avoid abstract concepts the model cannot render
6. Keep output under 200 characters when possible

Focus on visual elements the model can understand: colors, materials, poses, camera angles, lighting conditions."""


# System prompt for refining image modification/edit prompts.
#
# This prompt instructs Haiku to transform rough edit descriptions into
# precise action-oriented instructions for image editing models.
#
# Input: User's rough edit description (e.g., "make it darker")
# Output: Specific edit instruction
#
# Example transformations:
#   "make it darker" -> "Reduce brightness 40%, increase contrast, add shadow overlay"
#   "add a hat" -> "Add red baseball cap on subject's head, matching lighting"
#   "change background" -> "Replace background with solid navy blue, preserve subject edges"
#
IMAGE_MODIFICATION_REFINEMENT_PROMPT = """You are an image edit optimizer. Transform rough edit descriptions into precise modification instructions.

Rules:
1. Output ONLY the refined edit instruction, nothing else
2. Be specific about what to change
3. Use action verbs: add, remove, change, adjust, replace
4. Include parameters when helpful: percentages, colors, positions
5. Reference "the subject" or "the image" for clarity
6. Keep output under 150 characters when possible

Focus on actionable edits: color adjustments, object additions/removals, style changes, background modifications."""


# System prompt for refining image modification prompts with character preservation.
#
# This prompt instructs Haiku to preserve character identity while transforming
# the edit description into precise action-oriented instructions.
#
# Input: User's rough edit description (e.g., "change the background to a beach")
# Output: Specific edit instruction that preserves character features
#
# Example transformations:
#   "sunset background" -> "Replace background with sunset scene, preserve all character features exactly"
#   "add sunglasses" -> "Add sunglasses, maintain exact facial features and appearance"
#   "different pose" -> "Change pose, preserve character's face, body type, outfit colors"
#
CHARACTER_PRESERVATION_REFINEMENT_PROMPT = """You are refining an image modification prompt. The user wants to preserve character consistency.

CRITICAL PRESERVATION RULES:
- DO NOT change: facial features, body type, hair color/style, skin tone, eye color, distinctive markings
- DO NOT change: outfit colors, character-specific accessories, signature items
- Preserve the character's identity exactly as they appear in the source image

ALLOWED CHANGES (only what the user explicitly requests):
- Pose, expression, camera angle
- Background, setting, environment
- Lighting, time of day, weather
- Additional props or objects (not replacing character items)

Take the user's rough description and create a detailed prompt that:
1. Explicitly instructs to preserve the character's appearance
2. Describes the requested changes clearly
3. Emphasizes maintaining visual consistency
4. Keep output under 500 characters when possible

Output ONLY the refined prompt, no explanations."""
