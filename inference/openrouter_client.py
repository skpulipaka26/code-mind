import os
import time
from typing import List, Dict, Any
from dataclasses import dataclass
from openai import AsyncOpenAI
from dotenv import load_dotenv
from monitoring.telemetry import get_telemetry

load_dotenv()


@dataclass
class EmbeddingResponse:
    embedding: List[float]
    model: str
    usage: Dict[str, int]


@dataclass
class CompletionResponse:
    content: str
    model: str
    usage: Dict[str, int]


@dataclass
class RerankResponse:
    rankings: List[Dict[str, Any]]
    model: str


class OpenRouterClient:
    """Simple OpenRouter client using OpenAI SDK."""

    def __init__(self, api_key: str = None):
        self.client = AsyncOpenAI(
            api_key=api_key or os.getenv("OPENROUTER_API_KEY"),
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": "https://turbo-review.local",
                "X-Title": "Turbo Review",
            },
        )

    async def embed(
        self, text: str, model: str = "qwen/qwen3-embedding-0.6b"
    ) -> List[float]:
        """Create embedding for text."""
        telemetry = get_telemetry()

        with telemetry.trace_operation(
            "openrouter_embed", {"model": model, "text_length": len(text)}
        ):
            start_time = time.time()
            response = await self.client.embeddings.create(model=model, input=text)
            duration = time.time() - start_time

            # Record API request and cost metrics
            telemetry.increment_api_requests({"model": model, "operation": "embed"})
            telemetry.record_embedding_duration(
                duration, {"model": model, "batch_size": 1}
            )

            # Estimate cost based on tokens (approximate)
            if hasattr(response, "usage") and response.usage:
                tokens = getattr(response.usage, "total_tokens", len(text.split()))
                estimated_cost = tokens * 0.00001  # Rough estimate
                telemetry.record_cost(
                    estimated_cost, {"model": model, "operation": "embed"}
                )

            return response.data[0].embedding

    async def embed_batch(
        self, texts: List[str], model: str = "qwen/qwen3-embedding-0.6b"
    ) -> List[List[float]]:
        """Create embeddings for multiple texts."""
        telemetry = get_telemetry()

        with telemetry.trace_operation(
            "openrouter_embed_batch", {"model": model, "batch_size": len(texts)}
        ):
            start_time = time.time()
            response = await self.client.embeddings.create(model=model, input=texts)
            duration = time.time() - start_time

            # Record metrics
            telemetry.increment_api_requests(
                {"model": model, "operation": "embed_batch"}
            )
            telemetry.record_embedding_duration(
                duration, {"model": model, "batch_size": len(texts)}
            )

            # Estimate cost
            if hasattr(response, "usage") and response.usage:
                tokens = getattr(
                    response.usage,
                    "total_tokens",
                    sum(len(text.split()) for text in texts),
                )
                estimated_cost = tokens * 0.00001
                telemetry.record_cost(
                    estimated_cost, {"model": model, "operation": "embed_batch"}
                )

            return [data.embedding for data in response.data]

    async def complete(
        self,
        messages: List[Dict[str, str]],
        model: str = "qwen/qwen2.5-coder-7b-instruct",
    ) -> str:
        """Create completion."""
        telemetry = get_telemetry()

        with telemetry.trace_operation(
            "openrouter_complete", {"model": model, "message_count": len(messages)}
        ):
            response = await self.client.chat.completions.create(
                model=model, messages=messages, temperature=0.1, max_tokens=2048
            )

            # Record metrics
            telemetry.increment_api_requests({"model": model, "operation": "complete"})

            # Record cost if usage info is available
            if hasattr(response, "usage") and response.usage:
                tokens = getattr(
                    response.usage, "total_tokens", 1000
                )  # Default fallback
                estimated_cost = tokens * 0.00002  # Rough estimate for completion
                telemetry.record_cost(
                    estimated_cost, {"model": model, "operation": "complete"}
                )

            return response.choices[0].message.content

    async def rerank(
        self, query: str, documents: List[str], top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """Rerank documents using instruction model."""
        docs_text = "\n".join([f"{i + 1}. {doc}" for i, doc in enumerate(documents)])

        messages = [
            {
                "role": "system",
                "content": "Rank code snippets by relevance to the query. Return only document numbers, comma-separated.",
            },
            {
                "role": "user",
                "content": f"Query: {query}\n\nDocuments:\n{docs_text}\n\nRank most relevant:",
            },
        ]

        response = await self.complete(messages)

        # Parse rankings
        try:
            rankings = [int(x.strip()) - 1 for x in response.split(",")]
            rankings = [r for r in rankings if 0 <= r < len(documents)][:top_k]
        except Exception:
            rankings = list(range(min(top_k, len(documents))))

        return [
            {
                "document": documents[i],
                "index": i,
                "rank": rank + 1,
                "score": 1.0 - (rank / len(rankings)),
            }
            for rank, i in enumerate(rankings)
        ]

    async def close(self):
        """Close client."""
        await self.client.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
