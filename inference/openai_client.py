import time
import asyncio
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from openai import AsyncOpenAI
from openai import RateLimitError, APIError
from monitoring.telemetry import get_telemetry
from utils.logging import get_logger
from cli.config import ModelConfig

logger = get_logger(__name__)


class RateLimiter:
    """Global rate limiter to prevent overwhelming the API."""

    def __init__(self, requests_per_minute: int = 20, requests_per_second: float = 0.5):
        self.requests_per_minute = requests_per_minute
        self.requests_per_second = requests_per_second
        self.request_times = []
        self.last_request_time = 0
        self.consecutive_rate_limits = 0
        self.adaptive_delay = 1.0  # Start with 1 second base delay
        self._lock = asyncio.Lock()

    async def acquire(self):
        """Acquire permission to make a request."""
        async with self._lock:
            now = time.time()

            # Remove requests older than 1 minute
            self.request_times = [t for t in self.request_times if now - t < 60]

            # Check if we need to wait for per-minute limit
            if len(self.request_times) >= self.requests_per_minute:
                wait_time = 60 - (now - self.request_times[0]) + 1
                logger.info(
                    f"Rate limit: waiting {wait_time:.1f}s for per-minute limit"
                )
                await asyncio.sleep(wait_time)
                now = time.time()
                self.request_times = [t for t in self.request_times if now - t < 60]

            # Check if we need to wait for per-second limit
            time_since_last = now - self.last_request_time
            min_interval = 1.0 / self.requests_per_second

            # Apply adaptive delay if we've been rate limited recently
            if self.consecutive_rate_limits > 0:
                min_interval = max(min_interval, self.adaptive_delay)

            if time_since_last < min_interval:
                wait_time = min_interval - time_since_last
                logger.debug(
                    f"Rate limit: waiting {wait_time:.1f}s for per-second limit"
                )
                await asyncio.sleep(wait_time)
                now = time.time()

            # Record this request
            self.request_times.append(now)
            self.last_request_time = now

    def record_rate_limit(self):
        """Record that we hit a rate limit to adjust future delays."""
        self.consecutive_rate_limits += 1
        # Exponentially increase adaptive delay, but cap it
        self.adaptive_delay = min(self.adaptive_delay * 1.5, 30.0)
        logger.warning(
            f"Rate limit hit #{self.consecutive_rate_limits}, adaptive delay now {self.adaptive_delay:.1f}s"
        )

    def record_success(self):
        """Record a successful request to gradually reduce delays."""
        if self.consecutive_rate_limits > 0:
            self.consecutive_rate_limits = max(0, self.consecutive_rate_limits - 1)
            if self.consecutive_rate_limits == 0:
                self.adaptive_delay = max(1.0, self.adaptive_delay * 0.8)
                logger.info(
                    f"Rate limiting recovered, adaptive delay now {self.adaptive_delay:.1f}s"
                )


# Global rate limiter instance
_rate_limiter = RateLimiter()


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


