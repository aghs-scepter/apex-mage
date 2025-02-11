from typing import Optional, Dict, List, Any
from os import getenv
import json
import logging
import sqlite3

### WEIRD HARDCODING ###
WINDOW = 35 # Number of previous messages to use as context. High values will increase cost and latency.

def init_database() -> bool:
    """
    Initializes the database and schema if they don't exist.
    
    Returns:
    bool: True if the database was successfully initialized.
    """
    logging.debug(f"Connecting to database...")
    try:
        db = sqlite3.connect('data/app.db')
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON') # FKs enabled for fast reads; slower writes don't matter for this app
        logging.debug(f"Connected to database.")
    except Exception as ex:
        logging.error(f"Error connecting to database: {ex}")
        raise ex

    logging.debug(f"Initializing database schema...")
    try:
        db.execute(open('db/create_schema_channels.sql').read())
        db.execute(open('db/create_schema_vendors.sql').read())
        db.execute(open('db/create_schema_channel_messages.sql').read())
        logging.debug(f"Database schema initialized.")
    except Exception as ex:
        logging.error(f"Error initializing database schema: {ex}")
        raise ex
    
    return db

db = init_database()

### HELPER METHODS ###
def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """
    Converts a sqlite3.Row object to a dictionary for easier access.

    Parameters:
    row (sqlite3.Row): The row object to convert.

    Returns:
    Dict[str, Any]: The dictionary representation of the row.
    """
    return {key: row[key] for key in row.keys()}

### CUD METHODS ###
def add_channel(discord_id: int) -> None:
    """
    Adds a channel to the database. Each channel is independent of the others, so conversations do not cross channels.

    Parameters:
    discord_id (int): The Discord ID of the channel to add.
    """
    logging.debug(f"Adding channel {discord_id} to database...")
    query = open('db/add_channel.sql').read()
    db.execute(query, (discord_id,))
    db.commit()
    logging.debug(f"channel {discord_id} added to database.")

def add_vendor(vendor_name: str, vendor_model_name: str) -> None:
    """
    Adds an AI vendor to the database. Refers to the company, not a specific model.

    Parameters:
    vendor_name (str): The name of the vendor to add.
    """
    logging.debug(f"Adding vendor {vendor_name} to database...")
    query = open('db/add_vendor.sql').read()
    db.execute(query, (vendor_name,vendor_model_name,))
    db.commit()
    logging.debug(f"Vendor {vendor_name} added to database.")

def add_message(discord_id: int, vendor_name: str, message_type: str, is_image_prompt: bool, message_data: str) -> None:
    """
    Adds a message to the database. Messages include both user-submitted prompts as well as AI responses.
    """
    logging.debug(f"Adding message to database...")
    query = open('db/add_message.sql').read()
    db.execute(query, (discord_id,vendor_name,message_type,message_data,is_image_prompt,))
    db.commit()
    logging.debug(f"Message added to database.")

def add_message_with_images(discord_id: int, vendor_name: str, message_type: str, is_image_prompt: bool, message_data: str, message_images: str) -> None:
    """
    Adds a message containing image attachments to the database. Messages include both user-submitted prompts as well as AI responses.
    """
    logging.debug(f"Adding message to database...")
    query = open('db/add_message_with_images.sql').read()
    db.execute(query, (discord_id,vendor_name,message_type,message_data,message_images,is_image_prompt,))
    db.commit()
    logging.debug(f"Message added to database.")

def delete_channel_messages(discord_id: int, vendor_name: str) -> None:
    """
    Soft-deletes all messages for a given channel and vendor. This is used to clear the history of a conversation.
    """
    logging.debug(f"Deleting messages for channel {discord_id} and vendor {vendor_name}...")
    query = open('db/delete_channel_messages.sql').read()
    db.execute(query, (discord_id,vendor_name,vendor_name,))
    db.commit()
    logging.debug(f"Messages deleted for channel {discord_id} and vendor {vendor_name}.")


### R METHODS ###
def get_channel(discord_id: int) -> Optional[Dict[str, Any]]:
    """
    Gets a channel's record from the database by its Discord ID.

    Parameters:
    discord_id (int): The Discord ID of the channel to retrieve.

    Returns:
    Optional[Dict[str, Any]]: The channel's record if it exists, or None if it does not.
    """
    logging.debug(f"Getting channel {discord_id} from database...")
    query = open('db/get_channel.sql').read()
    cursor = db.execute(query, (discord_id,))
    row = cursor.fetchone()
    logging.debug(f"channel {discord_id} retrieved from database.")
    return row_to_dict(row) if row else None

