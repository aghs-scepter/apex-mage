"""Google Cloud Storage adapter for uploading content.

This module provides a GCSAdapter class for uploading text content to
Google Cloud Storage, returning public URLs for the uploaded files.
"""

import logging
from uuid import uuid4

from google.cloud import storage

logger = logging.getLogger(__name__)


class GCSUploadError(Exception):
    """Exception raised when a GCS upload operation fails.

    Attributes:
        message_type: The type of message being uploaded.
        channel_id: The channel ID associated with the upload.
        original_error: The underlying exception that caused the failure.
    """

    def __init__(
        self,
        message: str,
        message_type: str,
        channel_id: int,
        original_error: Exception | None = None,
    ) -> None:
        """Initialize a GCSUploadError.

        Args:
            message: Human-readable error message.
            message_type: The type of message being uploaded (e.g., "prompt", "response").
            channel_id: The channel ID associated with the upload.
            original_error: The underlying exception that caused the failure.
        """
        super().__init__(message)
        self.message_type = message_type
        self.channel_id = channel_id
        self.original_error = original_error


class GCSAdapter:
    """Adapter for uploading content to Google Cloud Storage.

    This class provides methods for uploading text content to GCS and
    returning public URLs. It wraps the google-cloud-storage client
    and provides proper error handling and logging.

    Example:
        adapter = GCSAdapter(bucket_name="my-bucket")
        url = adapter.upload_text(
            message_type="response",
            channel_id=12345,
            content="# Long Response\\nContent here..."
        )
        print(f"Uploaded to: {url}")
    """

    def __init__(self, bucket_name: str = "apex-mage-data") -> None:
        """Initialize the GCS adapter.

        Args:
            bucket_name: Name of the GCS bucket to upload to.
                Defaults to "apex-mage-data".
        """
        self._bucket_name = bucket_name
        self._client: storage.Client | None = None

    def _get_client(self) -> storage.Client:
        """Get or create the GCS client.

        Lazily initializes the client on first use.

        Returns:
            storage.Client: The GCS client instance.
        """
        if self._client is None:
            self._client = storage.Client()
        return self._client

    def upload_text(
        self,
        message_type: str,
        channel_id: int,
        content: str,
    ) -> str:
        """Upload text content to GCS and return the public URL.

        The content is uploaded as a markdown file with the following path pattern:
        overflow_{message_type}s/{channel_id}/{uuid}/response.md

        Args:
            message_type: Type of message (e.g., "prompt", "response").
                Used in the blob path as overflow_{message_type}s/.
            channel_id: The channel ID for organizing uploads.
            content: The text content to upload.

        Returns:
            str: The public URL of the uploaded file.

        Raises:
            GCSUploadError: If the upload fails for any reason.
        """
        logger.debug(
            "Uploading content to GCS",
            extra={
                "message_type": message_type,
                "channel_id": channel_id,
                "content_length": len(content),
            },
        )

        try:
            client = self._get_client()
            bucket = client.bucket(self._bucket_name)
            blob_path = f"overflow_{message_type}s/{channel_id}/{uuid4()}/response.md"
            blob = bucket.blob(blob_path)
            blob.upload_from_string(content, content_type="text/markdown")
            url = blob.public_url

            logger.debug(
                "Successfully uploaded content to GCS",
                extra={
                    "message_type": message_type,
                    "channel_id": channel_id,
                    "url": url,
                },
            )
            return url

        except Exception as ex:
            logger.error(
                "Failed to upload content to GCS",
                extra={
                    "message_type": message_type,
                    "channel_id": channel_id,
                    "error": str(ex),
                },
                exc_info=True,
            )
            raise GCSUploadError(
                message=f"Failed to upload {message_type} to GCS: {ex}",
                message_type=message_type,
                channel_id=channel_id,
                original_error=ex,
            ) from ex
