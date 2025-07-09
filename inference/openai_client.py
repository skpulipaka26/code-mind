import os
import time
from typing import List, Dict, Any
from dataclasses import dataclass
from openai import AsyncOpenAI, APIConnectionError
from dotenv import load_dotenv
from monitoring.telemetry import get_telemetry
from utils.logging import get_logger

logger = get_logger(__name__)

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
    """Simple OpenRouter client using OpenAI SDK. Also supports a local embedding model."""

    def __init__(self, api_key: str = None, config=None):
        self.config = config
        self.openrouter_client = AsyncOpenAI(
            api_key=api_key or os.getenv("OPENROUTER_API_KEY"),
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": "https://turbo-review.local",
                "X-Title": "Turbo Review",
            },
        )

        # For local model via LM Studio
        self.local_client = AsyncOpenAI(
            api_key="lm-studio",
            base_url=config.local_model_base_url
            if config
            else "http://127.0.0.1:1234/v1",
        )
        self.local_embedding_model_name = (
            config.local_embedding_model
            if config
            else "text-embedding-qwen3-embedding-0.6b"
        )
        self.local_embedding_model_alias = "qwen/qwen3-embedding-0.6b"
        self.local_completion_model_name = (
            config.local_completion_model if config else "qwen2.5-coder-7b-instruct"
        )
        self.local_completion_model_alias = "qwen/qwen2.5-coder-7b-instruct"

    def _record_telemetry(self, operation: str, model: str, duration: float, **kwargs):
        """Helper to record telemetry data."""
        telemetry = get_telemetry()
        telemetry.increment_api_requests({"model": model, "operation": operation})
        if "batch_size" in kwargs:
            telemetry.record_embedding_duration(
                duration, {"model": model, "batch_size": kwargs["batch_size"]}
            )

    async def embed(
        self, text: str, model: str = "qwen/qwen3-embedding-0.6b"
    ) -> List[float]:
        """Create embedding for text."""
        telemetry = get_telemetry()

        if model == self.local_embedding_model_alias:
            with telemetry.trace_operation(
                "local_embed",
                {"model": self.local_embedding_model_name, "text_length": len(text)},
            ):
                try:
                    start_time = time.time()
                    response = await self.local_client.embeddings.create(
                        model=self.local_embedding_model_name, input=text
                    )
                    duration = time.time() - start_time
                    self._record_telemetry(
                        "embed", self.local_embedding_model_name, duration, batch_size=1
                    )
                    logger.debug(
                        f"Local embedding successful for text length {len(text)}"
                    )
                    return response.data[0].embedding
                except APIConnectionError as e:
                    logger.warning(
                        f"Local embedding model unavailable, falling back to OpenRouter: {e}"
                    )
                    # Fallback to OpenRouter if local model is unavailable
                    pass

        with telemetry.trace_operation(
            "openrouter_embed", {"model": model, "text_length": len(text)}
        ):
            start_time = time.time()
            response = await self.openrouter_client.embeddings.create(
                model=model, input=text
            )
            duration = time.time() - start_time

            # Record API request and cost metrics
            self._record_telemetry("embed", model, duration, batch_size=1)
            logger.debug(
                f"OpenRouter embedding successful for model {model}, text length {len(text)}"
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

        if model == self.local_embedding_model_alias:
            with telemetry.trace_operation(
                "local_embed_batch",
                {
                    "model": self.local_embedding_model_name,
                    "batch_size": len(texts),
                },
            ):
                try:
                    start_time = time.time()
                    response = await self.local_client.embeddings.create(
                        model=self.local_embedding_model_name, input=texts
                    )
                    duration = time.time() - start_time
                    self._record_telemetry(
                        "embed_batch",
                        self.local_embedding_model_name,
                        duration,
                        batch_size=len(texts),
                    )
                    return [data.embedding for data in response.data]
                except APIConnectionError:
                    # Fallback to OpenRouter
                    pass

        with telemetry.trace_operation(
            "openrouter_embed_batch", {"model": model, "batch_size": len(texts)}
        ):
            start_time = time.time()
            response = await self.openrouter_client.embeddings.create(
                model=model, input=texts
            )
            duration = time.time() - start_time

            # Record metrics
            self._record_telemetry(
                "embed_batch", model, duration, batch_size=len(texts)
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

        if model == self.local_completion_model_alias:
            with telemetry.trace_operation(
                "local_complete",
                {
                    "model": self.local_completion_model_name,
                    "message_count": len(messages),
                },
            ):
                try:
                    response = await self.local_client.chat.completions.create(
                        model=self.local_completion_model_name,
                        messages=messages,
                        temperature=self.config.review_temperature
                        if self.config
                        else 0.1,
                        max_tokens=self.config.max_tokens if self.config else 2048,
                    )
                    self._record_telemetry(
                        "complete", self.local_completion_model_name, 0
                    )
                    return response.choices[0].message.content
                except APIConnectionError:
                    # Fallback to OpenRouter
                    pass

        with telemetry.trace_operation(
            "openrouter_complete", {"model": model, "message_count": len(messages)}
        ):
            response = await self.openrouter_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=self.config.review_temperature if self.config else 0.1,
                max_tokens=self.config.max_tokens if self.config else 2048,
            )

            # Record metrics
            self._record_telemetry("complete", model, 0)

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
        except Exception as e:
            logger.warning(f"Error parsing rerank response: {e}")
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
        await self.openrouter_client.close()
        await self.local_client.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
