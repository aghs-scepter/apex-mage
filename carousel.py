import base64
import json
import io
import logging
from typing import List
from os import getenv
import discord
import ai
import mem

class ImageCarouselSelectionModal(discord.ui.Modal, title="Title Placeholder"):
    """
    A modal that accepts user instructions for manipulating an image selected in the carousel
    """
    instruction = discord.ui.TextInput(
        label="Prompt",
        placeholder="Add your instructions here...",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1000
    )

    def __init__(self, carousel_view: "ImageCarouselView"):
        """
        Initializes the modal with the carousel view that the instructions are for.

        Args:
            carousel_view (ImageCarouselView): The carousel view that the instructions are for.
        """
        self.carousel_view = carousel_view
        super().__init__(timeout=120)
    
    async def on_submit(self, interaction: discord.Interaction):
        """
        Stores the user's input
        """
        await interaction.response.defer() # Defer to create a "thinking" spinner and avoid timeout

        # Send temporary "thinking" message
        thinking_message = await interaction.followup.send(f"Prompt: {self.instruction.value}\n\nProcessing request. This may take up to 60 seconds...", wait=True)

        # Create the user slug for decorating the result embed
        embed_user = {
            "name": interaction.user.display_name,
            "pfp": interaction.user.avatar
        }

        # Store the user's selected image
        selected_image = self.carousel_view.get_current_file()

        # Check if channel is within or outside of prompt rate limits
        within_rate_limit = await mem.enforce_image_rate_limits(interaction.channel.id)

        if within_rate_limit:
            # Add the user's request as a message in the DB
            mem.create_channel(interaction.channel.id)
            str_image = json.dumps([{ "filename": "image.jpeg", "image": selected_image["image"] }])
            mem.add_message(interaction.channel.id, 'Fal.AI', 'prompt', False, self.instruction.value)
        
            # Get the AI response and record it in the database. For images, a placeholder is used in place of a message.
            response = await ai.modify_image(selected_image["image"], self.instruction.value)
            image_data = await ai.image_strip_headers(response["image"]["url"], "jpeg")
            image_data = await ai.compress_image(image_data) # Compress the image to reduce token count
            str_image = json.dumps([{ "filename": "image.jpeg", "image": image_data }])
            # Dear reader, I am so sorry for this. But Anthropic's API freaks the fuck out if you specify that a bot, rather than a user, uploaded an image as context.
            mem.add_message_with_images(interaction.channel.id, 'Fal.AI', "prompt", False, "Modified Image", str_image)
            
            # Format the image response as a Discord file object
            output_filename, output_file = await ai.format_image_response(image_data, "jpeg", response["has_nsfw_concepts"]) # Fal.AI returns jpeg-format image files
            
            # Update the deferred message with the prompt text and the image file attached
            embed = await ai.generate_embed(user=embed_user, prompt=self.instruction.value, response="Modified image", inline=False, filename=output_filename)

            await thinking_message.edit(
                content=None,
                attachments=[output_file],
                embed=embed
            )
        else:
            # If the channel is outside of the rate limit, tell users to chill tf out
            error = f"You're requesting too many images and have been rate-limited. The bot can handle a maximum of {getenv('FAL_RATE_LIMIT')} `/create_image` requests per hour. Please wait a few minutes before sending more requests."
            embed = await ai.generate_embed(user=embed_user, prompt=self.instruction.value, response="Error", error=error, inline=False)
            await thinking_message.edit(
                content=None,
                embed=embed
            )

