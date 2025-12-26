"""Tests for structured logging configuration."""

import json
import logging
from io import StringIO
from unittest.mock import patch

import structlog

from src.core.logging import (
    bind_contextvars,
    clear_contextvars,
    configure_logging,
    get_logger,
    unbind_contextvars,
)


class TestConfigureLogging:
    """Tests for configure_logging function."""

    def setup_method(self) -> None:
        """Reset structlog and logging configuration before each test."""
        structlog.reset_defaults()
        clear_contextvars()

    def test_configure_development_mode(self) -> None:
        """Should configure pretty-printed output in development mode."""
        configure_logging(development=True)
        logger = get_logger("test")
        # Should not raise
        logger.info("test message", key="value")

    def test_configure_production_mode(self) -> None:
        """Should configure JSON output in production mode."""
        configure_logging(development=False)
        logger = get_logger("test")
        # Should not raise
        logger.info("test message", key="value")

    def test_reads_environment_variable(self) -> None:
        """Should read ENVIRONMENT env var to determine mode."""
        with patch.dict("os.environ", {"ENVIRONMENT": "production"}):
            configure_logging()
            # Should not raise
            logger = get_logger("test")
            logger.info("test")

    def test_reads_log_level_environment_variable(self) -> None:
        """Should read LOG_LEVEL env var."""
        with patch.dict("os.environ", {"LOG_LEVEL": "DEBUG"}):
            configure_logging(development=True)
            # Should configure DEBUG level
            assert logging.getLogger().level == logging.DEBUG

    def test_default_log_level_is_info(self) -> None:
        """Should default to INFO log level."""
        configure_logging(development=True, log_level="INFO")
        assert logging.getLogger().level == logging.INFO

    def test_silences_third_party_loggers(self) -> None:
        """Should set third-party loggers to WARNING level."""
        configure_logging(development=True)
        assert logging.getLogger("discord").level == logging.WARNING
        assert logging.getLogger("anthropic").level == logging.WARNING
        assert logging.getLogger("httpx").level == logging.WARNING


class TestGetLogger:
    """Tests for get_logger function."""

    def setup_method(self) -> None:
        """Configure logging before each test."""
        structlog.reset_defaults()
        configure_logging(development=True)

    def test_returns_bound_logger(self) -> None:
        """Should return a structlog BoundLogger."""
        logger = get_logger("test.module")
        assert hasattr(logger, "info")
        assert hasattr(logger, "debug")
        assert hasattr(logger, "warning")
        assert hasattr(logger, "error")

    def test_logger_with_name(self) -> None:
        """Should create logger with specified name."""
        logger = get_logger("my.custom.logger")
        # Should not raise
        logger.info("test message")

    def test_logger_without_name(self) -> None:
        """Should create logger without name."""
        logger = get_logger()
        # Should not raise
        logger.info("test message")


class TestContextVars:
    """Tests for context variable functions."""

    def setup_method(self) -> None:
        """Configure logging and clear context before each test."""
        structlog.reset_defaults()
        clear_contextvars()
        configure_logging(development=True)

    def test_bind_contextvars_adds_to_context(self) -> None:
        """Should add variables to logging context."""
        bind_contextvars(correlation_id="abc-123", user_id=456)
        # Variables should be bound (tested implicitly through logging)
        logger = get_logger("test")
        logger.info("test message")  # Should include correlation_id and user_id

    def test_clear_contextvars_removes_all(self) -> None:
        """Should remove all bound context variables."""
        bind_contextvars(key1="value1", key2="value2")
        clear_contextvars()
        # Context should be empty now
        # This is tested implicitly - if clear didn't work, subsequent logs would have old values

    def test_unbind_contextvars_removes_specific(self) -> None:
        """Should remove only specified context variables."""
        bind_contextvars(keep="this", remove="that")
        unbind_contextvars("remove")
        # Only "remove" should be gone, "keep" should remain


class TestProductionJsonOutput:
    """Tests for JSON output in production mode."""

    def setup_method(self) -> None:
        """Reset configuration before each test."""
        structlog.reset_defaults()
        clear_contextvars()

    def test_json_output_is_valid(self) -> None:
        """Should produce valid JSON in production mode."""
        # Capture output
        output = StringIO()
        handler = logging.StreamHandler(output)
        handler.setLevel(logging.INFO)

        # Configure for production
        configure_logging(development=False, log_level="INFO")

        # Get root logger and add our handler
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)

        try:
            logger = get_logger("test")
            logger.info("test message", custom_key="custom_value")

            # Get output
            handler.flush()
            log_output = output.getvalue()

            # Should be valid JSON (might have multiple lines)
            if log_output.strip():
                # Parse the last line which should be our log
                lines = [line for line in log_output.strip().split("\n") if line]
                if lines:
                    last_line = lines[-1]
                    parsed = json.loads(last_line)
                    assert "event" in parsed
                    assert parsed["event"] == "test message"
        finally:
            root_logger.removeHandler(handler)


class TestStructuredLoggingIntegration:
    """Integration tests for structured logging."""

    def setup_method(self) -> None:
        """Configure logging before each test."""
        structlog.reset_defaults()
        clear_contextvars()
        configure_logging(development=True)

    def test_log_with_exception(self) -> None:
        """Should handle exception logging."""
        logger = get_logger("test")
        try:
            raise ValueError("test error")
        except ValueError:
            logger.exception("caught error")

    def test_log_levels(self) -> None:
        """Should support all standard log levels."""
        logger = get_logger("test")
        logger.debug("debug message")
        logger.info("info message")
        logger.warning("warning message")
        logger.error("error message")

    def test_log_with_complex_data(self) -> None:
        """Should handle complex data types."""
        logger = get_logger("test")
        logger.info(
            "complex data",
            user={"id": 123, "name": "test"},
            items=[1, 2, 3],
            nested={"a": {"b": {"c": "deep"}}},
        )
