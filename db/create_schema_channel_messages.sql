CREATE TABLE IF NOT EXISTS channel_messages(
    channel_message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL,
    vendor_id INTEGER NOT NULL,
    message_type TEXT NOT NULL,
    message_data TEXT,
    message_images TEXT DEFAULT '[]',
    message_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    visible BOOLEAN DEFAULT TRUE,
    is_image_prompt BOOLEAN DEFAULT FALSE,
    image_b64 TEXT DEFAULT NULL,
    FOREIGN KEY (channel_id) REFERENCES channels(channel_id),
    FOREIGN KEY (vendor_id) REFERENCES vendors(vendor_id)
);