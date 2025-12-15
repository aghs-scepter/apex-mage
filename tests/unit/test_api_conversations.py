"""Tests for the conversation API routes."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes.conversations import router
from src.api.schemas import ChatCompletionRequest, ConversationCreate
from src.core.providers import ChatResponse
from src.core.rate_limit import RateLimitResult


@pytest.fixture
def mock_repo():
    """Create a mock repository adapter."""
    repo = AsyncMock()
    repo.create_channel = AsyncMock()
    repo.add_message = AsyncMock()
    repo.get_visible_messages = AsyncMock(return_value=[])
    repo.deactivate_all_messages = AsyncMock()
    return repo


@pytest.fixture
def mock_ai_provider():
    """Create a mock AI provider."""
    provider = AsyncMock()
    provider.chat = AsyncMock(
        return_value=ChatResponse(
            content="Hello! How can I help you?",
            model="claude-3-sonnet-20240229",
        )
    )
    return provider


@pytest.fixture
def mock_rate_limiter():
    """Create a mock rate limiter."""
    limiter = AsyncMock()
    limiter.check = AsyncMock(
        return_value=RateLimitResult(
            allowed=True,
            remaining=29,
            reset_at=datetime.now(timezone.utc),
            wait_seconds=None,
        )
    )
    limiter.record = AsyncMock()
    return limiter


@pytest.fixture
def app(mock_repo, mock_ai_provider, mock_rate_limiter):
    """Create a test FastAPI app with mocked dependencies."""
    from src.api.dependencies import get_ai_provider, get_rate_limiter, get_repository

    app = FastAPI()
    app.include_router(router)

    # Override dependencies
    app.dependency_overrides[get_repository] = lambda: mock_repo
    app.dependency_overrides[get_ai_provider] = lambda: mock_ai_provider
    app.dependency_overrides[get_rate_limiter] = lambda: mock_rate_limiter

    return app


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app)


class TestCreateConversation:
    """Tests for POST /conversations."""

    def test_creates_empty_conversation(self, client, mock_repo):
        """Should create conversation without initial message."""
        response = client.post("/conversations", json={})

        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert data["messages"] == []

        mock_repo.create_channel.assert_called_once()

    def test_creates_conversation_with_initial_message(
        self, client, mock_repo, mock_ai_provider, mock_rate_limiter
    ):
        """Should create conversation with initial message and get AI response."""
        response = client.post(
            "/conversations", json={"initial_message": "Hello!"}
        )

        assert response.status_code == 201
        data = response.json()
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][0]["content"] == "Hello!"
        assert data["messages"][1]["role"] == "assistant"

        mock_ai_provider.chat.assert_called_once()
        mock_rate_limiter.record.assert_called_once()

    def test_creates_conversation_with_system_prompt(
        self, client, mock_repo
    ):
        """Should create conversation with system prompt."""
        response = client.post(
            "/conversations",
            json={"system_prompt": "You are a helpful assistant."},
        )

        assert response.status_code == 201

        # Check that behavior message was added
        calls = mock_repo.add_message.call_args_list
        assert any(call[0][2] == "behavior" for call in calls)

    def test_rate_limit_exceeded(self, client, mock_rate_limiter):
        """Should return 429 when rate limited."""
        mock_rate_limiter.check.return_value = RateLimitResult(
            allowed=False,
            remaining=0,
            reset_at=datetime.now(timezone.utc),
            wait_seconds=60.0,
        )

        response = client.post(
            "/conversations", json={"initial_message": "Hello!"}
        )

        assert response.status_code == 429


class TestGetConversation:
    """Tests for GET /conversations/{id}."""

    def test_gets_empty_conversation(self, client, mock_repo):
        """Should return empty conversation when no messages."""
        mock_repo.get_visible_messages.return_value = []

        response = client.get("/conversations/123")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 123
        assert data["messages"] == []

    def test_gets_conversation_with_messages(self, client, mock_repo):
        """Should return conversation with messages."""
        mock_repo.get_visible_messages.return_value = [
            {"message_type": "prompt", "message_data": "Hello"},
            {"message_type": "assistant", "message_data": "Hi there!"},
        ]

        response = client.get("/conversations/123")

        assert response.status_code == 200
        data = response.json()
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][0]["content"] == "Hello"
        assert data["messages"][1]["role"] == "assistant"

    def test_excludes_behavior_messages(self, client, mock_repo):
        """Should not include behavior messages in response."""
        mock_repo.get_visible_messages.return_value = [
            {"message_type": "behavior", "message_data": "Be helpful"},
            {"message_type": "prompt", "message_data": "Hello"},
        ]

        response = client.get("/conversations/123")

        assert response.status_code == 200
        data = response.json()
        assert len(data["messages"]) == 1
        assert data["messages"][0]["role"] == "user"


class TestSendMessage:
    """Tests for POST /conversations/{id}/messages."""

    def test_sends_message_and_gets_response(
        self, client, mock_repo, mock_ai_provider, mock_rate_limiter
    ):
        """Should send message and return AI response."""
        mock_repo.get_visible_messages.return_value = [
            {"message_type": "prompt", "message_data": "Hello"},
        ]

        response = client.post(
            "/conversations/123/messages", json={"content": "What is Python?"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["user_message"]["content"] == "What is Python?"
        assert data["user_message"]["role"] == "user"
        assert data["assistant_message"]["role"] == "assistant"

        mock_ai_provider.chat.assert_called_once()
        mock_rate_limiter.record.assert_called_once()

    def test_rate_limit_exceeded(self, client, mock_rate_limiter):
        """Should return 429 when rate limited."""
        mock_rate_limiter.check.return_value = RateLimitResult(
            allowed=False,
            remaining=0,
            reset_at=datetime.now(timezone.utc),
            wait_seconds=60.0,
        )

        response = client.post(
            "/conversations/123/messages", json={"content": "Hello"}
        )

        assert response.status_code == 429

    def test_creates_channel_if_not_exists(self, client, mock_repo):
        """Should create channel if it doesn't exist."""
        response = client.post(
            "/conversations/456/messages", json={"content": "Hello"}
        )

        assert response.status_code == 200
        mock_repo.create_channel.assert_called_once_with(456)


class TestClearConversation:
    """Tests for DELETE /conversations/{id}."""

    def test_clears_conversation(self, client, mock_repo):
        """Should deactivate all messages."""
        response = client.delete("/conversations/123")

        assert response.status_code == 204
        mock_repo.deactivate_all_messages.assert_called_once_with(123)


class TestSchemas:
    """Tests for Pydantic schemas."""

    def test_message_create_validation(self):
        """Should validate message content."""
        from src.api.schemas import MessageCreate

        # Valid
        msg = MessageCreate(content="Hello")
        assert msg.content == "Hello"

        # Empty content should fail
        with pytest.raises(ValueError):
            MessageCreate(content="")

    def test_conversation_create_optional_fields(self):
        """Should allow optional fields."""
        conv = ConversationCreate()
        assert conv.initial_message is None
        assert conv.system_prompt is None

        conv = ConversationCreate(
            initial_message="Hi", system_prompt="Be helpful"
        )
        assert conv.initial_message == "Hi"
        assert conv.system_prompt == "Be helpful"

    def test_chat_completion_request_validation(self):
        """Should validate chat content."""
        req = ChatCompletionRequest(content="Hello")
        assert req.content == "Hello"

        with pytest.raises(ValueError):
            ChatCompletionRequest(content="")
