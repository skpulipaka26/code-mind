"""
Turbo Review - AI-powered code review system

Usage:
    python main.py <command> [options]

Commands:
    index <repo_path>     - Index a repository
    review <diff_file>    - Review a diff file using existing index
"""

import sys
import asyncio

from cli.config import Config
from services.review_service import ReviewService
from utils.logging import setup_logging, get_logger


async def index_repository(repo_path: str):
    """Index a repository for code review."""
    config = Config.load()
    logger = get_logger()
    service = ReviewService(config, logger)

    success = await service.index_repository(repo_path)
    if not success:
        logger.error("Failed to index repository")
        sys.exit(1)


async def review_diff(diff_file: str):
    """Review a diff file."""
    config = Config.load()
    logger = get_logger()
    service = ReviewService(config, logger)

    result = await service.review_diff(diff_file)
    if result:
        logger.info(
f"""
================================
CODE REVIEW
================================
{result.review_content}
================================
"""
        )
    else:
        logger.error("Failed to review diff")
        sys.exit(1)


def main():
    """Main entry point."""
    config = Config.load()
    setup_logging(level=config.log_level)
    logger = get_logger()

    if len(sys.argv) < 2:
        logger.info(__doc__)
        sys.exit(1)

    command = sys.argv[1]

    if command == "index" and len(sys.argv) > 2:
        asyncio.run(index_repository(sys.argv[2]))
    elif command == "review" and len(sys.argv) > 2:
        asyncio.run(review_diff(sys.argv[2]))
    else:
        logger.info(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
