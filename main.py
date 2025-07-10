"""
Turbo Review - AI-powered code review system

Usage:
    python main.py <command> [options]

Commands:
    index <repo_path>     - Index a repository
    review <diff_file>    - Review a diff file using existing index
    health                - Check database health
"""

import sys
import asyncio

from cli.config import Config
from services.review_service import ReviewService
from storage.database import TurboReviewDatabase
from utils.logging import setup_logging, get_logger


async def index_repository(repo_path: str):
    """Index a repository for code review."""
    config = Config.load()
    logger = get_logger()

    # Initialize database
    db = TurboReviewDatabase()

    # Check database health
    health = db.health_check()
    if not all(health.values()):
        logger.error(f"Database health check failed: {health}")
        logger.error("Make sure to start databases with: docker-compose up -d")
        sys.exit(1)

    logger.info("Database health check passed")

    # Initialize service with database
    service = ReviewService(config, logger, db)

    success = await service.index_repository(repo_path)
    if not success:
        logger.error("Failed to index repository")
        sys.exit(1)

    # Show stats
    stats = db.get_database_stats()
    logger.info(f"Indexing complete. Database stats: {stats}")


async def review_diff(diff_file: str):
    """Review a diff file."""
    config = Config.load()
    logger = get_logger()

    # Initialize database
    db = TurboReviewDatabase()

    # Check database health
    health = db.health_check()
    if not all(health.values()):
        logger.error(f"Database health check failed: {health}")
        logger.error("Make sure to start databases with: docker-compose up -d")
        sys.exit(1)

    # Initialize service with database
    service = ReviewService(config, logger, db)

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


async def health_check():
    """Check database health."""
    logger = get_logger()

    try:
        db = TurboReviewDatabase()
        health = db.health_check()
        stats = db.get_database_stats()

        logger.info("=== Database Health Check ===")
        logger.info(f"Vector DB (Qdrant): {'✅' if health['vector_db'] else '❌'}")
        logger.info(f"Graph DB (Neo4j): {'✅' if health['graph_db'] else '❌'}")
        logger.info(f"Database Stats: {stats}")

        if all(health.values()):
            logger.info("All databases are healthy! 🎉")
        else:
            logger.error("Some databases are unhealthy. Run: docker-compose up -d")
            sys.exit(1)

    except Exception as e:
        logger.error(f"Health check failed: {e}")
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
    elif command == "health":
        asyncio.run(health_check())
    else:
        logger.info(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
