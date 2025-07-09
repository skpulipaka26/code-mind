"""
Core review service that handles indexing and reviewing operations.
This service is used by both CLI and main.py entry points.
"""

import os
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
import pickle

from graph_engine.knowledge_graph import KnowledgeGraph
from graph_engine.graph_builder import GraphBuilder
from graph_engine.summarizer import HierarchicalSummarizer
from graph_engine.search import Search

from core.chunker import TreeSitterChunker
from core.vectordb import VectorDatabase
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
    """Core service for code review operations."""
    
    def __init__(self, config, logger_instance=None):
        self.config = config
        self.logger = logger_instance or get_logger(__name__)
        self.telemetry = get_telemetry()
        self.prompt_builder = PromptBuilder()
    
    async def index_repository(self, repo_path: str, output: str = "vector_db") -> bool:
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

            # Build Knowledge Graph
            try:
                with self.telemetry.trace_operation("build_knowledge_graph"):
                    kg = KnowledgeGraph()
                    builder = GraphBuilder(kg)
                    builder.build_graph_from_chunks(chunks)
                    graph_path = Path(self.config.vector_db_path) / f"{output}.graph"
                    os.makedirs(os.path.dirname(graph_path), exist_ok=True)
                    with open(graph_path, "wb") as f:
                        pickle.dump(kg, f)
                    self.logger.info(f"Knowledge Graph built and saved to {graph_path}")
            except Exception as e:
                self.logger.error(f"Error building or saving Knowledge Graph: {e}", exc_info=True)
                return False

            # Generate embeddings
            async with LLMClient(config=self.config) as client:
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
                    db = VectorDatabase(dimension=self.config.vector_dimension)
                    db.add_chunks(chunks, embeddings)
                    db.save(str(Path(self.config.vector_db_path) / output))
                self.logger.info(f"Repository indexed successfully as '{output}'")
                return True
            except Exception as e:
                self.logger.error(f"Error saving index: {e}", exc_info=True)
                return False
    
    async def review_diff(
        self, 
        diff_file: str, 
        index: str = "vector_db", 
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
                    db = VectorDatabase(dimension=self.config.vector_dimension)
                    db_path = str(Path(self.config.vector_db_path) / index)
                    db.load(db_path)
                self.logger.info(f"Loaded index '{index}' with {len(db.metadata)} chunks")
            except Exception as e:
                self.logger.error(f"Error loading index '{index}': {e}")
                return None

            # Load Knowledge Graph
            kg = None
            try:
                graph_path = Path(self.config.vector_db_path) / f"{index}.graph"
                if graph_path.exists():
                    with open(graph_path, "rb") as f:
                        kg = pickle.load(f)
                    self.logger.info(f"Loaded Knowledge Graph from {graph_path}")
                else:
                    self.logger.warning(f"Knowledge Graph not found at {graph_path}")
            except Exception as e:
                self.logger.error(f"Error loading Knowledge Graph: {e}")

            # Initialize GraphRAG components
            summarizer = None
            search_engine = None
            if kg:
                summarizer = HierarchicalSummarizer(kg)
                search_engine = Search(kg)

            # Search and review
            async with LLMClient(config=self.config) as client:
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

                        # Add content to reranked results and log info
                        self.logger.info(f"Retrieved {len(reranked_results)} reranked chunks:")
                        for i, result in enumerate(reranked_results):
                            result.content = db.get_content(result.metadata.chunk_id)
                            self.logger.info(f"  {i+1}. {result.metadata.file_path}:{result.metadata.chunk_type} '{result.metadata.name}' (score: {result.score:.3f})")
                            if hasattr(result.metadata, 'parent_name') and result.metadata.parent_name:
                                self.logger.info(f"      Parent: {result.metadata.parent_type} '{result.metadata.parent_name}'")
                            if hasattr(result.metadata, 'full_signature') and result.metadata.full_signature:
                                self.logger.info(f"      Signature: {result.metadata.full_signature}")
                            self.logger.debug(f"      Content: {result.content[:150]}...")

                    # --- GraphRAG Context Enrichment ---
                    graph_context = []
                    if kg and search_engine and summarizer:
                        self.logger.info("Enriching context with Knowledge Graph...")
                        processed_chunks = 0
                        for changed_chunk in changed_chunks[:10]:  # Limit to first 10 for logging
                            # Try to find the corresponding node in the graph
                            node_id_prefix = f"{changed_chunk.chunk.chunk_type}_{changed_chunk.chunk.name or ''}_{changed_chunk.chunk.file_path}_{changed_chunk.chunk.start_line}"
                            matching_nodes = [n for n in kg.graph.nodes if n.startswith(node_id_prefix)]

                            if matching_nodes:
                                changed_node_id = matching_nodes[0]
                                self.logger.info(f"Found graph node for {changed_chunk.chunk.file_path}:{changed_chunk.chunk.chunk_type} '{changed_chunk.chunk.name}'")
                                
                                # Perform local search around the changed chunk
                                local_search_results = search_engine.local_search(changed_node_id, query, depth=1)
                                self.logger.info(f"  Local search returned {len(local_search_results)} related nodes")
                                for res in local_search_results:
                                    graph_context.append(res['attributes'].get('content', ''))
                                
                                # Get community summary if available
                                communities = kg.detect_communities()
                                if communities:
                                    for comm_id, nodes in communities.items():
                                        if changed_node_id in nodes:
                                            self.logger.info(f"  Found in community {comm_id} with {len(nodes)} nodes")
                                            community_summary = await summarizer.summarize_community(nodes)
                                            graph_context.append(community_summary)
                                            break
                                processed_chunks += 1
                            else:
                                self.logger.debug(f"No graph node found for changed chunk: {changed_chunk.chunk.file_path}:{changed_chunk.chunk.start_line}")
                        
                        self.logger.info(f"Graph enrichment complete: processed {processed_chunks} chunks, added {len(graph_context)} context items")

                    # Generate review using PromptBuilder
                    self.logger.info("Building review prompt...")
                    review_prompt = self.prompt_builder.build_review_prompt(
                        diff_content=diff_content,
                        context_chunks=reranked_results,
                        changed_chunks=changed_chunks,
                        graph_context=graph_context # Pass graph-enriched context
                    )
                    self.logger.info(f"Generated prompt: {len(review_prompt)} characters")
                    self.logger.info(f"  Diff content: {len(diff_content)} chars")
                    self.logger.info(f"  Context chunks: {len(reranked_results)}")
                    self.logger.info(f"  Changed chunks: {len(changed_chunks)}")
                    self.logger.info(f"  Graph context items: {len(graph_context)}")

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

        async with LLMClient(config=self.config) as client:
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