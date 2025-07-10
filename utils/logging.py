import logging
import sys
from typing import Optional


def setup_logging(
    level: str = "INFO",
    format_string: Optional[str] = None,
) -> logging.Logger:

    if format_string is None:
        format_string = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    formatter = logging.Formatter(format_string)

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    root_logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    codemind_logger = logging.getLogger("codemind")
    codemind_logger.setLevel(getattr(logging, level.upper()))

    codemind_logger.propagate = True

    return codemind_logger


def get_logger(name: str = "codemind") -> logging.Logger:
    logger = logging.getLogger(name)
    logger.propagate = True
    return logger
