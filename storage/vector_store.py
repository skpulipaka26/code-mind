"""
Vector database interface using Qdrant for production-grade vector storage.
"""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
import hashlib
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
    SearchRequest,
    UpdateStatus,
)
from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class VectorSearchResult:
    """Result from vector similarity search."""

    content_hash: str
    score: float
    metadata: Dict[str, Any]
    content: str


class QdrantVectorStore:
    """Production vector store using Qdrant."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        collection_name: str = "turbo_review",
    ):
        self.client = QdrantClient(host=host, port=port)
        self.collection_name = collection_name
        self.vector_size = 768  # For microsoft/unixcoder-base model

        # Create collection if it doesn't exist
        self._ensure_collection()

    def _ensure_collection(self):
        """Create collection if it doesn't exist."""
        try:
            collections = self.client.get_collections()
            collection_names = [c.name for c in collections.collections]

            if self.collection_name not in collection_names:
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=self.vector_size, distance=Distance.COSINE
                    ),
                )
                logger.info(f"Created Qdrant collection: {self.collection_name}")
            else:
                logger.info(f"Using existing Qdrant collection: {self.collection_name}")

        except Exception as e:
            logger.error(f"Error setting up Qdrant collection: {e}")
            raise

    def store_vectors(self, vectors_data: List[Dict[str, Any]]) -> bool:
        """
        Store vectors with metadata.

        Args:
            vectors_data: List of dicts with keys: content_hash, vector, metadata, content
        """
        try:
            points = []
            for data in vectors_data:
                # Convert content_hash to numeric ID for Qdrant
                numeric_id = int(
                    hashlib.sha256(data["content_hash"].encode()).hexdigest()[:15], 16
                )

                point = PointStruct(
                    id=numeric_id,
                    vector=data["vector"],
                    payload={
                        "content": data["content"],
                        "content_hash": data["content_hash"],
                        **data["metadata"],
                    },
                )
                points.append(point)

            result = self.client.upsert(
                collection_name=self.collection_name, points=points
            )

            if result.status == UpdateStatus.COMPLETED:
                logger.info(f"Stored {len(points)} vectors in Qdrant")
                return True
            else:
                logger.error(f"Failed to store vectors: {result}")
                return False

        except Exception as e:
            logger.error(f"Error storing vectors: {e}")
            return False

    def search_similar(
        self,
        query_vector: List[float],
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        score_threshold: float = 0.0,
    ) -> List[VectorSearchResult]:
        """
        Search for similar vectors.

        Args:
            query_vector: Query embedding
            limit: Maximum results to return
            filters: Optional metadata filters
            score_threshold: Minimum similarity score
        """
        try:
            # Build filter conditions
            filter_conditions = None
            if filters:
                conditions = []
                for key, value in filters.items():
                    conditions.append(
                        FieldCondition(key=key, match=MatchValue(value=value))
                    )
                if conditions:
                    filter_conditions = Filter(must=conditions)

            # Perform search
            search_result = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                query_filter=filter_conditions,
                limit=limit,
                score_threshold=score_threshold,
                with_payload=True,
            )

            # Convert to our result format
            results = []
            for hit in search_result:
                result = VectorSearchResult(
                    content_hash=hit.payload["content_hash"],
                    score=hit.score,
                    metadata={
                        k: v
                        for k, v in hit.payload.items()
                        if k not in ["content", "content_hash"]
                    },
                    content=hit.payload["content"],
                )
                results.append(result)

            logger.debug(f"Found {len(results)} similar vectors")
            return results

        except Exception as e:
            logger.error(f"Error searching vectors: {e}")
            return []

    def get_by_hash(self, content_hash: str) -> Optional[VectorSearchResult]:
        """Get vector data by content hash."""
        try:
            # Convert content_hash to numeric ID
            numeric_id = int(hashlib.sha256(content_hash.encode()).hexdigest()[:15], 16)

            result = self.client.retrieve(
                collection_name=self.collection_name,
                ids=[numeric_id],
                with_payload=True,
            )

            if result:
                hit = result[0]
                return VectorSearchResult(
                    content_hash=hit.payload["content_hash"],
                    score=1.0,  # Exact match
                    metadata={
                        k: v
                        for k, v in hit.payload.items()
                        if k not in ["content", "content_hash"]
                    },
                    content=hit.payload["content"],
                )
            return None

        except Exception as e:
            logger.error(f"Error retrieving vector {content_hash}: {e}")
            return None

    def exists(self, content_hash: str) -> bool:
        """Check if a vector exists by content hash."""
        try:
            # Convert content_hash to numeric ID
            numeric_id = int(hashlib.sha256(content_hash.encode()).hexdigest()[:15], 16)

            result = self.client.retrieve(
                collection_name=self.collection_name, ids=[numeric_id]
            )
            return len(result) > 0
        except Exception as e:
            logger.error(f"Error checking existence of {content_hash}: {e}")
            return False

    def delete_by_filter(self, filters: Dict[str, Any]) -> bool:
        """Delete vectors matching filters."""
        try:
            conditions = []
            for key, value in filters.items():
                conditions.append(
                    FieldCondition(key=key, match=MatchValue(value=value))
                )

            if conditions:
                filter_conditions = Filter(must=conditions)
                result = self.client.delete(
                    collection_name=self.collection_name,
                    points_selector=filter_conditions,
                )
                logger.info(f"Deleted vectors matching filters: {filters}")
                return result.status == UpdateStatus.COMPLETED
            return False

        except Exception as e:
            logger.error(f"Error deleting vectors: {e}")
            return False

    def get_collection_info(self) -> Dict[str, Any]:
        """Get information about the collection."""
        try:
            info = self.client.get_collection(self.collection_name)
            return {
                "name": info.config.params.vectors.size,
                "vectors_count": info.vectors_count,
                "indexed_vectors_count": info.indexed_vectors_count,
                "points_count": info.points_count,
                "status": info.status,
            }
        except Exception as e:
            logger.error(f"Error getting collection info: {e}")
            return {}

    def health_check(self) -> bool:
        """Check if Qdrant is healthy."""
        try:
            collections = self.client.get_collections()
            return True
        except Exception as e:
            logger.error(f"Qdrant health check failed: {e}")
            return False
