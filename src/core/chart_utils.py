"""Chart generation utilities for usage statistics visualization.

This module provides functions to generate matplotlib charts for displaying
usage statistics in a Discord-friendly format.
"""

import colorsys
import io
from typing import TypedDict

import matplotlib
import matplotlib.pyplot as plt

# Use non-interactive backend for server environments
matplotlib.use("Agg")


class UserStats(TypedDict):
    """Type definition for user statistics from get_top_users_by_usage."""

    user_id: int
    username: str
    image_count: int
    text_count: int
    total_score: int


def _get_user_color(user_id: int) -> tuple[float, float, float]:
    """Derive a consistent color from a Discord user ID.

    Uses HSV color space to generate visually distinct colors based on
    the user ID hash. The hue is derived from the user ID modulo 360.

    Args:
        user_id: Discord user ID (integer).

    Returns:
        RGB tuple with values in [0, 1] range.
    """
    hue = (user_id % 360) / 360
    saturation = 0.7
    value = 0.9
    return colorsys.hsv_to_rgb(hue, saturation, value)


def _get_dark_variant(color: tuple[float, float, float]) -> tuple[float, float, float]:
    """Get a darker variant of a color for text command bars.

    Reduces saturation and value to create a muted version.

    Args:
        color: RGB tuple with values in [0, 1] range.

    Returns:
        Darker RGB tuple with values in [0, 1] range.
    """
    # Convert RGB to HSV
    h, s, v = colorsys.rgb_to_hsv(color[0], color[1], color[2])
    # Reduce saturation and value for darker variant
    s_dark = s * 0.5
    v_dark = v * 0.6
    return colorsys.hsv_to_rgb(h, s_dark, v_dark)


async def generate_usage_chart(
    user_stats: list[UserStats],
    title: str = "Top Users by Usage",
) -> bytes:
    """Generate a stacked bar chart of usage statistics.

    Creates a horizontal stacked bar chart showing image commands (bright color)
    and text commands (dark color) for each user. Uses a dark background theme
    suitable for Discord.

    Args:
        user_stats: List of dicts with keys: user_id, username, image_count,
            text_count, total_score. Expected to be sorted by total_score descending.
        title: Chart title.

    Returns:
        PNG image as bytes.

    Example:
        >>> stats = [
        ...     {"user_id": 123, "username": "Alice", "image_count": 10,
        ...      "text_count": 50, "total_score": 100},
        ...     {"user_id": 456, "username": "Bob", "image_count": 5,
        ...      "text_count": 25, "total_score": 50},
        ... ]
        >>> image_bytes = await generate_usage_chart(stats)
        >>> assert image_bytes[:8] == b'\\x89PNG\\r\\n\\x1a\\n'
    """
    # Use dark background style for Discord
    with plt.style.context("dark_background"):
        # Create figure with specified size (600x300 px at 100 dpi = 6x3 inches)
        fig, ax = plt.subplots(figsize=(6, 3), dpi=100)

        if not user_stats:
            # Handle empty stats
            ax.text(
                0.5,
                0.5,
                "No usage data available",
                ha="center",
                va="center",
                transform=ax.transAxes,
                fontsize=12,
                color="white",
            )
            ax.set_title(title, fontsize=14, fontweight="bold", color="white")
        else:
            # Prepare data - reverse order so highest score is at top
            usernames = [stat["username"] for stat in reversed(user_stats)]
            image_counts = [stat["image_count"] for stat in reversed(user_stats)]
            text_counts = [stat["text_count"] for stat in reversed(user_stats)]
            user_ids = [stat["user_id"] for stat in reversed(user_stats)]

            # Y positions for bars
            y_positions = range(len(usernames))

            # Generate colors for each user
            image_colors = [_get_user_color(uid) for uid in user_ids]
            text_colors = [_get_dark_variant(c) for c in image_colors]

            # Create stacked horizontal bars
            # Text commands (dark) go first, image commands (bright) stack on top
            ax.barh(
                y_positions,
                text_counts,
                label="Text Commands",
                color=text_colors,
                edgecolor="none",
            )
            ax.barh(
                y_positions,
                image_counts,
                left=text_counts,
                label="Image Commands (5x)",
                color=image_colors,
                edgecolor="none",
            )

            # Configure axes
            ax.set_yticks(list(y_positions))
            ax.set_yticklabels(usernames, fontsize=10)
            ax.set_xlabel("Command Count", fontsize=10)
            ax.set_title(title, fontsize=14, fontweight="bold", color="white")

            # Add legend
            ax.legend(loc="lower right", fontsize=8)

            # Add value labels on bars
            for i, (text_count, image_count) in enumerate(
                zip(text_counts, image_counts, strict=True)
            ):
                total = text_count + image_count
                if total > 0:
                    ax.text(
                        total + 0.5,
                        i,
                        str(total),
                        va="center",
                        ha="left",
                        fontsize=8,
                        color="white",
                    )

        # Adjust layout
        plt.tight_layout()

        # Save to bytes buffer
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png", facecolor=fig.get_facecolor(), edgecolor="none")
        plt.close(fig)

        buffer.seek(0)
        return buffer.read()
