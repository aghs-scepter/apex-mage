import base64
import json
import io
import logging
from typing import List, Callable, Coroutine, Any
from os import getenv
import discord
import ai
import mem

embed_color_error = 0xE91515
embed_color_info = 0x3498DB

def get_user_info(user: dict):
    """
    Returns the username and avatar data of a user. If one wasn't provided, system defaults are used.

    Args:
        user (dict): The user dict to get information from.
    """
    if user:
        return user["name"], user["id"], user["pfp"]
    else:
        return "System", 0, "https://github.com/aghs-scepter/apex-mage/raw/main/assets/default_pfp.png"
 
class InfoEmbedView(discord.ui.View):
    """
    A simple view that displays an informational or error message in an embed.
    """
    def __init__(self, message=None, user=None, title: str = "Default Title", description: str = None, is_error: bool = False, image_data: dict = None, notes: List[dict] = None, full_response_url = None, full_prompt_url = None):
        super().__init__()
        self.user = user
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.title = title
        self.message = message
        self.description = description
        self.is_error = is_error
        self.image_data = image_data
        self.notes = notes
        self.full_response_url = full_response_url
        self.full_prompt_url = full_prompt_url
        self.embed = None

    async def initialize(self, interaction: discord.Interaction):
        """
        Creates and displays the error embed.
        """
        self.embed = discord.Embed(
            title=self.title,
            color=embed_color_error if self.is_error else embed_color_info
        )
        self.embed.set_author(
            name=f'{self.username} (via Apex Mage)', 
            url="https://github.com/aghs-scepter/apex-mage", 
            icon_url=self.pfp
        )

        if self.description:
            self.embed.description = self.description

        if self.notes:
            for note in self.notes:
                self.embed.add_field(
                    name=note["name"],
                    value=note["value"],
                    inline=False
                )
        
        # Add view full response button if URL is provided
        if self.full_response_url:
            self.add_item(discord.ui.Button(
                label="View Full Response",
                url=self.full_response_url,
                style=discord.ButtonStyle.link
            ))
        
        # Add view full prompt button if URL is provided
        if self.full_prompt_url:
            self.add_item(discord.ui.Button(
                label="View Full Prompt",
                url=self.full_prompt_url,
                style=discord.ButtonStyle.link
            ))

        if self.image_data:
            embed_image = await create_file_from_image(self.image_data)
            self.embed.set_image(url=f"attachment://{embed_image.filename}")

            if interaction.original_response:
                await interaction.edit_original_response(
                    embed=self.embed,
                    attachments=[embed_image],
                    view=self
                )
            else:
                await interaction.followup.send(
                    embed=self.embed,
                    file=embed_image,
                    view=self
                )
        else:
            if interaction.original_response:
                await interaction.edit_original_response(
                    attachments=[],
                    embed=self.embed,
                    view=self
                )
            else:
                await interaction.followup.send(
                    embed=self.embed,
                    view=self
                )
        
        return

class UnauthorizedModal(discord.ui.Modal):
    def init(self):
        super().init(title="Not Allowed")

    async def on_submit(self, interaction):
        await interaction.response.defer()
        return

