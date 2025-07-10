"""
Specialized service for AI-powered code reviews.
Uses the CodebaseService for context-aware review generation.
"""

import time
from typing import Optional
from dataclasses import dataclass

from services.codebase_service import CodebaseService
from inference.openai_client import LLMClient
from inference.prompt_builder import PromptBuilder
from processing.diff_processor import DiffProcessor
from processing.reranker import CodeReranker

from monitoring.telemetry import get_telemetry
from utils.logging import get_logger


@dataclass
class ReviewResult:
    """Result of a code review operation."""
    review_content: str
    changed_chunks_count: int
    context_chunks_count: int
    duration: float
    review_type: str  # 'contextual' or 'quick'


class CodeReviewService:
    """
    Specialized service for AI-powered code reviews.
    
    This service handles:
    - Context-aware diff reviews using indexed codebase
    - Quick reviews without context
    - PR review generation
    - Review quality analysis
    """

    def __init__(self, config, logger_instance=None, codebase_service=None):
        self.config = config
        self.logger = logger_instance or get_logger(__name__)
        self.telemetry = get_telemetry()
        self.prompt_builder = PromptBuilder()
        self.codebase_service = codebase_service or CodebaseService(config)

    async def review_diff(
        self, 
        diff_content: str, 
        repo_url: Optional[str] = None,
        context_enabled: bool = True
    ) -> Optional[ReviewResult]:
        """
        Review a diff with optional codebase context.
        
        Args:
            diff_content: The diff content to review
            repo_url: Optional repository URL for context
            context_enabled: Whether to use codebase context
            
        Returns:
            ReviewResult with review details
        """
        review_start = time.time()
        
        with self.telemetry.trace_operation(
            "review_diff", 
            {"repo_url": repo_url, "context_enabled": context_enabled}
        ):
            self.logger.info(f"Reviewing diff (context: {context_enabled})")

            # Process diff to extract changed chunks
            with self.telemetry.trace_operation("process_diff"):
                processor = DiffProcessor()
                changed_chunks = processor.extract_changed_chunks(diff_content, repo_url)
            
            self.logger.info(f"Found {len(changed_chunks)} changed chunks")

            # Determine query for context search
            if not changed_chunks:
                self.logger.info("No code chunks changed. Creating generic review.")
                query = "code review"
            else:
                query = processor.create_query_from_changes(changed_chunks)

            async with LLMClient(config=self.config) as client:
                try:
                    reranked_results = []
                    
                    if context_enabled:
                        # Search for related code using the codebase service
                        with self.telemetry.trace_operation("vector_search"):
                            retrieval_start = time.time()
                            query_embedding = await client.embed(query)

                            # Search in database through codebase service
                            search_results = self.codebase_service.database.search_similar_code(
                                query_embedding,
                                repo_url=repo_url,
                                limit=self.config.vector_search_k,
                                score_threshold=0.7,
                            )

                            retrieval_duration = time.time() - retrieval_start
                            self.telemetry.record_retrieval_duration(
                                retrieval_duration, {"query_type": "diff_review"}
                            )

                        self.logger.info(f"Found {len(search_results)} relevant chunks")

                        # Rerank results for better relevance
                        if search_results:
                            with self.telemetry.trace_operation("rerank_results"):
                                reranker = CodeReranker(client)
                                reranked_results = await reranker.rerank_search_results(
                                    query,
                                    search_results,
                                    top_k=self.config.rerank_top_k,
                                )

                            self.logger.info(f"Reranked to {len(reranked_results)} chunks")

                    # Generate review using appropriate prompt
                    self.logger.info("Generating review...")
                    
                    if context_enabled and reranked_results:
                        # Context-aware review
                        review_prompt = self.prompt_builder.build_review_prompt(
                            diff_content=diff_content,
                            context_chunks=reranked_results,
                            changed_chunks=changed_chunks,
                            graph_context=[],
                        )
                        review_type = "contextual"
                    else:
                        # Quick review without context
                        review_prompt = self.prompt_builder.build_quick_review_prompt(diff_content)
                        review_type = "quick"

                    with self.telemetry.trace_operation("generate_review"):
                        review = await client.complete([
                            {"role": "user", "content": review_prompt}
                        ])

                    # Record total review duration
                    review_duration = time.time() - review_start
                    self.telemetry.record_review_duration(
                        review_duration, {"review_type": review_type}
                    )

                    return ReviewResult(
                        review_content=review,
                        changed_chunks_count=len(changed_chunks),
                        context_chunks_count=len(reranked_results),
                        duration=review_duration,
                        review_type=review_type
                    )

                except Exception as e:
                    self.logger.error(f"Error during review: {e}")
                    return None

    async def quick_review(self, diff_content: str) -> Optional[ReviewResult]:
        """
        Perform a quick review without codebase context.
        
        Args:
            diff_content: The diff content to review
            
        Returns:
            ReviewResult with review details
        """
        review_start = time.time()
        self.logger.info("Performing quick review")

        # Generate review using PromptBuilder
        review_prompt = self.prompt_builder.build_quick_review_prompt(diff_content)

        async with LLMClient(config=self.config) as client:
            try:
                review = await client.complete([
                    {"role": "user", "content": review_prompt}
                ])

                review_duration = time.time() - review_start
                return ReviewResult(
                    review_content=review,
                    changed_chunks_count=0,  # Not calculated for quick review
                    context_chunks_count=0,  # No context used
                    duration=review_duration,
                    review_type="quick"
                )
            except Exception as e:
                self.logger.error(f"Error during quick review: {e}")
                return None

    async def review_pull_request(
        self,
        pr_diff_url: str,
        repo_url: str,
        pr_number: int
    ) -> Optional[ReviewResult]:
        """
        Review a GitHub pull request.
        
        Args:
            pr_diff_url: URL to the PR diff
            repo_url: Repository URL
            pr_number: Pull request number
            
        Returns:
            ReviewResult with review details
        """
        try:
            # Download diff content
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get(pr_diff_url)
                if response.status_code != 200:
                    self.logger.error(f"Failed to download diff: {response.status_code}")
                    return None
                diff_content = response.text

            # Review with context
            result = await self.review_diff(
                diff_content=diff_content,
                repo_url=repo_url,
                context_enabled=True
            )

            if result:
                self.logger.info(f"Generated review for PR #{pr_number}")
            
            return result

        except Exception as e:
            self.logger.error(f"Error reviewing PR #{pr_number}: {e}")
            return None