import asyncio
from typing import Optional

import click
from utils.logging import get_logger, setup_logging

from cli.config import Config
from services.review_service import ReviewService
from monitoring.telemetry import setup_telemetry


@click.group()
@click.option("--config", "-c", help="Config file path")
@click.pass_context
def cli(ctx, config):
    """Turbo Review - AI-powered code review system."""
    ctx.ensure_object(dict)
    loaded_config = Config.load(config)
    ctx.obj["config"] = loaded_config

    # Initialize logging first
    setup_logging(level=loaded_config.log_level)
    ctx.obj["logger"] = get_logger(__name__)

    # Initialize telemetry
    setup_telemetry()


@cli.command()
@click.argument("repo_path", type=click.Path(exists=True))
@click.option("--output", "-o", default="index", help="Output index name")
@click.pass_context
def index(ctx, repo_path: str, output: str):
    """Index a repository for code review."""
    asyncio.run(_index_repository(repo_path, output, ctx.obj["config"], ctx.obj["logger"]))


@cli.command()
@click.argument("diff_file", type=click.Path(exists=True))
@click.option("--index", "-i", default="index", help="Index to use")
@click.option("--repo", "-r", help="Repository path")
@click.pass_context
def review(ctx, diff_file: str, index: str, repo: Optional[str]):
    """Review a diff file."""
    asyncio.run(_review_diff(diff_file, index, repo, ctx.obj["config"], ctx.obj["logger"]))


@cli.command()
@click.argument("repo_path", type=click.Path(exists=True))
@click.argument("diff_file", type=click.Path(exists=True))
@click.pass_context
def quick(ctx, repo_path: str, diff_file: str):
    """Quick review without pre-indexing."""
    asyncio.run(_quick_review(repo_path, diff_file, ctx.obj["config"], ctx.obj["logger"]))


async def _index_repository(repo_path: str, output: str, config: Config, logger_instance):
    """Index repository implementation."""
    service = ReviewService(config, logger_instance)
    success = await service.index_repository(repo_path, output)
    if success:
        logger_instance.info(f"Repository '{repo_path}' indexed successfully to '{output}'")
    else:
        logger_instance.error("Failed to index repository")


async def _review_diff(
    diff_file: str, index: str, repo_path: Optional[str], config: Config, logger_instance
):
    """Review diff implementation."""
    service = ReviewService(config, logger_instance)
    result = await service.review_diff(diff_file, index, repo_path)
    
    if result:
        # Display review
        logger_instance.info("\n" + "=" * 60)
        logger_instance.info("📋 CODE REVIEW")
        logger_instance.info("=" * 60)
        logger_instance.info(result.review_content)
        logger_instance.info("=" * 60)
    else:
        logger_instance.error("❌ Error during review")


async def _quick_review(repo_path: str, diff_file: str, config: Config, logger_instance):
    """Quick review without indexing."""
    logger_instance.info(f"⚡ Quick review: {diff_file}")
    
    service = ReviewService(config, logger_instance)
    result = await service.quick_review(repo_path, diff_file)
    
    if result:
        # Display review
        logger_instance.info("\n" + "=" * 60)
        logger_instance.info("📋 QUICK CODE REVIEW")
        logger_instance.info("=" * 60)
        logger_instance.info(result.review_content)
        logger_instance.info("=" * 60)
    else:
        logger_instance.error("❌ Error during review")
