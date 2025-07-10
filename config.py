import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
import json
from dotenv import load_dotenv

load_dotenv()

@dataclass
class ModelConfig:
    model_name: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None


@dataclass
class Config:
    """Configuration for Turbo Review."""

    openrouter_api_key: str = ""  # Keep for global fallback

    max_chunks: int = 20
    chunk_overlap: int = 5
    review_temperature: float = 0.1
    vector_dimension: int = 1024
    vector_db_path: str = "vector_db"

    # Logging configuration
    log_level: str = "INFO"
    log_file: str = "review_output.log"

    # Processing configuration
    embedding_batch_size: int = 5  # Reduced from 10 to avoid rate limits
    vector_search_k: int = 10
    rerank_top_k: int = 5
    max_tokens: int = 2048
    
    # Rate limiting configuration
    local_requests_per_minute: int = 300  # Higher limit for local models
    local_requests_per_second: float = 10.0  # 10 requests per second for local
    remote_requests_per_minute: int = 20  # Conservative for remote APIs
    remote_requests_per_second: float = 0.5  # 0.5 requests per second for remote

    # Model configurations
    embedding: ModelConfig = field(
        default_factory=lambda: ModelConfig(
            model_name="qwen/qwen3-embedding-0.6b", base_url="http://127.0.0.1:1234/v1"
        )
    )
    rerank: ModelConfig = field(
        default_factory=lambda: ModelConfig(
            model_name="qwen/qwen2.5-coder-7b-instruct",
            base_url="http://127.0.0.1:1234/v1",
        )
    )
    completion: ModelConfig = field(
        default_factory=lambda: ModelConfig(
            model_name="qwen/qwen2.5-coder-7b-instruct",
            base_url="http://127.0.0.1:1234/v1",
        )
    )

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "Config":
        """Load configuration from file or environment."""
        config = cls()

        # Load from environment
        default_openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
        if default_openrouter_api_key:
            config.openrouter_api_key = default_openrouter_api_key

        # Override with config file if provided
        if config_path and Path(config_path).exists():
            try:
                with open(config_path, "r") as f:
                    data = json.load(f)
                    for key, value in data.items():
                        if key in ["embedding", "rerank", "completion"] and isinstance(
                            value, dict
                        ):
                            setattr(config, key, ModelConfig(**value))
                        elif hasattr(config, key):
                            setattr(config, key, value)
            except Exception as e:
                print(f"Warning: Could not load config file: {e}")

        # Apply default API key to individual models if not specified
        if default_openrouter_api_key:
            if not config.embedding.api_key:
                config.embedding.api_key = default_openrouter_api_key
            if not config.rerank.api_key:
                config.rerank.api_key = default_openrouter_api_key
            if not config.completion.api_key:
                config.completion.api_key = default_openrouter_api_key

        # Validate required fields (optional, depending on how strict we want to be)
        # if not config.openrouter_api_key and (not config.completion.api_key or not config.embedding.api_key):
        #     print("Warning: No API key configured for OpenRouter or individual models.")

        return config

    def save(self, config_path: str):
        """Save configuration to file."""
        data = {
            "openrouter_api_key": self.openrouter_api_key,
            "max_chunks": self.max_chunks,
            "chunk_overlap": self.chunk_overlap,
            "review_temperature": self.review_temperature,
            "vector_dimension": self.vector_dimension,
            "log_level": self.log_level,
            "log_file": self.log_file,
            "embedding_batch_size": self.embedding_batch_size,
            "vector_search_k": self.vector_search_k,
            "rerank_top_k": self.rerank_top_k,
            "max_tokens": self.max_tokens,
            "embedding": self.embedding.__dict__,
            "rerank": self.rerank.__dict__,
            "completion": self.completion.__dict__,
        }

        with open(config_path, "w") as f:
            json.dump(data, f, indent=2)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "openrouter_api_key": self.openrouter_api_key,
            "max_chunks": self.max_chunks,
            "chunk_overlap": self.chunk_overlap,
            "review_temperature": self.review_temperature,
            "vector_dimension": self.vector_dimension,
            "log_level": self.log_level,
            "log_file": self.log_file,
            "embedding_batch_size": self.embedding_batch_size,
            "vector_search_k": self.vector_search_k,
            "rerank_top_k": self.rerank_top_k,
            "max_tokens": self.max_tokens,
            "embedding": self.embedding.__dict__,
            "rerank": self.rerank.__dict__,
            "completion": self.completion.__dict__,
            "has_api_key": bool(self.openrouter_api_key or self.completion.api_key),
        }
