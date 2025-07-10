"""
Unified database interface combining vector and graph storage.
"""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from storage.vector_store import QdrantVectorStore, VectorSearchResult
from storage.graph_store import Neo4jGraphStore, GraphNode, GraphRelationship
from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class CodeChunk:
    """Represents a code chunk with all its data."""

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


class TurboReviewDatabase:
    """Unified interface for vector and graph databases."""

    def __init__(
        self,
        # Qdrant config
        qdrant_host: str = "localhost",
        qdrant_port: int = 6333,
        collection_name: str = "turbo_review",
        # Neo4j config
        neo4j_uri: str = "bolt://localhost:7687",
        neo4j_user: str = "neo4j",
        neo4j_password: str = "turbo-review-password",
    ):
        self.vector_store = QdrantVectorStore(qdrant_host, qdrant_port, collection_name)
        self.graph_store = Neo4jGraphStore(neo4j_uri, neo4j_user, neo4j_password)

    def store_code_chunks(self, chunks: List[CodeChunk]) -> bool:
        """Store code chunks in both vector and graph databases."""
        try:
            # Prepare vector data
            vector_data = []
            graph_nodes = []

            for chunk in chunks:
                if chunk.embedding:
                    # Vector store data
                    vector_data.append(
                        {
                            "content_hash": chunk.content_hash,
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
                                **(chunk.metadata or {}),
                            },
                        }
                    )

                # Graph store data
                labels = ["CodeChunk", chunk.chunk_type.title()]
                if chunk.chunk_type == "file":
                    labels = ["File"]

                graph_nodes.append(
                    GraphNode(
                        id=chunk.content_hash,
                        labels=labels,
                        properties={
                            "content_hash": chunk.content_hash,
                            "content": chunk.content,
                            "chunk_type": chunk.chunk_type,
                            "file_path": chunk.file_path,
                            "language": chunk.language,
                            "name": chunk.name,
                            "start_line": chunk.start_line,
                            "end_line": chunk.end_line,
                            "summary": chunk.summary,
                            **(chunk.metadata or {}),
                        },
                    )
                )

            # Store in both databases
            vector_success = True
            if vector_data:
                vector_success = self.vector_store.store_vectors(vector_data)

            graph_success = self.graph_store.store_nodes(graph_nodes)

            return vector_success and graph_success

        except Exception as e:
            logger.error(f"Error storing code chunks: {e}")
            return False

    def store_relationships(
        self, relationships: List[Tuple[str, str, str, Dict[str, Any]]]
    ) -> bool:
        """
        Store relationships between code chunks.

        Args:
            relationships: List of (from_hash, to_hash, relationship_type, properties)
        """
        try:
            graph_relationships = [
                GraphRelationship(
                    start_node=from_hash,
                    end_node=to_hash,
                    type=rel_type,
                    properties=props,
                )
                for from_hash, to_hash, rel_type, props in relationships
            ]

            return self.graph_store.store_relationships(graph_relationships)

        except Exception as e:
            logger.error(f"Error storing relationships: {e}")
            return False

    def search_similar_code(
        self,
        query_embedding: List[float],
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        score_threshold: float = 0.7,
    ) -> List[VectorSearchResult]:
        """Search for similar code using vector similarity."""
        return self.vector_store.search_similar(
            query_embedding, limit, filters, score_threshold
        )

    def get_code_chunk(self, content_hash: str) -> Optional[CodeChunk]:
        """Get a code chunk by its content hash."""
        # Try vector store first (has embeddings)
        vector_result = self.vector_store.get_by_hash(content_hash)
        if vector_result:
            return CodeChunk(
                content_hash=vector_result.content_hash,
                content=vector_result.content,
                chunk_type=vector_result.metadata.get("chunk_type", ""),
                file_path=vector_result.metadata.get("file_path", ""),
                language=vector_result.metadata.get("language", ""),
                name=vector_result.metadata.get("name", ""),
                start_line=vector_result.metadata.get("start_line", 0),
                end_line=vector_result.metadata.get("end_line", 0),
                summary=vector_result.metadata.get("summary"),
                metadata=vector_result.metadata,
            )

        # Fallback to graph store
        graph_node = self.graph_store.get_node(content_hash)
        if graph_node:
            props = graph_node.properties
            return CodeChunk(
                content_hash=props.get("content_hash", ""),
                content=props.get("content", ""),
                chunk_type=props.get("chunk_type", ""),
                file_path=props.get("file_path", ""),
                language=props.get("language", ""),
                name=props.get("name", ""),
                start_line=props.get("start_line", 0),
                end_line=props.get("end_line", 0),
                summary=props.get("summary"),
                metadata=props,
            )

        return None

    def get_related_chunks(
        self, content_hash: str, relationship_types: Optional[List[str]] = None
    ) -> List[CodeChunk]:
        """Get chunks related to a given chunk through graph relationships."""
        neighbors = self.graph_store.get_neighbors(content_hash, relationship_types)

        chunks = []
        for neighbor in neighbors:
            chunk = self.get_code_chunk(neighbor.id)
            if chunk:
                chunks.append(chunk)

        return chunks

    def get_file_chunks(self, file_path: str) -> List[CodeChunk]:
        """Get all chunks belonging to a file."""
        nodes = self.graph_store.find_nodes_by_property(
            "CodeChunk", "file_path", file_path
        )

        chunks = []
        for node in nodes:
            chunk = self.get_code_chunk(node.id)
            if chunk:
                chunks.append(chunk)

        return chunks

    def chunk_exists(self, content_hash: str) -> bool:
        """Check if a chunk exists in the database."""
        return (
            self.vector_store.exists(content_hash)
            or self.graph_store.get_node(content_hash) is not None
        )

    def get_database_stats(self) -> Dict[str, Any]:
        """Get statistics about both databases."""
        vector_stats = self.vector_store.get_collection_info()
        graph_stats = self.graph_store.get_stats()

        return {"vector_db": vector_stats, "graph_db": graph_stats}

    def health_check(self) -> Dict[str, bool]:
        """Check health of both databases."""
        return {
            "vector_db": self.vector_store.health_check(),
            "graph_db": self.graph_store.health_check(),
        }

    def close(self):
        """Close database connections."""
        self.graph_store.close()
        # Qdrant client doesn't need explicit closing
