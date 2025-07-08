"""
Core review service that handles indexing and reviewing operations.
This service is used by both CLI and main.py entry points.
"""

import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from core.chunker import TreeSitterChunker
from core.vectordb import VectorDatabase
from inference.openai_client import OpenRouterClient
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


class ReviewService:
    """Core service for code review operations."""
    
    def __init__(self, config, logger_instance=None):
        self.config = config
        self.logger = logger_instance or get_logger(__name__)
        self.telemetry = get_telemetry()
        self.prompt_builder = PromptBuilder()
    
    async def index_repository(self, repo_path: str, output: str = "index") -> bool:
        """Index a repository for code review."""
        with self.telemetry.trace_operation(
            "index_repository", {"repo_path": repo_path, "output": output}
        ):
            self.logger.info(f"Indexing repository: {repo_path}")

            # Extract code chunks
            with self.telemetry.trace_operation("extract_chunks"):
                chunker = TreeSitterChunker()
                path = Path(repo_path)
                if path.is_file():
                    chunks = chunker.chunk_file(str(path), path.read_text())
                elif path.is_dir():
                    chunks = chunker.chunk_repository(str(path))
                else:
                    self.logger.error(f"Invalid path: {repo_path}. Must be a file or a directory.")
                    return False

            self.logger.info(f"Found {len(chunks)} code chunks")
            self.telemetry.update_chunk_count(
                len(chunks), {"operation": "index", "repo": repo_path}
            )

            if not chunks:
                self.logger.warning("No code chunks found. Check repository path.")
                return False

            # Generate embeddings
            async with OpenRouterClient(api_key=self.config.openrouter_api_key, config=self.config) as client:
                try:
                    with self.telemetry.trace_operation(
                        "generate_embeddings", {"chunk_count": len(chunks)}
                    ):
                        embedding_start = time.time()
                        contents = [chunk.content for chunk in chunks]
                        self.logger.info("Generating embeddings...")
                        embeddings = []
                        batch_size = self.config.embedding_batch_size
                        for i in range(0, len(contents), batch_size):
                            batch = contents[i : i + batch_size]
                            batch_embeddings = await client.embed_batch(batch)
                            embeddings.extend(batch_embeddings)
                            self.logger.debug(f"Generated {len(embeddings)} embeddings so far.")

                        embedding_duration = time.time() - embedding_start
                        self.telemetry.record_embedding_duration(
                            embedding_duration, {"chunk_count": len(chunks)}
                        )

                    self.logger.info(f"Generated {len(embeddings)} embeddings")
                except Exception as e:
                    self.logger.error(f"Error generating embeddings: {e}")
                    return False

            # Store in vector database
            try:
                with self.telemetry.trace_operation("store_vectors"):
                    db = VectorDatabase()
                    db.add_chunks(chunks, embeddings)
                    db.save(output)
                self.logger.info(f"Repository indexed successfully as '{output}'")
                return True
            except Exception as e:
                self.logger.error(f"Error saving index: {e}", exc_info=True)
                return False
    
    async def review_diff(
        self, 
        diff_file: str, 
        index: str = "index", 
        repo_path: Optional[str] = None
    ) -> Optional[ReviewResult]:
        """Review a diff file using indexed code."""
        with self.telemetry.trace_operation(
            "review_diff", {"diff_file": diff_file, "index": index}
        ):
            review_start = time.time()
            self.logger.info(f"Reviewing diff: {diff_file}")

            # Load diff
            try:
                diff_content = Path(diff_file).read_text()
            except Exception as e:
                self.logger.error(f"Error reading diff file: {e}")
                return None

            # Process diff
            with self.telemetry.trace_operation("process_diff"):
                processor = DiffProcessor()
                changed_chunks = processor.extract_changed_chunks(diff_content, repo_path)
            self.logger.info(f"Found {len(changed_chunks)} changed chunks")

            if not changed_chunks:
                self.logger.info("No code chunks changed. Creating generic review.")
                query = "code review"
            else:
                query = processor.create_query_from_changes(changed_chunks)

            # Load vector database
            try:
                with self.telemetry.trace_operation("load_index"):
                    db = VectorDatabase()
                    db.load(index)
                self.logger.info(f"Loaded index '{index}' with {len(db.metadata)} chunks")
            except Exception as e:
                self.logger.error(f"Error loading index '{index}': {e}")
                return None

            # Search and review
            async with OpenRouterClient(api_key=self.config.openrouter_api_key, config=self.config) as client:
                try:
                    # Search for related code
                    with self.telemetry.trace_operation("vector_search"):
                        retrieval_start = time.time()
                        query_embedding = await client.embed(query)
                        search_results = db.search(query_embedding, k=self.config.vector_search_k)
                        retrieval_duration = time.time() - retrieval_start
                        self.telemetry.record_retrieval_duration(
                            retrieval_duration, {"query_type": "diff_review"}
                        )

                    reranked_results = []
                    if search_results:
                        # Rerank results
                        with self.telemetry.trace_operation("rerank_results"):
                            reranker = CodeReranker(client)
                            chunk_contents = {
                                meta.chunk_id: db.get_content(meta.chunk_id)
                                for meta, _ in search_results
                            }
                            reranked_results = await reranker.rerank_search_results(
                                query, search_results, chunk_contents, top_k=self.config.rerank_top_k
                            )

                        # Add content to reranked results and log debug info
                        self.logger.debug("Retrieved chunks for debugging:")
                        for result in reranked_results:
                            result.content = db.get_content(result.metadata.chunk_id)
                            self.logger.debug(f"  File: {result.metadata.file_path}")
                            self.logger.debug(f"  Type: {result.metadata.chunk_type}")
                            if result.metadata.name:
                                self.logger.debug(f"  Name: {result.metadata.name}")
                            self.logger.debug(f"  Score: {result.score:.4f}")
                            self.logger.debug(f"  Content:\n{result.content}\n")

                    # Generate review using PromptBuilder
                    review_prompt = self.prompt_builder.build_review_prompt(
                        diff_content=diff_content,
                        context_chunks=reranked_results,
                        changed_chunks=changed_chunks
                    )

                    self.logger.info("Generating review...")
                    with self.telemetry.trace_operation("generate_review"):
                        review = await client.complete(
                            [{"role": "user", "content": review_prompt}]
                        )

                    # Record total review duration
                    review_duration = time.time() - review_start
                    self.telemetry.record_review_duration(
                        review_duration, {"diff_file": diff_file}
                    )

                    return ReviewResult(
                        review_content=review,
                        changed_chunks_count=len(changed_chunks),
                        context_chunks_count=len(reranked_results),
                        duration=review_duration
                    )

                except Exception as e:
                    self.logger.error(f"Error during review: {e}")
                    return None
    
    async def quick_review(self, repo_path: str, diff_file: str) -> Optional[ReviewResult]:
        """Quick review without pre-indexing."""
        review_start = time.time()
        self.logger.info(f"Quick review: {diff_file}")

        # Load diff
        try:
            diff_content = Path(diff_file).read_text()
        except Exception as e:
            self.logger.error(f"Error reading diff file: {e}")
            return None

        # Generate review using PromptBuilder
        review_prompt = self.prompt_builder.build_quick_review_prompt(diff_content)

        async with OpenRouterClient(api_key=self.config.openrouter_api_key, config=self.config) as client:
            try:
                review = await client.complete([{"role": "user", "content": review_prompt}])
                
                review_duration = time.time() - review_start
                return ReviewResult(
                    review_content=review,
                    changed_chunks_count=0,  # Not calculated for quick review
                    context_chunks_count=0,  # Not calculated for quick review
                    duration=review_duration
                )
            except Exception as e:
                self.logger.error(f"Error during quick review: {e}")
                return None