class ImageCarouselView(discord.ui.View):
    """
    A view that provides a simple image carousel.
    """
    def __init__(self, interaction: discord.Interaction, files: List[discord.File], user=None):
        """
        Initializes the carousel with a list of image file data.
        If no files are provided, the carousel is "not healthy" and will display an error message.

        Args:
            files (List[discord.File]): A list of image files.
        """
        super().__init__(timeout=60.0) # The carousel times out after 60 seconds of inactivity.
        # Metadata about user, used for display at top of embed
        self.username, self.pfp = self.get_user_info(user)
        # Embed object, image list, current image, and current index for the carousel
        self.embed = None
        self.files = files
        self.embed_image = None
        self.current_index = 0
        self.healthy = False # Default to unhealthy so weird states don't try to render as embeds
        
        # If images are provided, default to showing the first in the list when initialized
        if self.files:
            # Setting initial carousel position and button state
            self.healthy = True

    async def initialize(self, interaction: discord.Interaction):
        """
        Initializes the image carousel view.
        """
        if not self.healthy:
            # Create an error embed if the carousel is labeled as unhealthy after init
            self.embed, self.embed_image = await self.create_error_embed(interaction, "ERROR: There are no images in context. Add or generate an image to use this feature.")
            self.hide_buttons()
            logging.error("No files provided to ImageCarouselView at startup; Error embed created.")
        
        else:
            # Create embed with first image in list as default
            self.embed, self.embed_image = await self.create_embed(interaction)
            self.update_buttons()
            logging.debug("ImageCarouselView embed created successfully.")

        # Add the embed to the message
        if self.embed_image:
            await interaction.followup.send(
                file=self.embed_image,
                embed=self.embed,
                view=self,
                wait=True # Wait for the message to successfully send before continuing
            )
        else:
            await interaction.followup.send(
                embed=self.embed,
                view=self,
                wait=True
            )
        # Start the timeout tracker
        await self.start(interaction)
        logging.debug("ImageCarouselView initialized successfully.")

    def get_user_info(self, user):
        """
        Returns the username and avatar data of a user. If one wasn't provided, system defaults are used.

        Args:
            user (dict): The user dict to get information from.
        """
        if user:
            return user["name"], user["pfp"]
        else:
            return "System", "https://github.com/aghs-scepter/apex-mage/raw/main/assets/default_pfp.png"
    
    async def create_error_embed(self, interaction, error_message):
        """
        Sets the message embed to a basic text error message and disables + hides all buttons.
        """
        embed = discord.Embed(description=error_message)
        embed_image = None
        embed.set_author(name=f'{self.username} (via Apex Mage)', url="https://github.com/aghs-scepter/apex-mage", icon_url=self.pfp)

        return embed, embed_image

    def get_current_file(self) -> str:
        """
        Returns the image file data of the image currently shown on the carousel.
        """
        return self.files[self.current_index]
    
    def disable_buttons(self):
        """
        Disable all navigation and selection buttons.
        """
        self.previous_button.disabled = True
        self.next_button.disabled = True
        self.accept_button.disabled = True
        self.cancel_button.disabled = True
    
    def hide_buttons(self):
        """
        Remove all navigation and selection buttons.
        """
        self.clear_items()

    def update_buttons(self):
        """
        Update the state of the nav buttons to prevent out-of-bounds navigation.
        """
        self.previous_button.disabled = (self.current_index <= 0)
        self.next_button.disabled = (self.current_index >= len(self.files) - 1)

    async def on_timeout(self):
        """
        Disables all buttons when the view times out.
        """
        self.disable_buttons()
        self.hide_buttons()
        try:
            await self.message.edit(view=self)
        except:
            pass
    
    async def start(self, interaction: discord.Interaction): 
        """
        Starts the image carousel interaction to begin the timeout countdown.
        """
        self.message = await interaction.original_response()

    async def create_embed(self, interaction: discord.Interaction):
        """
        Create the initial carousel embed with the first image selected.

        Args:
            interaction (discord.Interaction): The interaction that triggered the embed creation.
        """
        embed_image = await create_file_from_image(self.files[self.current_index])

        embed = discord.Embed(description=f"Image {self.current_index + 1}/{len(self.files)}")
        embed.set_author(name=f'{self.username} (via Apex Mage)', url="https://github.com/aghs-scepter/apex-mage", icon_url=self.pfp)
        embed.set_image(url=f"attachment://{embed_image.filename}")

        return embed, embed_image

    async def disable_embed(self, interaction: discord.Interaction):
        """
        Disable further interaction with the embed and close the image selection.

        Args:
            interaction (discord.Interaction): The interaction that triggered the embed disable.
        """
        self.embed_image = await create_file_from_image(self.files[self.current_index])

        self.embed.description = "Image selection closed."
        self.embed.set_image(url=f"attachment://{self.embed_image.filename}")

        self.hide_buttons()
        await interaction.response.edit_message(
            attachments=[self.embed_image],
            embed=self.embed,
            view=self
        )

    async def update_embed(self, interaction: discord.Interaction):
        """
        Updates the embed with the current image and button states after a navigation action.

        Args:
            interaction (discord.Interaction): The interaction that triggered the navigation.
        """
        # Create a file from the newly selected image data
        self.embed_image = await create_file_from_image(self.files[self.current_index])

        # Update embed description and attachment URL
        self.embed.description = f"Image {self.current_index + 1}/{len(self.files)}"
        self.embed.set_image(url=f"attachment://{self.embed_image.filename}")
       
        # Update button states
        self.update_buttons()

        # Update the message with new image in the embed
        await interaction.response.edit_message(
            attachments=[self.embed_image],
            embed=self.embed,
            view=self
        )

    @discord.ui.button(label="<", style=discord.ButtonStyle.primary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        The "<", or previous, button that navigates to the previous image in the carousel.
        """
        if self.current_index > 0: # Does nothing at start of list
            self.current_index -= 1
            await self.update_embed(interaction)

    @discord.ui.button(label=">", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        The ">", or next, button that navigates to the next image in the carousel.
        """
        if self.current_index < len(self.files) - 1: # Does nothing at end of list
            self.current_index += 1
            await self.update_embed(interaction)
    
    @discord.ui.button(label="Select", style=discord.ButtonStyle.success)
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        Button to accept current image selection
        """
        # Hide buttons first without sending a response
        self.hide_buttons()

        # Update the embed description
        self.embed.description = f"{interaction.user.display_name} selected an image. Waiting for them to enter a prompt..."

        # Create the modal for follow-up input
        modal = ImageCarouselSelectionModal(self)
        await interaction.response.send_modal(modal)

        # Update the message separately to disable buttons
        await interaction.followup.edit_message(
            message_id=interaction.message.id,
            view=self
        )

    @discord.ui.button(label="X", style=discord.ButtonStyle.danger)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        Button to cancel image selection and disable further interaction with the embed
        """
        await self.disable_embed(interaction)

async def create_file_from_image(image_data: dict) -> discord.File:
        """
        Creates a discord.File object from an image.
        """
        # Create a file-like object from the image data
        file_data = io.BytesIO(base64.b64decode(image_data["image"]))
        file_data.seek(0)
        
        # Create a discord.File object
        return discord.File(file_data, filename=image_data["filename"], spoiler=False)