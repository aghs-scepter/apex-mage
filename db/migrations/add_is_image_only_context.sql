-- Migration: Add is_image_only_context column to channel_messages
-- This column separates image-only context (for /describe_this, /modify_image)
-- from text prompt context (for /prompt).
-- Images added via "Add to Context" buttons should NOT appear in /prompt.

ALTER TABLE channel_messages ADD COLUMN is_image_only_context BOOLEAN DEFAULT FALSE;