def get_vendor(vendor_name: str) -> Optional[Dict[str, Any]]:
    """
    Gets a vendor's record from the database by its name.

    Parameters:
    vendor_name (str): The name of the vendor to retrieve.

    Returns:
    Optional[Dict[str, Any]]: The vendor's record if it exists, or None if it does not.
    """
    logging.debug(f"Getting vendor {vendor_name} from database...")
    query = open('db/get_vendor.sql').read()
    cursor = db.execute(query, (vendor_name,))
    row = cursor.fetchone()
    logging.debug(f"Vendor {vendor_name} retrieved from database.")
    return row_to_dict(row) if row else None

def get_latest_messages(discord_id: int, vendor_name: str, limit: int) -> List[Dict[str, Any]]:
    """
    Gets the latest messages for a given channel and vendor. This is used to provide context to the AI model.

    Parameters:
    discord_id (int): The Discord ID of the channel to retrieve messages for.
    vendor_name (str): The name of the vendor to retrieve messages for.
    limit (int): The maximum number of messages to retrieve.

    Returns:
    List[Dict[str, Any]]: A list of the latest messages for the channel and vendor in chronological order.
    """
    logging.debug(f"Getting latest messages for channel {discord_id} and vendor {vendor_name}...")
    query = open('db/get_latest_messages.sql').read()
    cursor = db.execute(query, (discord_id,vendor_name,vendor_name,limit,))
    rows = cursor.fetchall()
    logging.debug(f"Latest messages retrieved for channel {discord_id} and vendor {vendor_name}.")
    return [row_to_dict(row) for row in rows]

def get_latest_images(discord_id: int, vendor_name: str, limit: int) -> List[Dict[str, Any]]:
    """
    Gets the latest image messages for a given channel and vendor. This is used to provide context to the AI model.

    Parameters:
    discord_id (int): The Discord ID of the channel to retrieve messages for.
    vendor_name (str): The name of the vendor to retrieve messages for.
    limit (int): The maximum number of messages to retrieve.

    Returns:
    List[Dict[str, Any]]: A list of the latest image messages for the channel and vendor in chronological order.
    """
    logging.debug(f"Getting latest image messages for channel {discord_id} and vendor {vendor_name}...")
    query = open('db/get_latest_images.sql').read()
    cursor = db.execute(query, (discord_id,vendor_name,vendor_name,limit,))
    rows = cursor.fetchall()
    logging.debug(f"Latest image messages retrieved for channel {discord_id} and vendor {vendor_name}.")
    return [row_to_dict(row) for row in rows]

def get_visible_messages(discord_id: int, vendor_name: str) -> List[Dict[str, Any]]:
    """
    Gets all messages for a given channel and vendor. This is used to provide context to the AI model or for auditing.

    Parameters:
    discord_id (int): The Discord ID of the channel to retrieve messages for.
    vendor_name (str): The name of the vendor to retrieve messages for.

    Returns:
    List[Dict[str, Any]]: A list of all messages for the channel and vendor in chronological order
    """
    logging.debug(f"Getting visible messages for channel {discord_id} and vendor {vendor_name}...")
    query = open('db/get_visible_messages.sql').read()
    cursor = db.execute(query, (discord_id,vendor_name,vendor_name,))
    rows = cursor.fetchall()
    logging.debug(f"Visible messages retrieved for channel {discord_id} and vendor {vendor_name}.")
    return [row_to_dict(row) for row in rows]

def get_count_recent_image_requests(discord_id: int) -> int:
    """
    Gets the count of recent image requests for a given channel. This is used to enforce rate limits.

    Parameters:
    discord_id (int): The Discord ID of the channel to retrieve image requests for.

    Returns:
    int: The count of recent image requests.
    """
    logging.debug(f"Getting count of recent image requests for channel {discord_id}...")
    query = open('db/get_count_recent_image_requests.sql').read()
    cursor = db.execute(query, (discord_id,))
    row = cursor.fetchone()
    logging.debug(f"Count of recent image requests retrieved for channel {discord_id}.")
    return row['count'] if row else 0

def get_count_recent_text_requests(discord_id: int) -> int:
    """
    Gets the count of recent text requests for a given channel. This is used to enforce rate limits.

    Parameters:
    discord_id (int): The Discord ID of the channel to retrieve text requests for.

    Returns:
    int: The count of recent text requests.
    """
    logging.debug(f"Getting count of recent text requests for channel {discord_id}...")
    query = open('db/get_count_recent_text_requests.sql').read()
    cursor = db.execute(query, (discord_id,))
    row = cursor.fetchone()
    logging.debug(f"Count of recent text requests retrieved for channel {discord_id}.")
    return row['count'] if row else 0