class ClearHistoryConfirmationView(discord.ui.View):
    def __init__(self, interaction: discord.Interaction, user=None, on_select: Callable[[discord.Interaction, bool], Coroutine[Any, Any, None]] = None):
        super().__init__(timeout=60.0)
        self.user = user
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.embed = None
        self.message = None
        self.on_select = on_select
    
    async def initialize(self, interaction: discord.Interaction):
        """
        Creates and displays the confirmation embed.
        """
        self.embed = discord.Embed(
            title="Clear history confirmation",
            description="Are you sure you want to clear the bot's history in this channel? All prior messages and images will be forgotten and you will not be able to access them.",
            color=embed_color_info
        )
        self.embed.set_author(
            name=f'{self.username} (via Apex Mage)', 
            url="https://github.com/aghs-scepter/apex-mage", 
            icon_url=self.pfp
        )

        self.message = await interaction.followup.send(
            embed=self.embed,
            view=self
        )
    
    # Define helpers for button management
    def disable_buttons(self):
        """Disables all buttons in the view."""
        for child in self.children:
            child.disabled = True

    def hide_buttons(self):
        """Removes all buttons from the view."""
        self.clear_items()

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.hide_buttons()
        await self.message.edit(
            embed=self.embed,
            view=self
        )
        if self.on_select:
            await self.on_select(interaction, self.user, True)

    @discord.ui.button(label="Never Mind", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.hide_buttons()
        await self.message.edit(
            embed=self.embed,
            view=self
        )
        if self.on_select:
            await self.on_select(interaction, self.user, False)

class ImageSelectionTypeView(discord.ui.View):
    """
    A view that provides a set of buttons specifying how a user wants to select an image for their request.
    """
    def __init__(self, interaction: discord.Interaction, user=None, on_select: Callable[[discord.Interaction, str], Coroutine[Any, Any, None]] = None):
        """
        Initializes the image selection type modal.

        Args:
            interaction (discord.Interaction): The interaction that triggered the modal.
        """
        super().__init__()
        self.user = user
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.embed = None
        self.message = None
        self.on_select = on_select # Callback function for when a selection is made
    
    async def initialize(self, interaction: discord.Interaction):
        """
        Initializes the image selection type modal.
        """
        # Create the embed for the modal
        self.embed = discord.Embed(title="Image Selection Type", description="Select an option to choose an image for your request.")
        self.embed.set_author(name=f'{self.username} (via Apex Mage)', url="https://github.com/aghs-scepter/apex-mage", icon_url=self.pfp)

        # Check if the user has a previous selection in context
        #has_previous_image = mem.get_user_latest_image_indicator(interaction.channel.id, "All Models", interaction.user.id)
        has_previous_image = False

        # Check if the channel has recent images
        has_recent_images = mem.get_channel_latest_image_indicator(interaction.channel.id, "All Models")

        # Update buttons to reflect which options are available to the user
        self.update_buttons(has_previous_image, has_recent_images)
        logging.debug("ImageSelectionTypeModal embed created successfully.")

        self.message = await interaction.followup.send(
            embed=self.embed,
            view=self,
            wait=True
        )

        # Start the timeout tracker
        logging.debug("ImageSelectionTypeModal initialized successfully.")
        return
    
    def update_buttons(self, has_previous_image: bool, has_recent_images: bool):
        """
        Update the state of the nav buttons to prevent out-of-bounds navigation.
        """
        self.last_image_button.disabled = not has_previous_image
        self.recent_images_button.disabled = not has_recent_images
    
    def disable_buttons(self):
        """
        Disable all selection buttons.
        """
        self.last_image_button.disabled = True
        self.recent_images_button.disabled = True
        self.cancel_button.disabled = True
    
    def hide_buttons(self):
        """
        Remove all selection buttons.
        """
        self.clear_items()
    
    async def disable_embed(self, interaction: discord.Interaction):
        """
        Disable further interaction with the embed and close the image selection.

        Args:
            interaction (discord.Interaction): The interaction that triggered the embed disable.
        """
        self.embed.description = f"Command cancelled by {self.username}."

        self.hide_buttons()
        await interaction.response.edit_message(
            embed=self.embed,
            view=self
        )

    @discord.ui.button(label="Google (disabled)", style=discord.ButtonStyle.primary, disabled=True)
    async def last_image_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        Indicates the user wants to use their most recently selected or uploaded image.
        """
        if self.user_id != interaction.user.id:
            modal = UnauthorizedModal()
            modal.init()
            await interaction.response.send_message(f"Only the original requester ({self.username}) can select this option.", ephemeral=True)
            return
        else:
            # Make a callback to the parent view to handle the image selection
            if self.on_select:
                self.hide_buttons()
                await self.on_select(interaction, "My Last Image")
    
    @discord.ui.button(label="Recent Images", style=discord.ButtonStyle.primary)
    async def recent_images_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        Indicates the user wants to select a recent image from a carousel.
        """
        if self.user_id != interaction.user.id:
            modal = UnauthorizedModal()
            modal.init()
            await interaction.response.send_message(f"Only the original requester ({self.username}) can select this option.", ephemeral=True)
            return
        
        else:
            # Make a callback to the parent view to handle the image selection
            if self.on_select:
                self.hide_buttons()
                await self.on_select(interaction, "Recent Images")
    
    @discord.ui.button(label="X", style=discord.ButtonStyle.danger)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        Button to cancel selection and disable further interaction with the embed
        """
        if self.user_id != interaction.user.id:
            modal = UnauthorizedModal()
            modal.init()
            await interaction.response.send_message(f"Only the original requester ({self.username}) can select this option.", ephemeral=True)
            return
        else:
            # Make a callback to the parent view to handle the image selection
            if self.on_select:
                self.hide_buttons()
                await self.message.edit(view=self)
                await self.on_select(interaction, "Cancel")

class ImageCarouselView(discord.ui.View):
    """
    A view that provides a simple image carousel.
    """
    def __init__(self, interaction: discord.Interaction, files: List[discord.File], user=None, message=None, on_select: Callable[[discord.Interaction, dict], Coroutine[Any, Any, None]] = None):
        """
        Initializes the carousel with a list of image file data.
        If no files are provided, the carousel is "not healthy" and will display an error message.

        Args:
            files (List[discord.File]): A list of image files.
        """
        super().__init__() # The carousel times out after 60 seconds of inactivity.
        # Metadata about user, used for display at top of embed
        self.user = user
        self.username, self.user_id, self.pfp = get_user_info(user)
        # Embed object, image list, current image, and current index for the carousel
        self.embed = None
        self.files = files
        self.embed_image = None
        self.current_index = (len(self.files) - 1) if self.files else 0 # start at the end (latest) image
        self.on_select = on_select
        self.message = message
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
            await self.message.edit(
                attachments=[self.embed_image],
                embed=self.embed,
                view=self
            )
        else:
            await self.message.edit(
                embed=self.embed,
                view=self
            )
        logging.debug("ImageCarouselView initialized successfully.")
    
    def generate_image_chrono_bar(self, current_index: int, total: int) -> str:
        """
        Generate a visual description for an image's relative position in context of the carousel
        """
        bar_icons = ""
        for i in range(0, total):
            if i == current_index:
                bar_icons += "⬥"
            else:
                bar_icons += "⬦"
        
        return f"(Oldest) {bar_icons} (Newest)"
    
    async def create_error_embed(self, interaction, error_message):
        """
        Sets the message embed to a basic text error message and disables + hides all buttons.
        """
        embed = discord.Embed(title="Error Message",description=error_message)
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
        for child in self.children:
            child.disabled = True
    
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

    async def create_embed(self, interaction: discord.Interaction):
        """
        Create the initial carousel embed with the first image selected.

        Args:
            interaction (discord.Interaction): The interaction that triggered the embed creation.
        """
        embed_image = await create_file_from_image(self.files[self.current_index])

        embed = discord.Embed(title="Select an Image",description=self.generate_image_chrono_bar(self.current_index, len(self.files)))
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
        await self.message.edit(
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
        self.embed.description = self.generate_image_chrono_bar(self.current_index, len(self.files))
        self.embed.set_image(url=f"attachment://{self.embed_image.filename}")
       
        # Update button states
        self.update_buttons()

        # Update the message with new image in the embed
        await self.message.edit(
            attachments=[self.embed_image],
            embed=self.embed,
            view=self
        )

    @discord.ui.button(label="<", style=discord.ButtonStyle.primary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        The "<", or previous, button that navigates to the previous image in the carousel.
        """
        # Add defer to acknowledge the interaction
        await interaction.response.defer()

        if self.current_index > 0: # Does nothing at start of list
            self.current_index -= 1
            await self.update_embed(interaction)

    @discord.ui.button(label=">", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        The ">", or next, button that navigates to the next image in the carousel.
        """
        # Add defer to acknowledge the interaction
        await interaction.response.defer()

        if self.current_index < len(self.files) - 1: # Does nothing at end of list
            self.current_index += 1
            await self.update_embed(interaction)
    
    @discord.ui.button(label="Select", style=discord.ButtonStyle.success)
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        Button to accept current image selection
        """
        selected_image = self.get_current_file()
        if self.on_select:
            self.disable_buttons()
            await self.on_select(interaction, selected_image)

    @discord.ui.button(label="X", style=discord.ButtonStyle.danger)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        Button to cancel image selection and disable further interaction with the embed
        """
        #await self.disable_embed(interaction)
        if self.on_select:
            self.hide_buttons()
            await self.message.edit(view=self)
            await self.on_select(interaction, None)

class ImageEditTypeView(discord.ui.View):
    """
    A view that displays buttons for different image editing options.
    """
    def __init__(self, image_data: dict, user: dict = None, message: discord.Message = None, on_select: Callable[[discord.Interaction, str, str], Coroutine[Any, Any, None]] = None):
        super().__init__()
        self.image_data = image_data
        self.user = user
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.embed = None
        self.message = message
        self.on_select = on_select
        logging.debug("ImageEditTypeView initialized")

    async def initialize(self, interaction: discord.Interaction):
        """
        Initializes the view with the image and buttons.
        """
        self.embed = discord.Embed(title="Edit Image", description="Select an editing option:")
        self.embed.set_author(name=f'{self.username} (via Apex Mage)', url="https://github.com/aghs-scepter/apex-mage", icon_url=self.pfp)
        
        embed_image = await create_file_from_image(self.image_data)
        self.embed.set_image(url=f"attachment://{embed_image.filename}")
        
        await self.message.edit(
            embed=self.embed,
            attachments=[embed_image],
            view=self
        )
        logging.debug("ImageEditTypeView embed created and displayed")

    def disable_buttons(self):
        """
        Disables all buttons in the view.
        """
        for child in self.children:
            child.disabled = True
        logging.debug("All buttons disabled")

    def hide_buttons(self):
        """
        Removes all buttons from the view.
        """
        self.clear_items()
        logging.debug("All buttons hidden")

    @discord.ui.button(label="Adjust", style=discord.ButtonStyle.primary, row=0)
    async def adjust_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.on_select:
            if self.user_id != interaction.user.id:
                await interaction.response.send_message(
                    f"Only the original requester ({self.username}) can select this option.", 
                    ephemeral=True
                )
                return


            self.disable_buttons()
            self.hide_buttons()
            await self.message.edit(view=self)

            # Create prompt modal with retry functionality
            prompt_modal = ImageEditPromptModal(
                image_data=self.image_data,
                edit_type="Adjust",
                user=self.user, 
                message=self.message,
                on_select=self.on_select
            )
            await interaction.response.send_modal(prompt_modal)

    @discord.ui.button(label="Redraw", style=discord.ButtonStyle.primary, row=0)
    async def redraw_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.on_select:
            if self.user_id != interaction.user.id:
                await interaction.response.send_message(
                    f"Only the original requester ({self.username}) can select this option.", 
                    ephemeral=True
                )
                return


            self.disable_buttons()
            self.hide_buttons()
            await self.message.edit(view=self)

            # Create prompt modal with retry functionality
            prompt_modal = ImageEditPromptModal(
                image_data=self.image_data,
                edit_type="Redraw",
                user=self.user, 
                message=self.message,
                on_select=self.on_select
            )
            await interaction.response.send_modal(prompt_modal)

    @discord.ui.button(label="Random (disabled)", style=discord.ButtonStyle.secondary, disabled=True, row=0)
    async def random_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.on_select:
            if self.user_id != interaction.user.id:
                await interaction.response.send_message(
                    f"Only the original requester ({self.username}) can select this option.", 
                    ephemeral=True
                )
                return


            self.disable_buttons()
            self.hide_buttons()
            await self.message.edit(view=self)

            # Create prompt modal with retry functionality
            prompt_modal = ImageEditPromptModal(
                image_data=self.image_data,
                edit_type="Random",
                user=self.user, 
                message=self.message,
                on_select=self.on_select
            )
            await interaction.response.send_modal(prompt_modal)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, row=0)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.on_select:
            if self.user_id != interaction.user.id:
                await interaction.response.send_message(
                    f"Only the original requester ({self.username}) can select this option.", 
                    ephemeral=True
                )
                return


            self.disable_buttons()
            self.hide_buttons()
            await self.message.edit(view=self)
            await self.on_select(interaction, "Cancel", "")

class ImageEditPromptModal(discord.ui.Modal, title="Image Edit Instructions"):
    def __init__(self, image_data: dict, edit_type: str, user: dict, message: discord.Message, initial_text: str = "", on_select: Callable[[discord.Interaction, str, str], Coroutine[Any, Any, None]] = None):
        super().__init__()
        self.image_data = image_data
        self.edit_type = edit_type
        self.user = user
        self.message = message
        self.on_select = on_select

        self.prompt = discord.ui.TextInput(
            label="Enter your prompt:",
            style=discord.TextStyle.paragraph,
            placeholder="Describe how you want to modify this image. NOTE: Closing this window will cancel your edit request.",
            required=True,
            max_length=1000,
            default=initial_text
        )
        self.add_item(self.prompt)
    
    async def on_submit(self, interaction: discord.Interaction):
        if self.on_select:
            await self.on_select(interaction, self.edit_type, self.prompt.value)
            
    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        # Log the error
        logging.error(f"Error in ImageEditPromptModal: {str(error)}")
        
        try:
            # Send an error message to the user
            await interaction.response.send_message(
                "An error occurred while processing your request. Please try again.",
                ephemeral=True
            )
        except discord.errors.InteractionResponded:
            # If interaction was already responded to, use followup
            await interaction.followup.send(
                "An error occurred while processing your request. Please try again.",
                ephemeral=True
            )

class ImageEditPerformView(discord.ui.View):
    """
    A view that handles the business logic of performing an image edit operation.
    """
    def __init__(self, interaction: discord.Interaction, message: discord.Message, user: dict, image_data: dict, edit_type: str, prompt: str = "`placeholder`", on_complete: Callable[[discord.Interaction, dict], Coroutine[Any, Any, None]] = None):
        super().__init__()
        self.interaction = interaction
        self.prompt = prompt
        self.message = message
        self.user = user
        self.image_data = image_data
        self.edit_type = edit_type
        self.on_complete = on_complete
        self.username, self.user_id, self.pfp = get_user_info(user)
        self.embed = None

    async def initialize(self, interaction: discord.Interaction):
        """
        Creates and displays the initial "processing" embed.
        """
        await self.perform_edit(self.prompt)

    async def on_timeout(self):
        """
        Updates the embed with a timeout message if the operation takes too long.
        """
        self.embed.title = "Edit Timed Out"
        self.embed.description = "The image edit operation timed out. Please try again."
        self.embed.color = embed_color_error

        try:
            await self.message.edit(
                attachments=[],
                embed=self.embed,
                view=None
            )
        except:
            pass

    async def perform_edit(self, prompt: str):
        """
        Performs the actual image modification using the AI service.
        """
        try:
            # Check rate limits
            within_rate_limit = await mem.enforce_image_rate_limits(self.interaction.channel.id)
            
            if not within_rate_limit:
                error_data = {
                    "error": True,
                    "message": f"Rate limit exceeded. Please wait before requesting more image edits."
                }
                if self.on_complete:
                    await self.on_complete(self.interaction, error_data)
                return
            
            guidance_scale = 0.0
            if self.edit_type == "Adjust":
                guidance_scale = 10.0
            elif self.edit_type == "Redraw":
                guidance_scale = 1.5

            # Perform the image modification
            response = await ai.modify_image(self.image_data["image"], prompt, guidance_scale=guidance_scale)

            # Process the response
            image_data = await ai.image_strip_headers(response["image"]["url"], "jpeg")
            image_data = await ai.compress_image(image_data)
            image_return = { "filename": "image.jpeg", "image": image_data }

            # Call completion callback
            if self.on_complete:
                await self.on_complete(self.interaction, image_return)

        except Exception as ex:
            logging.error(f"Error in image edit: {str(ex)}")
            error_data = {
                "error": True,
                "message": f"An error occurred while modifying the image: {str(ex)}"
            }
            if self.on_complete:
                await self.on_complete(self.interaction, error_data)

async def create_file_from_image(image_data: dict) -> discord.File:
        """
        Creates a discord.File object from an image.
        """
        # Create a file-like object from the image data
        file_data = io.BytesIO(base64.b64decode(image_data["image"]))
        file_data.seek(0)
        
        # Create a discord.File object
        return discord.File(file_data, filename=image_data["filename"], spoiler=False)