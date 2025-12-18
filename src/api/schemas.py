"""Pydantic schemas for API request/response validation.

This module defines the data models used for validating API requests
and serializing responses.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MessageCreate(BaseModel):
    """Schema for creating a new message in a conversation."""

    content: str = Field(..., min_length=1, max_length=10000)
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"content": "Hello, can you help me with a coding question?"}
        }
    )


class MessageResponse(BaseModel):
    """Schema for a message in a conversation."""

    id: int
    role: str = Field(..., description="'user' or 'assistant'")
    content: str
    created_at: datetime | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": 1,
                "role": "assistant",
                "content": "Of course! I'd be happy to help with your coding question.",
                "created_at": "2025-01-01T12:00:00Z",
            }
        }
    )


class ConversationCreate(BaseModel):
    """Schema for creating a new conversation."""

    initial_message: str | None = Field(
        None,
        min_length=1,
        max_length=10000,
        description="Optional initial message to start the conversation",
    )
    system_prompt: str | None = Field(
        None,
        max_length=10000,
        description="Optional system prompt to set AI behavior",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "initial_message": "Hello!",
                "system_prompt": "You are a helpful coding assistant.",
            }
        }
    )


class ConversationResponse(BaseModel):
    """Schema for a conversation."""

    id: int = Field(..., description="Unique conversation/channel ID")
    messages: list[MessageResponse] = Field(default_factory=list)
    created_at: datetime | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": 12345,
                "messages": [
                    {
                        "id": 1,
                        "role": "user",
                        "content": "Hello!",
                        "created_at": "2025-01-01T12:00:00Z",
                    },
                    {
                        "id": 2,
                        "role": "assistant",
                        "content": "Hi! How can I help you today?",
                        "created_at": "2025-01-01T12:00:01Z",
                    },
                ],
                "created_at": "2025-01-01T12:00:00Z",
            }
        }
    )


class ChatCompletionRequest(BaseModel):
    """Schema for sending a message and getting a response."""

    content: str = Field(..., min_length=1, max_length=10000)

    model_config = ConfigDict(
        json_schema_extra={"example": {"content": "What is Python?"}}
    )


class ChatCompletionResponse(BaseModel):
    """Schema for AI chat completion response."""

    user_message: MessageResponse
    assistant_message: MessageResponse

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_message": {
                    "id": 1,
                    "role": "user",
                    "content": "What is Python?",
                    "created_at": "2025-01-01T12:00:00Z",
                },
                "assistant_message": {
                    "id": 2,
                    "role": "assistant",
                    "content": "Python is a high-level programming language...",
                    "created_at": "2025-01-01T12:00:01Z",
                },
            }
        }
    )


class ErrorResponse(BaseModel):
    """Schema for error responses."""

    error: str
    detail: str | None = None
    code: str | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "error": "Rate limit exceeded",
                "detail": "You have exceeded the maximum number of requests per hour.",
                "code": "RATE_LIMIT_EXCEEDED",
            }
        }
    )