def deactivate_old_messages(discord_id: int, vendor_name: str, window: int) -> None:
    """
    Sets all messages outside of the current window to inactive. This is used to prevent the AI from using outdated context.
    """
    logging.debug(f"Deactivating old messages for channel {discord_id} and vendor {vendor_name}...")
    query = open('db/deactivate_old_messages.sql').read()
    db.execute(query, (discord_id,vendor_name,vendor_name,window,))
    db.commit()
    logging.debug(f"Old messages deactivated for channel {discord_id} and vendor {vendor_name}.")


### LOGIC METHODS ###
def create_vendor(vendor_name: str, vendor_model_name: str) -> None:
    """
    Creates a vendor in the database if it does not already exist.

    Parameters:
    vendor_name (str): The name of the vendor to create.
    vendor_model_name (str): The name of the model to associate with the vendor.
    """
    logging.debug(f"Creating vendor {vendor_name}...")
    if not get_vendor(vendor_name):
        add_vendor(vendor_name, vendor_model_name)
        logging.debug(f"Vendor {vendor_name} created.")
    else:
        logging.debug(f"Vendor {vendor_name} was not created because it already exists")

def validate_vendors() -> None:
    """
    Checks the allowed_vendors.json file for vendors to create them in the database.
    """
    logging.debug(f"Validating vendors...")
    try:
        with open("allowed_vendors.json") as file:
            allowed_vendors = json.load(file)
        for vendor_name in allowed_vendors.keys():
            create_vendor(vendor_name, allowed_vendors[vendor_name]["model"])
    except FileNotFoundError:
        logging.error("allowed_vendors.json file not found.")
        raise ex
    except Exception as ex:
        logging.error(f"{ex}")
        raise ex

def create_channel(discord_id: int) -> None:
    """
    Creates a record of a Discord channel in the database if it does not already exist.

    Parameters:
    discord_id (int): The Discord ID of the channel to create.
    """
    logging.debug(f"Creating channel {discord_id}...")
    if not get_channel(discord_id):
        add_channel(discord_id)
        logging.debug(f"channel {discord_id} created.")
    else:
        logging.debug(f"channel {discord_id} was not created because it already exists")

def clear_messages(discord_id: int, vendor_name: str) -> None:
    """
    Clears all messages for a given channel and vendor. This is used to reset the bot's context.

    Parameters:
    discord_id (int): The Discord ID of the channel to clear messages for.
    vendor_name (str): The name of the vendor to clear messages for.
    """
    logging.debug(f"Clearing messages for channel {discord_id} and vendor {vendor_name}...")
    delete_channel_messages(discord_id, vendor_name)
    logging.debug(f"Messages cleared for channel {discord_id} and vendor {vendor_name}.")


### MISCELLANEOUS METHODS ###
async def enforce_text_rate_limits(channel_id: str) -> bool:
    """
    Enforce rate limits on text-based interactions to prevent abuse.

    Parameters:
    channel_id (str): The ID of the channel where the interaction occurred.

    Returns:
    bool: True if request is allowed, False if it exceeds the rate limit.
    """
    # Get a count of recent text requests made in this channel
    request_count = get_count_recent_text_requests(channel_id)
    rate_limit = int(getenv("ANTHROPIC_RATE_LIMIT"))

    # If the rate limit is exceeded, return an error message and signal to short-circuit the command
    if request_count < rate_limit:
        return True
    else:
        logging.warning(f"Text request rate limit exceeded for channel {channel_id}.")
        return False
    
async def enforce_image_rate_limits(channel_id: str) -> bool:
    """
    Enforce rate limits on image-based interactions to prevent abuse.

    Parameters:
    channel_id (str): The ID of the channel where the interaction occurred.

    Returns:
    bool: True if request is allowed, False if it exceeds the rate limit.
    """
    # Get a count of recent image requests made in this channel
    request_count = get_count_recent_image_requests(channel_id)
    rate_limit = int(getenv("FAL_RATE_LIMIT"))

    # If the rate limit is exceeded, return an error message and signal to short-circuit the command
    if request_count < rate_limit:
        return True
    else:
        logging.warning(f"Image request limit exceeded for channel {channel_id}.")
        return False