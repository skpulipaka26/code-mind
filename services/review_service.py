"""
Core review service that handles indexing and reviewing operations.
Uses persistent databases (Qdrant + Neo4j) instead of file storage.
"""

import time
import hashlib
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from storage.database import TurboReviewDatabase, CodeChunk
from graph_engine.summarizer import HierarchicalSummarizer
from core.chunker import TreeSitterChunker
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


class ReviewService:
    """Core service for code review operations using persistent databases."""

    def __init__(self, config, logger_instance=None, database=None):
        self.config = config
        self.logger = logger_instance or get_logger(__name__)
        self.telemetry = get_telemetry()
        self.prompt_builder = PromptBuilder()
        self.database = database or TurboReviewDatabase()

    def _content_hash(self, content: str) -> str:
        """Generate SHA-256 hash for content."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    async def index_repository(self, repo_path: str) -> bool:
        """Index a repository for code review using persistent databases."""
        with self.telemetry.trace_operation(
            "index_repository", {"repo_path": repo_path}
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
                    self.logger.error(
                        f"Invalid path: {repo_path}. Must be a file or a directory."
                    )
                    return False

            self.logger.info(f"Found {len(chunks)} code chunks")
            self.telemetry.update_chunk_count(
                len(chunks), {"operation": "index", "repo": repo_path}
            )

            if not chunks:
                self.logger.warning("No code chunks found. Check repository path.")
                return False

            # Convert to CodeChunk objects and generate embeddings
            async with LLMClient(config=self.config) as client:
                try:
                    # Generate embeddings
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
                            self.logger.debug(
                                f"Generated {len(embeddings)} embeddings so far."
                            )

                        embedding_duration = time.time() - embedding_start
                        self.telemetry.record_embedding_duration(
                            embedding_duration, {"chunk_count": len(chunks)}
                        )

                    self.logger.info(f"Generated {len(embeddings)} embeddings")

                    # Convert to CodeChunk objects with embeddings
                    code_chunks = []
                    for i, chunk in enumerate(chunks):
                        content_hash = self._content_hash(chunk.content)

                        code_chunk = CodeChunk(
                            content_hash=content_hash,
                            content=chunk.content,
                            chunk_type=chunk.chunk_type,
                            file_path=chunk.file_path,
                            language=chunk.language,
                            name=chunk.name or "",
                            start_line=chunk.start_line,
                            end_line=chunk.end_line,
                            embedding=embeddings[i] if i < len(embeddings) else None,
                            metadata={
                                "parent_name": chunk.parent_name,
                                "parent_type": chunk.parent_type,
                                "full_signature": chunk.full_signature,
                            },
                        )
                        code_chunks.append(code_chunk)

                    # Store in database
                    with self.telemetry.trace_operation("store_chunks"):
                        success = self.database.store_code_chunks(code_chunks)
                        if not success:
                            self.logger.error("Failed to store chunks in database")
                            return False

                    self.logger.info(f"Stored {len(code_chunks)} chunks in database")

                    # Generate summaries
                    try:
                        with self.telemetry.trace_operation("generate_summaries"):
                            self.logger.info("Generating code summaries...")

                            # Create a temporary knowledge graph for summarization
                            # We'll use the graph database for relationships later
                            from graph_engine.knowledge_graph import KnowledgeGraph

                            temp_kg = KnowledgeGraph()

                            # Add nodes to temp graph for summarization
                            for chunk in code_chunks:
                                node_id = chunk.content_hash
                                temp_kg.add_node(
                                    node_id,
                                    chunk.chunk_type,
                                    {
                                        "content": chunk.content,
                                        "content_hash": chunk.content_hash,
                                        "file_path": chunk.file_path,
                                        "language": chunk.language,
                                        "name": chunk.name,
                                        "start_line": chunk.start_line,
                                        "end_line": chunk.end_line,
                                        **chunk.metadata,
                                    },
                                )

                            summarizer = HierarchicalSummarizer(temp_kg, client)

                            # Get all node IDs for summarization
                            chunk_hashes = [chunk.content_hash for chunk in code_chunks]

                            if chunk_hashes:
                                summaries = await summarizer.summarize_chunks_batch(
                                    chunk_hashes
                                )
                                self.logger.info(
                                    f"Generated {len(summaries)} code summaries"
                                )

                                # Update chunks with summaries
                                for chunk in code_chunks:
                                    if chunk.content_hash in summaries:
                                        # Extract just the summary text from the formatted output
                                        summary_text = summaries[chunk.content_hash]
                                        if summary_text.startswith("["):
                                            # Remove the header like "[Chunk Summary for function_name in file.py]"
                                            lines = summary_text.split("\n", 1)
                                            if len(lines) > 1:
                                                summary_text = lines[1].strip()
                                        chunk.summary = summary_text

                                # Re-store chunks with summaries
                                success = self.database.store_code_chunks(code_chunks)
                                if not success:
                                    self.logger.warning(
                                        "Failed to update chunks with summaries"
                                    )
                            else:
                                self.logger.info("No chunks found to summarize")

                    except Exception as e:
                        self.logger.error(
                            f"Error generating summaries: {e}", exc_info=True
                        )
                        self.logger.warning("Continuing without summaries...")

                except Exception as e:
                    self.logger.error(f"Error during indexing: {e}")
                    return False

            self.logger.info("Repository indexed successfully")
            return True

    async def review_diff(
        self, diff_file: str, repo_path: Optional[str] = None
    ) -> Optional[ReviewResult]:
        """Review a diff file using the database."""
        with self.telemetry.trace_operation("review_diff", {"diff_file": diff_file}):
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
                changed_chunks = processor.extract_changed_chunks(
                    diff_content, repo_path
                )
            self.logger.info(f"Found {len(changed_chunks)} changed chunks")

            if not changed_chunks:
                self.logger.info("No code chunks changed. Creating generic review.")
                query = "code review"
            else:
                query = processor.create_query_from_changes(changed_chunks)

            # Search and review
            async with LLMClient(config=self.config) as client:
                try:
                    # Search for related code using vector similarity
                    with self.telemetry.trace_operation("vector_search"):
                        retrieval_start = time.time()
                        query_embedding = await client.embed(query)

                        # Search in database
                        search_results = self.database.search_similar_code(
                            query_embedding,
                            limit=self.config.vector_search_k,
                            score_threshold=0.7,
                        )

                        retrieval_duration = time.time() - retrieval_start
                        self.telemetry.record_retrieval_duration(
                            retrieval_duration, {"query_type": "diff_review"}
                        )

                    self.logger.info(
                        f"Original vector search results ({len(search_results)} chunks):"
                    )
                    for i, result in enumerate(search_results):
                        self.logger.info(
                            f"  {i + 1}. {result.metadata.get('file_path', 'unknown')}:{result.metadata.get('chunk_type', 'unknown')} '{result.metadata.get('name', 'unnamed')}' (vector score: {result.score:.3f})"
                        )

                    reranked_results = []
                    if search_results:
                        # Rerank results
                        with self.telemetry.trace_operation("rerank_results"):
                            reranker = CodeReranker(client)

                            reranked_results = await reranker.rerank_search_results(
                                query,
                                search_results,
                                top_k=self.config.rerank_top_k,
                            )

                        # Log reranked results
                        self.logger.info(
                            f"After reranking ({len(reranked_results)} chunks):"
                        )
                        for i, result in enumerate(reranked_results):
                            metadata = result.result.metadata
                            self.logger.info(
                                f"  {i + 1}. {metadata.get('file_path', 'unknown')}:{metadata.get('chunk_type', 'unknown')} '{metadata.get('name', 'unnamed')}' (score: {result.score:.3f})"
                            )

                    # Generate review using PromptBuilder
                    self.logger.info("Building review prompt...")
                    review_prompt = self.prompt_builder.build_review_prompt(
                        diff_content=diff_content,
                        context_chunks=reranked_results,
                        changed_chunks=changed_chunks,
                        graph_context=[],  # No graph context for now
                    )
                    self.logger.info(
                        f"Generated prompt: {len(review_prompt)} characters"
                    )
                    self.logger.info(f"  Diff content: {len(diff_content)} chars")
                    self.logger.info(f"  Context chunks: {len(reranked_results)}")
                    self.logger.info(f"  Changed chunks: {len(changed_chunks)}")

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
                        duration=review_duration,
                    )

                except Exception as e:
                    self.logger.error(f"Error during review: {e}")
                    return None

    async def quick_review(
        self, repo_path: str, diff_file: str
    ) -> Optional[ReviewResult]:
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

        async with LLMClient(config=self.config) as client:
            try:
                review = await client.complete(
                    [{"role": "user", "content": review_prompt}]
                )

                review_duration = time.time() - review_start
                return ReviewResult(
                    review_content=review,
                    changed_chunks_count=0,  # Not calculated for quick review
                    context_chunks_count=0,  # Not calculated for quick review
                    duration=review_duration,
                )
            except Exception as e:
                self.logger.error(f"Error during quick review: {e}")
                return None
