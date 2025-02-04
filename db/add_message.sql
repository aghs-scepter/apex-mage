INSERT INTO channel_messages(
    channel_id,
    vendor_id,
    message_type,
    message_data,
    is_image_prompt
)
SELECT
    (SELECT channel_id FROM channels WHERE discord_id = ?),
    (SELECT vendor_id FROM vendors WHERE vendor_name = ?),
    ?,
    ?,
    ?
;