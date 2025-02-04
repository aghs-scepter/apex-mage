UPDATE channel_messages
SET visible = FALSE
WHERE channel_id = (SELECT channel_id FROM channels WHERE discord_id = ?)
AND (vendor_id = (SELECT vendor_id FROM vendors WHERE vendor_name = ?) Or ? = "All Models")
;