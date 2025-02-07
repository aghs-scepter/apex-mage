SELECT
    COUNT(channel_messages.channel_message_id) AS count
FROM channels
JOIN channel_messages
    ON channel_messages.channel_id = channels.channel_id
JOIN vendors
    ON channel_messages.vendor_id = vendors.vendor_id
WHERE channels.discord_id = ?
AND (vendors.vendor_name = "Fal.AI")
AND channel_messages.message_type = "prompt"
AND channel_messages.is_image_prompt = 1
AND channel_messages.message_timestamp BETWEEN datetime('now', '-1 hour') AND datetime('now')
;