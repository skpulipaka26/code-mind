"""
Core codebase service that handles indexing, search, and AI-powered interactions.
This is the main service for the AI-powered codebase platform.
"""

import time
import hashlib
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from storage.database import CodeMindDatabase, CodeChunk, RepositoryInfo
from graph_engine.summarizer import HierarchicalSummarizer
from core.chunker import TreeSitterChunker
from core.fallback_chunker import ChunkingConfig
from inference.openai_client import LLMClient
from inference.prompt_builder import PromptBuilder
from processing.reranker import CodeReranker

from monitoring.telemetry import get_telemetry
from utils.logging import get_logger
from utils.local_repo_manager import (
    get_local_repo_manager,
    is_github_url,
    is_local_path,
)


@dataclass
class IndexResult:
    """Result of a repository indexing operation."""

    success: bool
    chunks_indexed: int
    duration: float
    message: str


@dataclass
class SearchResult:
    """Result of a codebase search operation."""

    chunks: List[Dict[str, Any]]
    total_results: int
    duration: float
    query: str


@dataclass
class ConversationResult:
    """Result of a codebase conversation."""

    answer: str
    context_chunks: List[Dict[str, Any]]
    duration: float
    query: str


class CodebaseService:
    """
    Core service for AI-powered codebase interactions.

    This service handles:
    - Repository indexing and embedding generation
    - Semantic code search
    - AI-powered codebase conversations
    - Context-aware code analysis
    """

    def __init__(self, config, logger_instance=None, database=None):
        self.config = config
        self.logger = logger_instance or get_logger(__name__)
        self.telemetry = get_telemetry()
        self.prompt_builder = PromptBuilder()
        self.database = database or CodeMindDatabase()

    def _content_hash(self, content: str) -> str:
        """Generate SHA-256 hash for content."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    async def index_repository(
        self,
        repo_path: str,
        repo_url: Optional[str] = None,
        repo_name: Optional[str] = None,
        owner: Optional[str] = None,
        branch: str = "main",
    ) -> IndexResult:
        """
        Index a repository for AI-powered interactions.

        Supports both local Git repositories and GitHub URLs as first-class citizens.

        Args:
            repo_path: Local path to the repository or GitHub URL
            repo_url: Optional explicit repo URL (for backward compatibility)
            repo_name: Optional repository name override
            owner: Optional owner override
            branch: Branch name (default: "main")

        Returns:
            IndexResult with operation details
        """
        start_time = time.time()

        # Determine if this is a local path or remote URL
        if is_local_path(repo_path):
            # Handle local repository or file
            path = Path(repo_path).resolve()

            if path.is_file():
                # Single file - find the repository root but index only this file
                local_repo_manager = get_local_repo_manager()
                repo_info = local_repo_manager.get_repository_info(str(path.parent))

                # Use extracted info, but allow overrides
                final_repo_url = repo_url or repo_info["repo_url"]
                final_repo_name = repo_name or repo_info["repo_name"]
                final_owner = owner or repo_info["owner"]
                final_branch = branch if branch != "main" else repo_info["branch"]
                actual_path = str(path)  # Use the specific file path

                self.logger.info(f"Indexing single file: {actual_path}")
                self.logger.info(
                    f"Repository info: {final_owner}/{final_repo_name} (branch: {final_branch})"
                )

            else:
                # Directory - handle as repository or subdirectory
                local_repo_manager = get_local_repo_manager()
                repo_info = local_repo_manager.get_repository_info(repo_path)

                # Use extracted info, but allow overrides
                final_repo_url = repo_url or repo_info["repo_url"]
                final_repo_name = repo_name or repo_info["repo_name"]
                final_owner = owner or repo_info["owner"]
                final_branch = branch if branch != "main" else repo_info["branch"]

                # Check if the requested path is a subdirectory of the repository
                requested_path = Path(repo_path).resolve()
                repo_root = Path(repo_info["local_path"]).resolve()

                if requested_path != repo_root and requested_path.is_relative_to(
                    repo_root
                ):
                    # Index only the requested subdirectory
                    actual_path = str(requested_path)
                    self.logger.info(f"Indexing subdirectory: {actual_path}")
                    self.logger.info(
                        f"Repository info: {final_owner}/{final_repo_name} (branch: {final_branch})"
                    )
                else:
                    # Index the entire repository
                    actual_path = repo_info["local_path"]
                    self.logger.info(f"Indexing local repository: {actual_path}")
                    self.logger.info(
                        f"Repository info: {final_owner}/{final_repo_name} (branch: {final_branch})"
                    )

        elif is_github_url(repo_path):
            # Handle GitHub URL - clone it first
            from utils.remote_repo_manager import get_repo_manager

            repo_manager = get_repo_manager()

            # Clone the repository
            actual_path = repo_manager.clone_repository(repo_path, branch)

            # Get repository info
            github_info = repo_manager.get_repository_info(repo_path)
            final_repo_url = repo_url or repo_path
            final_repo_name = repo_name or github_info["repo_name"]
            final_owner = owner or github_info["owner"]
            final_branch = branch

            self.logger.info(f"Cloned and indexing GitHub repository: {repo_path}")

        else:
            return IndexResult(
                success=False,
                chunks_indexed=0,
                duration=time.time() - start_time,
                message=f"Invalid repository path or URL: {repo_path}",
            )

        with self.telemetry.trace_operation(
            "index_repository",
            {
                "repo_path": actual_path,
                "repo_url": final_repo_url,
                "is_local": is_local_path(repo_path),
            },
        ):
            # Register repository in database
            self.database.register_repository(
                final_repo_url, final_repo_name, final_owner, final_branch
            )

            # Extract code chunks
            with self.telemetry.trace_operation("extract_chunks"):
                # Create chunking config from main config
                chunking_config = ChunkingConfig(
                    max_chunk_size=getattr(self.config, "max_chunk_size", 1000),
                    min_chunk_size=getattr(self.config, "min_chunk_size", 50),
                    overlap_size=getattr(self.config, "chunk_overlap_size", 50),
                )
                chunker = TreeSitterChunker(chunking_config)
                path = Path(actual_path)
                if path.is_file():
                    chunks = chunker.chunk_file(str(path), path.read_text())
                elif path.is_dir():
                    chunks = chunker.chunk_repository(str(path))
                else:
                    return IndexResult(
                        success=False,
                        chunks_indexed=0,
                        duration=time.time() - start_time,
                        message=f"Invalid path: {actual_path}. Must be a file or directory.",
                    )

            self.logger.info(f"Found {len(chunks)} code chunks")
            self.telemetry.update_chunk_count(
                len(chunks), {"operation": "index", "repo": final_repo_url}
            )

            if not chunks:
                return IndexResult(
                    success=False,
                    chunks_indexed=0,
                    duration=time.time() - start_time,
                    message="No code chunks found. Check repository path.",
                )

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
                            try:
                                batch_embeddings = await client.embed_batch(batch)
                                embeddings.extend(batch_embeddings)
                                self.logger.debug(
                                    f"Generated {len(embeddings)} embeddings so far."
                                )
                            except Exception as e:
                                self.logger.error(
                                    f"Failed to generate embeddings for batch {i//batch_size + 1}: {e}"
                                )
                                # If it's a connection error, provide helpful guidance
                                if (
                                    "connection" in str(e).lower()
                                    or "network" in str(e).lower()
                                ):
                                    self.logger.error(
                                        "This appears to be a network/connection issue."
                                    )
                                    self.logger.error(
                                        "If using HuggingFace models, ensure you have internet access for model download."
                                    )
                                    self.logger.error(
                                        "Consider using a local embedding service or OpenAI-compatible API instead."
                                    )
                                raise e

                        embedding_duration = time.time() - embedding_start
                        self.telemetry.record_embedding_duration(
                            embedding_duration, {"chunk_count": len(chunks)}
                        )

                    self.logger.info(f"Generated {len(embeddings)} embeddings")

                    # Convert to CodeChunk objects with embeddings
                    code_chunks = []
                    for i, chunk in enumerate(chunks):
                        content_hash = self._content_hash(chunk.content)

                        # Add repository metadata
                        metadata = {
                            "parent_name": chunk.parent_name,
                            "parent_type": chunk.parent_type,
                            "full_signature": chunk.full_signature,
                            "repo_url": final_repo_url,
                        }

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
                            metadata=metadata,
                        )
                        code_chunks.append(code_chunk)

                    # Store in database
                    with self.telemetry.trace_operation("store_chunks"):
                        success = self.database.store_code_chunks(
                            final_repo_url, code_chunks
                        )

                        if not success:
                            return IndexResult(
                                success=False,
                                chunks_indexed=0,
                                duration=time.time() - start_time,
                                message="Failed to store chunks in database",
                            )

                    self.logger.info(f"Stored {len(code_chunks)} chunks in database")

                    # Generate summaries
                    await self._generate_summaries(code_chunks, client)

                    duration = time.time() - start_time
                    return IndexResult(
                        success=True,
                        chunks_indexed=len(code_chunks),
                        duration=duration,
                        message=f"Successfully indexed {len(code_chunks)} chunks",
                    )

                except Exception as e:
                    self.logger.error(f"Error during indexing: {e}")
                    return IndexResult(
                        success=False,
                        chunks_indexed=0,
                        duration=time.time() - start_time,
                        message=f"Error during indexing: {str(e)}",
                    )

    async def search_codebase(
        self,
        query: str,
        max_results: int = 10,
        score_threshold: float = 0.5,
        repo_filter: Optional[str] = None,
    ) -> SearchResult:
        """
        Search the codebase using semantic similarity.

        Args:
            query: Search query
            max_results: Maximum number of results
            score_threshold: Minimum similarity score
            repo_filter: Optional repository URL filter

        Returns:
            SearchResult with matching code chunks
        """
        start_time = time.time()

        async with LLMClient(config=self.config) as client:
            try:
                # Generate embedding for the query
                query_embedding = await client.embed(query)

                # Search in database
                search_results = self.database.search_similar_code(
                    query_embedding,
                    repo_url=repo_filter,
                    limit=max_results,
                    score_threshold=score_threshold,
                )

                # Convert to response format
                chunks = []
                for result in search_results:
                    chunks.append(
                        {
                            "content": result.content,
                            "file_path": result.metadata.get("file_path", ""),
                            "chunk_type": result.metadata.get("chunk_type", ""),
                            "name": result.metadata.get("name", ""),
                            "start_line": result.metadata.get("start_line", 0),
                            "end_line": result.metadata.get("end_line", 0),
                            "language": result.metadata.get("language", ""),
                            "summary": result.metadata.get("summary"),
                            "score": result.score,
                            "repo_url": result.metadata.get("repo_url"),
                        }
                    )

                duration = time.time() - start_time

                return SearchResult(
                    chunks=chunks,
                    total_results=len(chunks),
                    duration=duration,
                    query=query,
                )

            except Exception as e:
                self.logger.error(f"Error in codebase search: {e}")
                raise

    async def chat_with_codebase(
        self, query: str, max_context: int = 5, repo_filter: Optional[str] = None
    ) -> ConversationResult:
        """
        Have a conversation with the codebase using AI.

        Args:
            query: User's question about the codebase
            max_context: Maximum number of context chunks to use
            repo_filter: Optional repository URL filter

        Returns:
            ConversationResult with AI response and context
        """
        start_time = time.time()

        async with LLMClient(config=self.config) as client:
            try:
                # Generate embedding for the query
                query_embedding = await client.embed(query)

                # Search for relevant code chunks
                search_results = self.database.search_similar_code(
                    query_embedding,
                    repo_url=repo_filter,
                    limit=max_context * 2,  # Get more for reranking
                    score_threshold=0.6,
                )

                self.logger.info(
                    f"Found {len(search_results)} relevant chunks for query: {query}"
                )

                # Rerank results for better relevance
                reranked_results = []
                if search_results:
                    reranker = CodeReranker(client)
                    reranked_results = await reranker.rerank_search_results(
                        query,
                        search_results,
                        top_k=min(max_context, len(search_results)),
                    )

                # Build chat prompt
                chat_prompt = self.prompt_builder.build_chat_prompt(
                    query=query, context_chunks=reranked_results
                )

                # Generate response
                response = await client.complete(
                    [{"role": "user", "content": chat_prompt}]
                )

                # Format context chunks for response
                context_chunks = []
                for result in reranked_results:
                    chunk_data = result.result
                    context_chunks.append(
                        {
                            "content": (
                                chunk_data.content[:500] + "..."
                                if len(chunk_data.content) > 500
                                else chunk_data.content
                            ),
                            "file_path": chunk_data.metadata.get("file_path", ""),
                            "chunk_type": chunk_data.metadata.get("chunk_type", ""),
                            "name": chunk_data.metadata.get("name", ""),
                            "start_line": chunk_data.metadata.get("start_line", 0),
                            "end_line": chunk_data.metadata.get("end_line", 0),
                            "score": result.score,
                            "repo_url": chunk_data.metadata.get("repo_url"),
                        }
                    )

                duration = time.time() - start_time

                return ConversationResult(
                    answer=response,
                    context_chunks=context_chunks,
                    duration=duration,
                    query=query,
                )

            except Exception as e:
                self.logger.error(f"Error in codebase conversation: {e}")
                raise

    async def _generate_summaries(
        self, code_chunks: List[CodeChunk], client: LLMClient
    ):
        """Generate summaries for code chunks."""
        try:
            with self.telemetry.trace_operation("generate_summaries"):
                self.logger.info("Generating code summaries...")

                # Create a temporary knowledge graph for summarization
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
                    summaries = await summarizer.summarize_chunks_batch(chunk_hashes)
                    self.logger.info(f"Generated {len(summaries)} code summaries")

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
                        self.logger.warning("Failed to update chunks with summaries")
                else:
                    self.logger.info("No chunks found to summarize")

        except Exception as e:
            self.logger.error(f"Error generating summaries: {e}", exc_info=True)
            self.logger.warning("Continuing without summaries...")

    async def get_repository_stats(
        self, repo_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get statistics about indexed repositories."""
        if repo_url:
            # Get stats for specific repository
            return self.database.get_repository_stats(repo_url)
        else:
            # Get stats for all repositories
            repositories = self.database.list_repositories()
            total_chunks = sum(repo.chunk_count for repo in repositories)

            return {
                "total_repositories": len(repositories),
                "total_chunks": total_chunks,
                "repositories": [
                    {
                        "repo_url": repo.repo_url,
                        "repo_name": repo.repo_name,
                        "owner": repo.owner,
                        "chunk_count": repo.chunk_count,
                        "indexed_at": repo.indexed_at,
                    }
                    for repo in repositories
                ],
                "supported_languages": [
                    "python",
                    "javascript",
                    "typescript",
                    "java",
                    "go",
                ],
            }

    def list_repositories(self) -> List[RepositoryInfo]:
        """List all indexed repositories."""
        return self.database.list_repositories()

    def delete_repository(self, repo_url: str) -> bool:
        """Delete a repository and all its data."""
        return self.database.delete_repository(repo_url)
