from typing import List
from dataclasses import dataclass
from storage.vector_store import VectorSearchResult
from inference.openai_client import LLMClient


@dataclass
class RerankedResult:
    result: VectorSearchResult
    score: float
    rank: int


class CodeReranker:
    """Rerank code chunks for relevance."""

    def __init__(self, client: LLMClient):
        self.client = client

    async def rerank_search_results(
        self,
        query: str,
        search_results: List[VectorSearchResult],
        top_k: int = 5,
    ) -> List[RerankedResult]:
        """Rerank search results by relevance."""
        if not search_results:
            return []

        # Prepare documents
        documents = []
        result_list = []

        for result in search_results:
            if result.content:
                doc_text = self._format_chunk(result)
                documents.append(doc_text)
                result_list.append(result)

        if not documents:
            return []

        # Rerank
        rankings = await self.client.rerank(query, documents, top_k)

        # Convert to results
        results = []
        for ranking in rankings:
            doc_index = ranking["index"]
            if doc_index < len(result_list):
                vector_result = result_list[doc_index]

                result = RerankedResult(
                    result=vector_result,
                    score=ranking["score"],
                    rank=ranking["rank"],
                )
                results.append(result)

        return results

    def _format_chunk(self, result: VectorSearchResult) -> str:
        """Format chunk for reranking."""
        metadata = result.metadata
        chunk_type = metadata.get("chunk_type", "code")
        name = metadata.get("name", "")
        file_path = metadata.get("file_path", "")
        return f"{chunk_type} {name} in {file_path}:\n{result.content}"
