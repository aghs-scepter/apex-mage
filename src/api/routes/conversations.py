"""Conversation API routes.

These routes provide endpoints for managing conversations and messages.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from src.adapters import RepositoryAdapter
from src.api.auth import AuthUser, get_current_user
from src.api.dependencies import get_ai_provider, get_rate_limiter, get_repository
from src.api.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ConversationCreate,
    ConversationResponse,
    ErrorResponse,
    MessageResponse,
)
from src.core.logging import bind_contextvars, clear_contextvars, get_logger
from src.core.providers import AIProvider, ChatMessage
from src.core.rate_limit import SlidingWindowRateLimiter

logger = get_logger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _convert_context_to_messages(
    context: list[dict[str, Any]],
) -> tuple[list[ChatMessage], str | None]:
    """Convert database context to ChatMessage list and extract system prompt.

    Args:
        context: List of message dicts from the repository.

    Returns:
        Tuple of (chat_messages, system_prompt).
    """
    messages: list[ChatMessage] = []
    system_prompt: str | None = None

    # Find the most recent behavior message (system prompt)
    for row in reversed(context):
        if row["message_type"] == "behavior":
            system_prompt = row["message_data"]
            break

    # Convert non-behavior messages to ChatMessages
    for row in context:
        msg_type = row["message_type"]
        if msg_type == "behavior":
            continue

        if msg_type == "prompt":
            role = "user"
        elif msg_type == "assistant":
            role = "assistant"
        else:
            continue

        messages.append(ChatMessage(role=role, content=row["message_data"]))

    return messages, system_prompt


@router.post(
    "",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Conversation created successfully"},
        401: {"model": ErrorResponse, "description": "Authentication required"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
    },
)
async def create_conversation(
    request: ConversationCreate,
    user: AuthUser = Depends(get_current_user),
    repo: RepositoryAdapter = Depends(get_repository),
    ai_provider: AIProvider = Depends(get_ai_provider),
    rate_limiter: SlidingWindowRateLimiter = Depends(get_rate_limiter),
) -> ConversationResponse:
    """Create a new conversation.

    Optionally include an initial message and/or system prompt.
    If an initial message is provided, the AI will respond to it.
    """
    # Generate a unique conversation ID (using timestamp-based ID for simplicity)
    # In production, you might want to use a proper ID generation strategy
    conversation_id = int(datetime.now(UTC).timestamp() * 1000)

    bind_contextvars(conversation_id=conversation_id, user_id=user.user_id)

    try:
        logger.info("creating_conversation", user_id=user.user_id)

        # Create the channel in the database
        await repo.create_channel(conversation_id)

        messages: list[MessageResponse] = []
        msg_id = 1

        # Add system prompt if provided
        if request.system_prompt:
            await repo.add_message(
                conversation_id,
                "Anthropic",
                "behavior",
                False,
                request.system_prompt,
            )
            logger.info("system_prompt_set")

        # Add initial message and get response if provided
        if request.initial_message:
            # Check rate limit using authenticated user's ID
            rate_check = await rate_limiter.check(user.user_id, "chat")
            if not rate_check.allowed:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "error": "Rate limit exceeded",
                        "wait_seconds": rate_check.wait_seconds,
                    },
                )

            # Add user message
            await repo.add_message(
                conversation_id,
                "Anthropic",
                "prompt",
                False,
                request.initial_message,
            )

            user_msg = MessageResponse(
                id=msg_id,
                role="user",
                content=request.initial_message,
                created_at=datetime.now(UTC),
            )
            messages.append(user_msg)
            msg_id += 1

            # Get AI response
            context = await repo.get_visible_messages(conversation_id, "All Models")
            chat_messages, system_prompt = _convert_context_to_messages(context)

            chat_response = await ai_provider.chat(
                chat_messages, system_prompt=system_prompt
            )

            # Save assistant response
            await repo.add_message(
                conversation_id,
                "Anthropic",
                "assistant",
                False,
                chat_response.content,
            )

            assistant_msg = MessageResponse(
                id=msg_id,
                role="assistant",
                content=chat_response.content,
                created_at=datetime.now(UTC),
            )
            messages.append(assistant_msg)

            # Record rate limit usage
            await rate_limiter.record(user.user_id, "chat")

            logger.info("initial_message_processed")

        logger.info("conversation_created", message_count=len(messages))

        return ConversationResponse(
            id=conversation_id,
            messages=messages,
            created_at=datetime.now(UTC),
        )

    finally:
        clear_contextvars()


@router.get(
    "/{conversation_id}",
    response_model=ConversationResponse,
    responses={
        200: {"description": "Conversation retrieved successfully"},
        401: {"model": ErrorResponse, "description": "Authentication required"},
        404: {"model": ErrorResponse, "description": "Conversation not found"},
    },
)
async def get_conversation(
    conversation_id: int,
    user: AuthUser = Depends(get_current_user),
    repo: RepositoryAdapter = Depends(get_repository),
) -> ConversationResponse:
    """Retrieve a conversation by ID with all messages."""
    bind_contextvars(conversation_id=conversation_id, user_id=user.user_id)

    try:
        logger.info("retrieving_conversation", user_id=user.user_id)

        # Get all visible messages
        context = await repo.get_visible_messages(conversation_id, "All Models")

        if not context:
            # Check if channel exists but has no messages
            # For now, return empty conversation (channel might exist)
            pass

        messages: list[MessageResponse] = []
        msg_id = 1

        for row in context:
            msg_type = row["message_type"]
            if msg_type == "behavior":
                continue

            if msg_type == "prompt":
                role = "user"
            elif msg_type == "assistant":
                role = "assistant"
            else:
                continue

            messages.append(
                MessageResponse(
                    id=msg_id,
                    role=role,
                    content=row["message_data"],
                    created_at=None,  # Not stored in current schema
                )
            )
            msg_id += 1

        logger.info("conversation_retrieved", message_count=len(messages))

        return ConversationResponse(
            id=conversation_id,
            messages=messages,
            created_at=None,  # Not stored in current schema
        )

    finally:
        clear_contextvars()


@router.post(
    "/{conversation_id}/messages",
    response_model=ChatCompletionResponse,
    responses={
        200: {"description": "Message sent and response received"},
        401: {"model": ErrorResponse, "description": "Authentication required"},
        404: {"model": ErrorResponse, "description": "Conversation not found"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
    },
)
async def send_message(
    conversation_id: int,
    request: ChatCompletionRequest,
    user: AuthUser = Depends(get_current_user),
    repo: RepositoryAdapter = Depends(get_repository),
    ai_provider: AIProvider = Depends(get_ai_provider),
    rate_limiter: SlidingWindowRateLimiter = Depends(get_rate_limiter),
) -> ChatCompletionResponse:
    """Send a message in a conversation and get an AI response."""
    bind_contextvars(conversation_id=conversation_id, user_id=user.user_id)

    try:
        logger.info("sending_message", user_id=user.user_id)

        # Check rate limit using authenticated user's ID
        rate_check = await rate_limiter.check(user.user_id, "chat")
        if not rate_check.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "Rate limit exceeded",
                    "wait_seconds": rate_check.wait_seconds,
                },
            )

        # Ensure channel exists
        await repo.create_channel(conversation_id)

        # Add user message
        await repo.add_message(
            conversation_id,
            "Anthropic",
            "prompt",
            False,
            request.content,
        )

        # Get context and generate response
        context = await repo.get_visible_messages(conversation_id, "All Models")
        chat_messages, system_prompt = _convert_context_to_messages(context)

        chat_response = await ai_provider.chat(
            chat_messages, system_prompt=system_prompt
        )

        # Save assistant response
        await repo.add_message(
            conversation_id,
            "Anthropic",
            "assistant",
            False,
            chat_response.content,
        )

        # Record rate limit usage
        await rate_limiter.record(user.user_id, "chat")

        now = datetime.now(UTC)

        user_message = MessageResponse(
            id=len(context),
            role="user",
            content=request.content,
            created_at=now,
        )

        assistant_message = MessageResponse(
            id=len(context) + 1,
            role="assistant",
            content=chat_response.content,
            created_at=now,
        )

        logger.info("message_sent", user_id=user.user_id)

        return ChatCompletionResponse(
            user_message=user_message,
            assistant_message=assistant_message,
        )

    finally:
        clear_contextvars()


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {"description": "Conversation cleared successfully"},
        401: {"model": ErrorResponse, "description": "Authentication required"},
    },
)
async def clear_conversation(
    conversation_id: int,
    user: AuthUser = Depends(get_current_user),
    repo: RepositoryAdapter = Depends(get_repository),
) -> None:
    """Clear all messages in a conversation."""
    bind_contextvars(conversation_id=conversation_id, user_id=user.user_id)

    try:
        logger.info("clearing_conversation", user_id=user.user_id)
        await repo.deactivate_all_messages(conversation_id)
        logger.info("conversation_cleared")

    finally:
        clear_contextvars()