class LLMClient:
    """Simple OpenRouter client using OpenAI SDK. Also supports a local embedding model."""

    def __init__(self, config=None):
        self.config = config
        self._clients: Dict[str, AsyncOpenAI] = {}
        # Limit concurrent requests to prevent overwhelming the API
        self._semaphore = asyncio.Semaphore(5)  # Max 2 concurrent requests

    async def _retry_with_backoff(self, func, *args, max_retries=2, **kwargs):
        """Retry function with intelligent backoff for rate limit errors."""
        for attempt in range(max_retries + 1):
            try:
                # Use global rate limiter before making request
                await _rate_limiter.acquire()
                result = await func(*args, **kwargs)
                _rate_limiter.record_success()
                return result

            except RateLimitError as e:
                _rate_limiter.record_rate_limit()

                if attempt == max_retries:
                    logger.error(f"Rate limit exceeded after {max_retries} retries")
                    raise e

                # More conservative backoff: start at 10s, then 30s
                wait_time = 10 + (attempt * 20)
                logger.warning(
                    f"Rate limit hit, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries + 1})"
                )
                await asyncio.sleep(wait_time)

            except APIError as e:
                if "429" in str(e):
                    _rate_limiter.record_rate_limit()

                    if attempt < max_retries:
                        wait_time = 15 + (attempt * 25)  # 15s, then 40s
                        logger.warning(
                            f"API error 429, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries + 1})"
                        )
                        await asyncio.sleep(wait_time)
                    else:
                        raise e
                else:
                    raise e

    def _record_telemetry(self, operation: str, model: str, duration: float, **kwargs):
        """Helper to record telemetry data."""
        telemetry = get_telemetry()
        telemetry.increment_api_requests({"model": model, "operation": operation})
        if "batch_size" in kwargs:
            telemetry.record_embedding_duration(
                duration, {"model": model, "batch_size": kwargs["batch_size"]}
            )

    def _get_client_for_model(self, model_config: ModelConfig) -> AsyncOpenAI:
        """Returns an AsyncOpenAI client for the given model configuration, caching clients."""
        client_key = f"{model_config.base_url}-{model_config.api_key}"
        if client_key in self._clients:
            return self._clients[client_key]

        if not model_config.base_url:
            raise ValueError(
                f"Base URL not configured for model: {model_config.model_name}"
            )

        client = AsyncOpenAI(
            api_key=model_config.api_key,
            base_url=model_config.base_url,
            default_headers={
                "HTTP-Referer": "https://turbo-review.local",
                "X-Title": "Turbo Review",
            },
        )
        self._clients[client_key] = client
        logger.info(
            f"Initialized client for model '{model_config.model_name}' with base URL: {model_config.base_url}"
        )
        return client

    async def embed(self, text: str) -> List[float]:
        """Create embedding for text."""
        async with self._semaphore:
            telemetry = get_telemetry()
            model_config = getattr(self.config, "embedding", None)
            client = self._get_client_for_model(model_config)

            operation_name = (
                "local_embed"
                if "127.0.0.1" in model_config.base_url
                or "localhost" in model_config.base_url
                else "openrouter_embed"
            )
            model_name_for_telemetry = model_config.model_name

            with telemetry.trace_operation(
                operation_name,
                {"model": model_name_for_telemetry, "text_length": len(text)},
            ):
                start_time = time.time()
                response = await self._retry_with_backoff(
                    client.embeddings.create, model=model_name_for_telemetry, input=text
                )
                duration = time.time() - start_time

                self._record_telemetry(
                    "embed", model_name_for_telemetry, duration, batch_size=1
                )
                logger.debug(
                    f"{operation_name.replace('_', ' ').title()} successful for model {model_name_for_telemetry}, text length {len(text)}"
                )

                if hasattr(response, "usage") and response.usage:
                    tokens = getattr(response.usage, "total_tokens", len(text.split()))
                    estimated_cost = tokens * 0.00001
                    telemetry.record_cost(
                        estimated_cost,
                        {"model": model_name_for_telemetry, "operation": "embed"},
                    )

                return response.data[0].embedding

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Create embeddings for multiple texts."""
        async with self._semaphore:
            telemetry = get_telemetry()
            model_config = getattr(self.config, "embedding", None)
            client = self._get_client_for_model(model_config)

            operation_name = (
                "local_embed_batch"
                if "127.0.0.1" in model_config.base_url
                or "localhost" in model_config.base_url
                else "openrouter_embed_batch"
            )
            model_name_for_telemetry = model_config.model_name

            with telemetry.trace_operation(
                operation_name,
                {"model": model_name_for_telemetry, "batch_size": len(texts)},
            ):
                start_time = time.time()
                response = await self._retry_with_backoff(
                    client.embeddings.create,
                    model=model_name_for_telemetry,
                    input=texts,
                )
                duration = time.time() - start_time

                self._record_telemetry(
                    "embed_batch",
                    model_name_for_telemetry,
                    duration,
                    batch_size=len(texts),
                )

                if hasattr(response, "usage") and response.usage:
                    tokens = getattr(
                        response.usage,
                        "total_tokens",
                        sum(len(text.split()) for text in texts),
                    )
                    estimated_cost = tokens * 0.00001
                    telemetry.record_cost(
                        estimated_cost,
                        {"model": model_name_for_telemetry, "operation": "embed_batch"},
                    )

                return [data.embedding for data in response.data]

    async def complete(
        self,
        messages: List[Dict[str, str]],
        model_config: Optional[ModelConfig] = None,
    ) -> str:
        """Create completion."""
        async with self._semaphore:
            telemetry = get_telemetry()

            if model_config is None:
                model_config = getattr(self.config, "completion", None)

            client = self._get_client_for_model(model_config)

            operation_name = (
                "local_complete"
                if "127.0.0.1" in model_config.base_url
                or "localhost" in model_config.base_url
                else "openrouter_complete"
            )
            model_name_for_telemetry = model_config.model_name

            with telemetry.trace_operation(
                operation_name,
                {"model": model_name_for_telemetry, "message_count": len(messages)},
            ):
                response = await self._retry_with_backoff(
                    client.chat.completions.create,
                    model=model_name_for_telemetry,
                    messages=messages,
                    temperature=getattr(self.config, "review_temperature", 0.1),
                    max_tokens=getattr(self.config, "max_tokens", 2048),
                )

                self._record_telemetry("complete", model_name_for_telemetry, 0)

                if hasattr(response, "usage") and response.usage:
                    tokens = getattr(response.usage, "total_tokens", 1000)
                    estimated_cost = tokens * 0.00002
                    telemetry.record_cost(
                        estimated_cost,
                        {"model": model_name_for_telemetry, "operation": "complete"},
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

        response = await self.complete(
            messages, model_config=getattr(self.config, "rerank", None)
        )

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
        for client in self._clients.values():
            await client.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
