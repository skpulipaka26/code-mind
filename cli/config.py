import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
import json
from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class Config:
    """Configuration for Turbo Review."""

    openrouter_api_key: str = ""
    embedding_model: str = "qwen/qwen3-embedding-0.6b"
    completion_model: str = "qwen/qwen2.5-coder-7b-instruct"
    max_chunks: int = 20
    chunk_overlap: int = 5
    review_temperature: float = 0.1
    vector_dimension: int = 1024
    vector_db_path: str = "vector_db"
    
    # Logging configuration
    log_level: str = "INFO"
    log_file: str = "review_output.log"
    
    # Local model configuration
    local_model_base_url: str = "http://127.0.0.1:1234/v1"
    local_embedding_model: str = "text-embedding-qwen3-embedding-0.6b"
    local_completion_model: str = "qwen2.5-coder-7b-instruct"
    
    # Processing configuration
    embedding_batch_size: int = 10
    vector_search_k: int = 10
    rerank_top_k: int = 5
    max_tokens: int = 2048

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "Config":
        """Load configuration from file or environment."""
        config = cls()

        # Load from environment
        config.openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")

        # Override with config file if provided
        if config_path and Path(config_path).exists():
            try:
                with open(config_path, "r") as f:
                    data = json.load(f)
                    for key, value in data.items():
                        if hasattr(config, key):
                            setattr(config, key, value)
            except Exception as e:
                logger.warning(f"Could not load config file: {e}")

        # Validate required fields
        if not config.openrouter_api_key:
            print(
                "Warning: OPENROUTER_API_KEY not set. Set it via environment variable or config file."
            )

        return config

    def save(self, config_path: str):
        """Save configuration to file."""
        data = {
            "embedding_model": self.embedding_model,
            "completion_model": self.completion_model,
            "max_chunks": self.max_chunks,
            "chunk_overlap": self.chunk_overlap,
            "review_temperature": self.review_temperature,
            "vector_dimension": self.vector_dimension,
        }

        with open(config_path, "w") as f:
            json.dump(data, f, indent=2)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "embedding_model": self.embedding_model,
            "completion_model": self.completion_model,
            "max_chunks": self.max_chunks,
            "chunk_overlap": self.chunk_overlap,
            "review_temperature": self.review_temperature,
            "vector_dimension": self.vector_dimension,
            "has_api_key": bool(self.openrouter_api_key),
        }
