"""Shared constants for Discord client components."""

# Embed colors (Discord color values)
EMBED_COLOR_ERROR = 0xE91515
EMBED_COLOR_INFO = 0x3498DB

# Timeout constants (seconds)
# User interaction timeout (how long user has to click/submit)
USER_INTERACTION_TIMEOUT = 300.0  # 5 minutes
# Extended timeout for result views where user may take time to decide
EXTENDED_USER_INTERACTION_TIMEOUT = 600.0  # 10 minutes
# API timeout for image generation calls
API_TIMEOUT_SECONDS = 180
