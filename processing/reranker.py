from typing import List, Dict, Tuple
from dataclasses import dataclass
from core.vectordb import VectorMetadata
from inference.openai_client import OpenRouterClient
from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class RerankedResult:
    metadata: VectorMetadata
    content: str
    score: float
    rank: int


class CodeReranker:
    """Rerank code chunks for relevance."""

    def __init__(self, client: OpenRouterClient):
        self.client = client

    async def rerank_search_results(
        self,
        query: str,
        search_results: List[Tuple[VectorMetadata, float]],
        chunk_contents: Dict[str, str],
        top_k: int = 5,
    ) -> List[RerankedResult]:
        """Rerank search results by relevance."""
        if not search_results:
            logger.debug("No search results to rerank.")
            return []

        # Prepare documents
        documents = []
        metadata_list = []

        for metadata, score in search_results:
            content = chunk_contents.get(metadata.chunk_id, "")
            if content:
                doc_text = self._format_chunk(metadata, content)
                documents.append(doc_text)
                metadata_list.append((metadata, score))

        if not documents:
            return []

        # Rerank
        rankings = await self.client.rerank(query, documents, top_k)

        # Convert to results
        results = []
        for ranking in rankings:
            doc_index = ranking["index"]
            if doc_index < len(metadata_list):
                metadata, original_score = metadata_list[doc_index]

                result = RerankedResult(
                    metadata=metadata,
                    content=documents[doc_index],
                    score=ranking["score"],
                    rank=ranking["rank"],
                )
                results.append(result)

        return results

    def _format_chunk(self, metadata: VectorMetadata, content: str) -> str:
        """Format chunk for reranking."""
        return f"{metadata.chunk_type} {metadata.name or ''} in {metadata.file_path}:\n{content}"
