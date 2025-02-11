SELECT
    channel_messages.channel_message_id,
    message_type,
    message_data,
    message_images,
    message_timestamp,
    vendors.vendor_name
FROM channels
JOIN channel_messages
    ON channel_messages.channel_id = channels.channel_id
JOIN vendors
    ON channel_messages.vendor_id = vendors.vendor_id
WHERE channels.discord_id = ?
AND (vendors.vendor_name = ? OR ? = "All Models")
AND channel_messages.visible = TRUE
AND channel_messages.is_image_prompt = FALSE
AND channel_messages.message_images != "[]"
ORDER BY channel_messages.message_timestamp ASC
LIMIT ?
;