"""
Multi-repository database interface with proper isolation and management.
This is the main database interface that natively supports multiple repositories.
"""

import hashlib
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from urllib.parse import urlparse
from storage.vector_store import QdrantVectorStore, VectorSearchResult
from storage.graph_store import Neo4jGraphStore, GraphNode
from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class CodeChunk:
    content_hash: str
    content: str
    chunk_type: str
    file_path: str
    language: str
    name: str
    start_line: int
    end_line: int
    embedding: Optional[List[float]] = None
    summary: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class RepositoryInfo:
    repo_url: str
    repo_name: str
    owner: str
    branch: str
    indexed_at: str
    chunk_count: int
    collection_name: str  # Qdrant collection name
    graph_label: str  # Neo4j label for isolation


class CodeMindDatabase:
    def __init__(
        self,
        # Qdrant config
        qdrant_host: str = "localhost",
        qdrant_port: int = 6333,
        # Neo4j config
        neo4j_uri: str = "bolt://localhost:7687",
        neo4j_user: str = "neo4j",
        neo4j_password: str = "turbo-review-password",
    ):
        self.qdrant_host = qdrant_host
        self.qdrant_port = qdrant_port
        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password

        # Main graph store for repository metadata
        self.main_graph_store = Neo4jGraphStore(neo4j_uri, neo4j_user, neo4j_password)

        # Cache for repository-specific stores
        self._vector_stores: Dict[str, QdrantVectorStore] = {}
        self._graph_stores: Dict[str, Neo4jGraphStore] = {}

        # Initialize repository tracking
        self._ensure_repository_tracking()

    def _ensure_repository_tracking(self):
        with self.main_graph_store.driver.session() as session:
            # Create repository tracking constraints and indexes
            constraints = [
                "CREATE CONSTRAINT repo_url_unique IF NOT EXISTS FOR (r:Repository) REQUIRE r.repo_url IS UNIQUE",
                "CREATE INDEX repo_name_index IF NOT EXISTS FOR (r:Repository) ON (r.repo_name)",
                "CREATE INDEX repo_owner_index IF NOT EXISTS FOR (r:Repository) ON (r.owner)",
            ]

            for constraint in constraints:
                try:
                    session.run(constraint)
                except Exception as e:
                    logger.debug(f"Repository constraint already exists: {e}")

    def _get_repo_identifier(self, repo_url: str) -> str:
        """Generate a unique identifier for a repository."""
        if "github.com" in repo_url:
            # Parse GitHub URL to get owner/repo
            parsed = urlparse(repo_url)
            path = parsed.path.strip("/").replace(".git", "")
            parts = path.split("/")
            if len(parts) >= 2:
                owner, repo = parts[0], parts[1]
                # Create safe identifier
                identifier = f"{owner}_{repo}".lower()
                # Replace special characters
                identifier = "".join(
                    c if c.isalnum() or c == "_" else "_" for c in identifier
                )
                return identifier
        elif repo_url.startswith("file://"):
            # For local file URLs, create identifier from path
            from pathlib import Path

            path = repo_url.replace("file://", "")
            path_obj = Path(path)
            # Use directory name and hash for uniqueness
            dir_name = path_obj.name.lower()
            path_hash = hashlib.sha256(str(path_obj).encode()).hexdigest()[:8]
            identifier = f"local_{dir_name}_{path_hash}"
            # Replace special characters
            identifier = "".join(
                c if c.isalnum() or c == "_" else "_" for c in identifier
            )
            return identifier

        # Fallback: hash the URL
        return hashlib.sha256(repo_url.encode()).hexdigest()[:16]

    def _get_vector_store(self, repo_url: str) -> QdrantVectorStore:
        repo_id = self._get_repo_identifier(repo_url)
        collection_name = f"repo_{repo_id}"

        if collection_name not in self._vector_stores:
            self._vector_stores[collection_name] = QdrantVectorStore(
                host=self.qdrant_host,
                port=self.qdrant_port,
                collection_name=collection_name,
            )
            logger.info(f"Created vector store for repository: {collection_name}")

        return self._vector_stores[collection_name]

    def _get_graph_store(self, repo_url: str) -> Neo4jGraphStore:
        repo_id = self._get_repo_identifier(repo_url)

        if repo_id not in self._graph_stores:
            # Use same Neo4j instance but with repository-specific operations
            self._graph_stores[repo_id] = Neo4jGraphStore(
                self.neo4j_uri, self.neo4j_user, self.neo4j_password
            )
            logger.info(f"Created graph store for repository: {repo_id}")

        return self._graph_stores[repo_id]

    def register_repository(
        self, repo_url: str, repo_name: str, owner: str, branch: str = "main"
    ) -> RepositoryInfo:
        """Register a new repository in the system."""
        repo_id = self._get_repo_identifier(repo_url)
        collection_name = f"repo_{repo_id}"
        graph_label = f"Repo_{repo_id}"

        # Store repository metadata
        with self.main_graph_store.driver.session() as session:
            query = """
            MERGE (r:Repository {repo_url: $repo_url})
            SET r.repo_name = $repo_name,
                r.owner = $owner,
                r.branch = $branch,
                r.repo_id = $repo_id,
                r.collection_name = $collection_name,
                r.graph_label = $graph_label,
                r.indexed_at = datetime(),
                r.chunk_count = 0
            RETURN r
            """

            session.run(
                query,
                repo_url=repo_url,
                repo_name=repo_name,
                owner=owner,
                branch=branch,
                repo_id=repo_id,
                collection_name=collection_name,
                graph_label=graph_label,
            )

        return RepositoryInfo(
            repo_url=repo_url,
            repo_name=repo_name,
            owner=owner,
            branch=branch,
            indexed_at="",  # Will be set when indexing
            chunk_count=0,
            collection_name=collection_name,
            graph_label=graph_label,
        )

    def store_code_chunks(self, repo_url: str, chunks: List[CodeChunk]) -> bool:
        try:
            # Get repository-specific stores
            vector_store = self._get_vector_store(repo_url)
            graph_store = self._get_graph_store(repo_url)
            repo_id = self._get_repo_identifier(repo_url)
            graph_label = f"Repo_{repo_id}"

            # Prepare data with repository context
            vector_data = []
            graph_nodes = []

            for chunk in chunks:
                # Add repository context to content hash to avoid conflicts
                repo_content_hash = f"{repo_id}_{chunk.content_hash}"

                if chunk.embedding:
                    # Vector store data
                    vector_data.append(
                        {
                            "content_hash": repo_content_hash,
                            "vector": chunk.embedding,
                            "content": chunk.content,
                            "metadata": {
                                "chunk_type": chunk.chunk_type,
                                "file_path": chunk.file_path,
                                "language": chunk.language,
                                "name": chunk.name,
                                "start_line": chunk.start_line,
                                "end_line": chunk.end_line,
                                "summary": chunk.summary,
                                "repo_url": repo_url,
                                "repo_id": repo_id,
                                **(chunk.metadata or {}),
                            },
                        }
                    )

                # Graph store data with repository label
                labels = ["CodeChunk", chunk.chunk_type.title(), graph_label]
                if chunk.chunk_type == "file":
                    labels = ["File", graph_label]

                graph_nodes.append(
                    GraphNode(
                        id=repo_content_hash,
                        labels=labels,
                        properties={
                            "content_hash": repo_content_hash,
                            "original_hash": chunk.content_hash,
                            "content": chunk.content,
                            "chunk_type": chunk.chunk_type,
                            "file_path": chunk.file_path,
                            "language": chunk.language,
                            "name": chunk.name,
                            "start_line": chunk.start_line,
                            "end_line": chunk.end_line,
                            "summary": chunk.summary,
                            "repo_url": repo_url,
                            "repo_id": repo_id,
                            **(chunk.metadata or {}),
                        },
                    )
                )

            # Store in repository-specific databases
            vector_success = True
            if vector_data:
                vector_success = vector_store.store_vectors(vector_data)

            graph_success = graph_store.store_nodes(graph_nodes)

            # Update repository chunk count
            if vector_success and graph_success:
                self._update_repository_stats(repo_url, len(chunks))

            return vector_success and graph_success

        except Exception as e:
            logger.error(f"Error storing code chunks for {repo_url}: {e}")
            return False

    def search_similar_code(
        self,
        query_embedding: List[float],
        repo_url: Optional[str] = None,
        limit: int = 10,
        score_threshold: float = 0.7,
    ) -> List[VectorSearchResult]:
        """Search for similar code, optionally filtered by repository."""
        if repo_url:
            # Search in specific repository
            vector_store = self._get_vector_store(repo_url)
            return vector_store.search_similar(
                query_embedding, limit, None, score_threshold
            )
        else:
            # Search across all repositories
            all_results = []

            # Get all repositories
            repositories = self.list_repositories()

            for repo_info in repositories:
                try:
                    vector_store = self._get_vector_store(repo_info.repo_url)
                    results = vector_store.search_similar(
                        query_embedding, limit, None, score_threshold
                    )
                    all_results.extend(results)
                except Exception as e:
                    logger.warning(f"Error searching in {repo_info.repo_url}: {e}")

            # Sort by score and limit
            all_results.sort(key=lambda x: x.score, reverse=True)
            return all_results[:limit]

    def list_repositories(self) -> List[RepositoryInfo]:
        with self.main_graph_store.driver.session() as session:
            query = """
            MATCH (r:Repository)
            RETURN r.repo_url as repo_url, r.repo_name as repo_name, 
                   r.owner as owner, r.branch as branch, r.indexed_at as indexed_at,
                   r.chunk_count as chunk_count, r.collection_name as collection_name,
                   r.graph_label as graph_label
            ORDER BY r.indexed_at DESC
            """
            result = session.run(query)
            repositories = []

            for record in result:
                repositories.append(
                    RepositoryInfo(
                        repo_url=record["repo_url"],
                        repo_name=record["repo_name"],
                        owner=record["owner"],
                        branch=record["branch"],
                        indexed_at=(
                            str(record["indexed_at"]) if record["indexed_at"] else ""
                        ),
                        chunk_count=record["chunk_count"] or 0,
                        collection_name=record["collection_name"],
                        graph_label=record["graph_label"],
                    )
                )

            return repositories

    def delete_repository(self, repo_url: str) -> bool:
        try:
            repo_id = self._get_repo_identifier(repo_url)

            # Delete from vector store
            vector_store = self._get_vector_store(repo_url)
            collection_name = f"repo_{repo_id}"

            # Delete Qdrant collection
            try:
                vector_store.client.delete_collection(collection_name)
                logger.info(f"Deleted Qdrant collection: {collection_name}")
            except Exception as e:
                logger.warning(f"Error deleting Qdrant collection: {e}")

            # Delete from graph store
            graph_label = f"Repo_{repo_id}"
            with self.main_graph_store.driver.session() as session:
                # Delete all nodes with repository label
                query = f"MATCH (n:{graph_label}) DETACH DELETE n"
                session.run(query)

                # Delete repository metadata
                query = "MATCH (r:Repository {repo_url: $repo_url}) DELETE r"
                session.run(query, repo_url=repo_url)

            # Clean up caches
            if collection_name in self._vector_stores:
                del self._vector_stores[collection_name]
            if repo_id in self._graph_stores:
                self._graph_stores[repo_id].close()
                del self._graph_stores[repo_id]

            logger.info(f"Deleted repository: {repo_url}")
            return True

        except Exception as e:
            logger.error(f"Error deleting repository {repo_url}: {e}")
            return False

    def get_repository_stats(self, repo_url: str) -> Dict[str, Any]:
        try:
            vector_store = self._get_vector_store(repo_url)
            repo_id = self._get_repo_identifier(repo_url)

            # Get vector stats
            vector_stats = vector_store.get_collection_info()

            # Get graph stats
            graph_label = f"Repo_{repo_id}"
            with self.main_graph_store.driver.session() as session:
                query = f"""
                MATCH (n:{graph_label})
                RETURN count(n) as total_nodes,
                       count(CASE WHEN 'Function' IN labels(n) THEN 1 END) as functions,
                       count(CASE WHEN 'Class' IN labels(n) THEN 1 END) as classes,
                       count(CASE WHEN 'File' IN labels(n) THEN 1 END) as files
                """
                result = session.run(query)
                record = result.single()

                graph_stats = {
                    "total_nodes": record["total_nodes"],
                    "functions": record["functions"],
                    "classes": record["classes"],
                    "files": record["files"],
                }

            return {
                "repo_url": repo_url,
                "vector_stats": vector_stats,
                "graph_stats": graph_stats,
            }

        except Exception as e:
            logger.error(f"Error getting stats for {repo_url}: {e}")
            return {}

    def _update_repository_stats(self, repo_url: str, chunk_count: int):
        with self.main_graph_store.driver.session() as session:
            query = """
            MATCH (r:Repository {repo_url: $repo_url})
            SET r.chunk_count = $chunk_count, r.indexed_at = datetime()
            """
            session.run(query, repo_url=repo_url, chunk_count=chunk_count)

    def health_check(self) -> Dict[str, bool]:
        try:
            # Check main graph store
            graph_health = self.main_graph_store.health_check()

            # Check a sample vector store
            vector_health = True
            try:
                from qdrant_client import QdrantClient

                client = QdrantClient(host=self.qdrant_host, port=self.qdrant_port)
                client.get_collections()
            except Exception:
                vector_health = False

            return {
                "graph_db": graph_health,
                "vector_db": vector_health,
                "multi_repo_system": graph_health and vector_health,
            }

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {"graph_db": False, "vector_db": False, "multi_repo_system": False}

    def close(self):
        # Close main graph store
        self.main_graph_store.close()

        # Close all repository-specific stores
        for store in self._graph_stores.values():
            store.close()

        # Clear caches
        self._vector_stores.clear()
        self._graph_stores.clear()
