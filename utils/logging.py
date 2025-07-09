import logging
import sys
from typing import Optional


def setup_logging(
    level: str = "INFO",
    format_string: Optional[str] = None,
) -> logging.Logger:
    """Set up logging configuration."""

    if format_string is None:
        format_string = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    formatter = logging.Formatter(format_string)

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    root_logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    turbo_logger = logging.getLogger("turbo-review")
    turbo_logger.setLevel(getattr(logging, level.upper()))

    turbo_logger.propagate = True

    return turbo_logger


def get_logger(name: str = "turbo-review") -> logging.Logger:
    """Get logger instance."""
    logger = logging.getLogger(name)
    logger.propagate = True
    return logger
