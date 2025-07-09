import os
import pickle
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
import numpy as np
import faiss
from core.chunker import CodeChunk
from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class VectorMetadata:
    chunk_id: str
    file_path: str
    start_line: int
    end_line: int
    chunk_type: str
    name: Optional[str] = None
    language: str = "python"


class VectorDatabase:
    """Simple FAISS vector database for code chunks."""

    def __init__(self, dimension: int = 1024):
        self.dimension = dimension
        self.index = faiss.IndexFlatIP(dimension)
        self.metadata: List[VectorMetadata] = []
        self.chunk_contents: Dict[str, str] = {}

    def add_chunks(self, chunks: List[CodeChunk], embeddings: List[List[float]]):
        """Add chunks with embeddings to database."""
        if len(chunks) != len(embeddings):
            logger.error("Chunks and embeddings must have same length")
            raise ValueError("Chunks and embeddings must have same length")

        logger.info(f"Adding {len(chunks)} chunks to vector database.")

        # Normalize and add embeddings
        embeddings_array = np.array(embeddings, dtype=np.float32)
        faiss.normalize_L2(embeddings_array)
        self.index.add(embeddings_array)

        # Store metadata and content
        for chunk in chunks:
            chunk_id = f"{chunk.file_path}:{chunk.start_line}:{chunk.end_line}"
            metadata = VectorMetadata(
                chunk_id=chunk_id,
                file_path=chunk.file_path,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                chunk_type=chunk.chunk_type,
                name=chunk.name,
                language=chunk.language,
            )
            self.metadata.append(metadata)
            self.chunk_contents[chunk_id] = chunk.content

    def search(
        self, query_embedding: List[float], k: int = 10
    ) -> List[Tuple[VectorMetadata, float]]:
        """Search for similar chunks."""
        if self.index.ntotal == 0:
            return []

        # Normalize and search
        query_array = np.array([query_embedding], dtype=np.float32)
        faiss.normalize_L2(query_array)
        scores, indices = self.index.search(query_array, k)

        # Return results
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < len(self.metadata):
                results.append((self.metadata[idx], float(score)))

        return results

    def get_content(self, chunk_id: str) -> Optional[str]:
        """Get content for a chunk."""
        return self.chunk_contents.get(chunk_id)

    def save(self, path: str):
        """Save database to disk."""
        try:
            faiss.write_index(self.index, f"{path}.faiss")
            with open(f"{path}.pkl", "wb") as f:
                pickle.dump(
                    {"metadata": self.metadata, "chunk_contents": self.chunk_contents},
                    f,
                )
            logger.info(f"Vector database saved to {path}.faiss and {path}.pkl")
        except Exception as e:
            logger.error(f"Error saving vector database: {e}", exc_info=True)

    def load(self, path: str):
        """Load database from disk."""
        try:
            if os.path.exists(f"{path}.faiss"):
                self.index = faiss.read_index(f"{path}.faiss")
                logger.info(f"Loaded FAISS index from {path}.faiss")

            if os.path.exists(f"{path}.pkl"):
                with open(f"{path}.pkl", "rb") as f:
                    data = pickle.load(f)
                    self.metadata = data["metadata"]
                    self.chunk_contents = data["chunk_contents"]
                logger.info(f"Loaded metadata and chunk contents from {path}.pkl")
        except Exception as e:
            logger.error(f"Error loading vector database: {e}")

    def stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        return {
            "total_chunks": len(self.metadata),
            "dimension": self.dimension,
            "languages": list(set(m.language for m in self.metadata)),
            "chunk_types": list(set(m.chunk_type for m in self.metadata)),
        }
