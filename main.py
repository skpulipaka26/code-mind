"""
CodeMind - AI-powered codebase intelligence platform

Usage:
    python main.py <command> [options]

Commands:
    index <repo_path>     - Index a repository
    review <diff_file>    - Review a diff file using existing index
    health                - Check database health
"""

import os
import sys
import asyncio

# Suppress tokenizers parallelism warning
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from config import Config
from services.codebase_service import CodebaseService
from services.code_review_service import CodeReviewService
from storage.database import CodeMindDatabase
from utils.logging import setup_logging, get_logger


async def index_repository(repo_path: str):
    """Index a repository for code review."""
    config = Config.load()
    logger = get_logger()

    # Initialize database
    db = CodeMindDatabase()

    # Check database health
    health = db.health_check()
    if not all(health.values()):
        logger.error(f"Database health check failed: {health}")
        logger.error("Make sure to start databases with: docker-compose up -d")
        sys.exit(1)

    logger.info("Database health check passed")

    # Initialize service with database
    service = CodebaseService(config, logger, db)

    result = await service.index_repository(repo_path)
    if not result.success:
        logger.error(f"Failed to index repository: {result.message}")
        sys.exit(1)

    logger.info(
        f"Successfully indexed {result.chunks_indexed} chunks in {result.duration:.2f}s"
    )

    # Show stats
    repositories = db.list_repositories()
    logger.info(f"Indexing complete. Total repositories: {len(repositories)}")


async def review_diff(diff_file: str):
    """Review a diff file."""
    config = Config.load()
    logger = get_logger()

    # Initialize database
    db = CodeMindDatabase()

    # Check database health
    health = db.health_check()
    if not all(health.values()):
        logger.error(f"Database health check failed: {health}")
        logger.error("Make sure to start databases with: docker-compose up -d")
        sys.exit(1)

    # Initialize service with database
    service = CodeReviewService(config, logger)

    # Read diff content from file
    with open(diff_file, "r") as f:
        diff_content = f.read()

    result = await service.review_diff(diff_content)
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
        db = CodeMindDatabase()
        health = db.health_check()
        repositories = db.list_repositories()

        logger.info("=== Database Health Check ===")
        logger.info(f"Vector DB (Qdrant): {'✅' if health['vector_db'] else '❌'}")
        logger.info(f"Graph DB (Neo4j): {'✅' if health['graph_db'] else '❌'}")
        logger.info(f"Total repositories: {len(repositories)}")

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
