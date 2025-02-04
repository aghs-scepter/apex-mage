UPDATE channel_messages
SET visible = FALSE
WHERE channel_message_id NOT IN (
    SELECT
        channel_message_id
    FROM channel_messages
    WHERE channel_id = (SELECT channel_id FROM channels WHERE discord_id = ?)
    AND (vendor_id = (SELECT vendor_id FROM vendors WHERE vendor_name = ?) Or ? = "All Models")
    AND visible = TRUE
    ORDER BY message_timestamp DESC
    LIMIT ?
)
;