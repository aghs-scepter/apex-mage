"""Tests for GCS adapter."""

from unittest.mock import MagicMock, patch

import pytest

from src.adapters.gcs_adapter import GCSAdapter, GCSUploadError


class TestGCSUploadError:
    """Tests for GCSUploadError exception."""

    def test_stores_attributes(self):
        """Should store all provided attributes."""
        original = ValueError("test error")
        error = GCSUploadError(
            message="Upload failed",
            message_type="response",
            channel_id=12345,
            original_error=original,
        )
        assert str(error) == "Upload failed"
        assert error.message_type == "response"
        assert error.channel_id == 12345
        assert error.original_error is original

    def test_optional_original_error(self):
        """Should allow None for original_error."""
        error = GCSUploadError(
            message="Upload failed",
            message_type="response",
            channel_id=12345,
        )
        assert error.original_error is None


class TestGCSAdapter:
    """Tests for GCSAdapter class."""

    @pytest.fixture
    def mock_storage_client(self):
        """Create a mock storage client."""
        with patch("src.adapters.gcs_adapter.storage.Client") as mock_client:
            mock_blob = MagicMock()
            mock_blob.public_url = "https://storage.googleapis.com/test-bucket/test-blob"

            mock_bucket = MagicMock()
            mock_bucket.blob.return_value = mock_blob

            mock_instance = MagicMock()
            mock_instance.bucket.return_value = mock_bucket

            mock_client.return_value = mock_instance
            yield {
                "client_class": mock_client,
                "client": mock_instance,
                "bucket": mock_bucket,
                "blob": mock_blob,
            }

    def test_init_with_default_bucket(self):
        """Should use default bucket name."""
        adapter = GCSAdapter()
        assert adapter._bucket_name == "apex-mage-data"

    def test_init_with_custom_bucket(self):
        """Should accept custom bucket name."""
        adapter = GCSAdapter(bucket_name="custom-bucket")
        assert adapter._bucket_name == "custom-bucket"

    def test_lazy_client_initialization(self, mock_storage_client):
        """Client should not be created until needed."""
        adapter = GCSAdapter()
        assert adapter._client is None
        mock_storage_client["client_class"].assert_not_called()

    def test_upload_text_returns_url(self, mock_storage_client):
        """Should return public URL after successful upload."""
        adapter = GCSAdapter(bucket_name="test-bucket")
        url = adapter.upload_text(
            message_type="response",
            channel_id=12345,
            content="# Test Content",
        )
        assert url == "https://storage.googleapis.com/test-bucket/test-blob"

    def test_upload_text_creates_correct_blob_path(self, mock_storage_client):
        """Should create blob with correct path pattern."""
        adapter = GCSAdapter(bucket_name="test-bucket")
        adapter.upload_text(
            message_type="response",
            channel_id=12345,
            content="# Test Content",
        )

        mock_storage_client["bucket"].blob.assert_called_once()
        blob_path = mock_storage_client["bucket"].blob.call_args[0][0]
        assert blob_path.startswith("overflow_responses/12345/")
        assert blob_path.endswith("/response.md")

    def test_upload_text_sets_content_type(self, mock_storage_client):
        """Should set content type to text/markdown."""
        adapter = GCSAdapter()
        adapter.upload_text(
            message_type="prompt",
            channel_id=99999,
            content="Test",
        )

        mock_storage_client["blob"].upload_from_string.assert_called_once_with(
            "Test", content_type="text/markdown"
        )

    def test_upload_text_uses_correct_bucket(self, mock_storage_client):
        """Should use configured bucket name."""
        adapter = GCSAdapter(bucket_name="my-special-bucket")
        adapter.upload_text(
            message_type="response",
            channel_id=1,
            content="Test",
        )

        mock_storage_client["client"].bucket.assert_called_with("my-special-bucket")

    def test_upload_text_raises_on_error(self, mock_storage_client):
        """Should raise GCSUploadError on failure."""
        mock_storage_client["blob"].upload_from_string.side_effect = Exception(
            "Network error"
        )

        adapter = GCSAdapter()
        with pytest.raises(GCSUploadError) as exc_info:
            adapter.upload_text(
                message_type="response",
                channel_id=12345,
                content="Test",
            )

        assert exc_info.value.message_type == "response"
        assert exc_info.value.channel_id == 12345
        assert exc_info.value.original_error is not None

    def test_client_reused_across_calls(self, mock_storage_client):
        """Should reuse client instance across multiple uploads."""
        adapter = GCSAdapter()
        adapter.upload_text("response", 1, "Test 1")
        adapter.upload_text("response", 2, "Test 2")

        # Client should only be created once
        mock_storage_client["client_class"].assert_called_once()

    def test_upload_different_message_types(self, mock_storage_client):
        """Should handle different message types in path."""
        adapter = GCSAdapter()

        adapter.upload_text("prompt", 1, "Test")
        prompt_path = mock_storage_client["bucket"].blob.call_args_list[0][0][0]
        assert "overflow_prompts/" in prompt_path

        adapter.upload_text("response", 1, "Test")
        response_path = mock_storage_client["bucket"].blob.call_args_list[1][0][0]
        assert "overflow_responses/" in response_path
