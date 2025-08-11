"""
Hugging Face model client for direct model loading and inference.
Supports embedding models that can't be served via OpenAI-compatible APIs.
"""

import asyncio
import time
from typing import List, Dict, Any
from dataclasses import dataclass

import torch
import torch.nn.functional as F
from transformers import AutoTokenizer, AutoModel

from monitoring.telemetry import get_telemetry
from utils.logging import get_logger
from config import ModelConfig

logger = get_logger(__name__)


@dataclass
class HuggingFaceResponse:
    """Response from Hugging Face model."""

    embeddings: List[List[float]]
    model_name: str
    usage: Dict[str, int]


class HuggingFaceClient:
    """Client for direct Hugging Face model inference."""

    def __init__(self, config: ModelConfig):
        self.config = config
        self.model_name = config.model_name
        self.telemetry = get_telemetry()

        # Model and tokenizer will be loaded lazily
        self.model = None
        self.tokenizer = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        logger.info(
            f"Initialized HuggingFace client for {self.model_name} on {self.device}"
        )

    def _load_model(self):
        """Lazy load the model and tokenizer."""
        if self.model is None:
            logger.info(f"Loading model {self.model_name}...")
            start_time = time.time()

            try:
                # Use MPS device for Apple Silicon, fallback to CPU
                if torch.backends.mps.is_available():
                    self.device = "mps"
                elif torch.cuda.is_available():
                    self.device = "cuda"
                else:
                    self.device = "cpu"

                logger.info(f"Using device: {self.device}")

                self.tokenizer = AutoTokenizer.from_pretrained(
                    self.model_name, trust_remote_code=True, force_download=False
                )

                # Use appropriate dtype for device
                if self.device == "mps":
                    torch_dtype = torch.float32  # MPS doesn't support float16 well
                elif self.device == "cuda":
                    torch_dtype = torch.float16
                else:
                    torch_dtype = torch.float32

                self.model = AutoModel.from_pretrained(
                    self.model_name,
                    trust_remote_code=True,
                    torch_dtype=torch_dtype,
                    force_download=False,
                    device_map=None,
                ).to(self.device)

                load_time = time.time() - start_time
                logger.info(f"Model loaded in {load_time:.2f}s")

            except Exception as e:
                logger.error(f"Failed to load model {self.model_name}: {e}")
                if "connection" in str(e).lower() or "timeout" in str(e).lower():
                    logger.error("Network issue detected. Try:")
                    logger.error("1. Check internet connection")
                    logger.error(
                        "2. Use a smaller model like 'sentence-transformers/all-MiniLM-L6-v2'"
                    )
                    logger.error("3. Set up a local embedding server instead")
                raise

    def _mean_pooling(self, model_output, attention_mask):
        """Apply mean pooling to get sentence embeddings."""
        token_embeddings = model_output[0]
        input_mask_expanded = (
            attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
        )
        return torch.sum(token_embeddings * input_mask_expanded, 1) / torch.clamp(
            input_mask_expanded.sum(1), min=1e-9
        )

    async def embed(self, text: str, max_length: int = 8192) -> List[float]:
        """Generate embedding for a single text."""
        embeddings = await self.embed_batch([text], max_length=max_length)
        return embeddings[0]

    async def embed_batch(
        self, texts: List[str], max_length: int = 8192
    ) -> List[List[float]]:
        """Generate embeddings for a batch of texts."""
        self._load_model()

        start_time = time.time()

        try:
            # Use conservative max_length for UniXcoder (512 tokens)
            actual_max_length = 512

            # Tokenize inputs
            encoded_input = self.tokenizer(
                texts,
                padding=True,
                truncation=True,
                max_length=actual_max_length,
                return_tensors="pt",
            ).to(self.device)

            # Generate embeddings
            with torch.no_grad():
                model_output = self.model(**encoded_input)

            # Apply mean pooling
            embeddings = self._mean_pooling(
                model_output, encoded_input["attention_mask"]
            )

            # Normalize embeddings
            embeddings = F.normalize(embeddings, p=2, dim=1)

            # Convert to list format
            embeddings_list = embeddings.cpu().float().tolist()

            # Record telemetry
            duration = time.time() - start_time
            self.telemetry.record_embedding_duration(duration)

            logger.debug(
                f"Generated {len(embeddings_list)} embeddings in {duration:.2f}s"
            )

            return embeddings_list

        except Exception as e:
            logger.error(f"Error generating embeddings: {e}")
            raise

    def get_model_info(self) -> Dict[str, Any]:
        """Get information about the loaded model."""
        self._load_model()

        return {
            "model_name": self.model_name,
            "device": self.device,
            "model_size": sum(p.numel() for p in self.model.parameters()),
            "dtype": str(self.model.dtype) if self.model else None,
        }

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        # Clean up GPU memory if needed
        if self.model is not None and self.device == "cuda":
            del self.model
            del self.tokenizer
            torch.cuda.empty_cache()


class InstructionEmbeddingClient(HuggingFaceClient):
    """Client for instruction-based embedding models (like Salesforce SFR models)."""

    def __init__(self, config: ModelConfig):
        super().__init__(config)
        # Determine max length based on model
        self.max_length = self._get_max_length_for_model()

    def _get_max_length_for_model(self) -> int:
        """Get appropriate max length based on model name."""
        model_name_lower = self.model_name.lower()
        if "bge" in model_name_lower:
            return 8192  # BGE models typically 8k
        elif "code" in model_name_lower:
            return 16384  # Code models often support longer context
        else:
            return 8192  # Safe default

    async def embed_with_instruction(
        self, text: str, instruction: str = None
    ) -> List[float]:
        """
        Embed text with optional instruction.

        Args:
            text: The text to embed
            instruction: Optional instruction for the embedding task
        """
        if instruction and self._model_supports_instructions():
            # For instruction-based models, format with instruction
            formatted_text = f"Instruct: {instruction}\nQuery: {text}"
        else:
            # For regular models or passages, use text as-is
            formatted_text = text

        return await self.embed(formatted_text, max_length=self.max_length)

    def _model_supports_instructions(self) -> bool:
        """Check if the model supports instruction-based embedding."""
        model_name_lower = self.model_name.lower()
        return "instruct" in model_name_lower or "sfr" in model_name_lower

    async def embed_query(self, query: str) -> List[float]:
        """Embed a search query with default instruction if supported."""
        if self._model_supports_instructions():
            instruction = "Given Code or Text, retrieval relevant content"
            return await self.embed_with_instruction(query, instruction=instruction)
        else:
            return await self.embed(query, max_length=self.max_length)

    async def embed_passage(self, passage: str) -> List[float]:
        """Embed a passage (no instruction needed)."""
        return await self.embed(passage, max_length=self.max_length)


def create_huggingface_client(model_name: str) -> HuggingFaceClient:
    """Create appropriate HuggingFace client based on model name."""
    config = ModelConfig(model_name=model_name)

    # Check if model supports instruction-based embedding
    model_name_lower = model_name.lower()
    if ("sfr" in model_name_lower) or "instruct" in model_name_lower:
        return InstructionEmbeddingClient(config)
    else:
        return HuggingFaceClient(config)


# Example usage
async def test_embedding():
    """Test the embedding client with current config."""
    from config import Config

    config = Config.load()
    model_name = config.embedding.model_name

    print(f"Testing model: {model_name}")

    async with create_huggingface_client(model_name) as client:
        # Test code embedding
        code = """
def quick_sort(arr):
    if len(arr) <= 1:
        return arr
    pivot = arr[len(arr) // 2]
    left = [x for x in arr if x < pivot]
    middle = [x for x in arr if x == pivot]
    right = [x for x in arr if x > pivot]
    return quick_sort(left) + middle + quick_sort(right)
        """

        query = "how to implement LRU cache in Python?"

        # Generate embeddings
        if isinstance(client, InstructionEmbeddingClient):
            code_embedding = await client.embed_passage(code)
            query_embedding = await client.embed_query(query)
        else:
            code_embedding = await client.embed(code)
            query_embedding = await client.embed(query)

        # Calculate similarity
        import numpy as np

        similarity = np.dot(code_embedding, query_embedding)

        print(f"Code-Query similarity: {similarity:.3f}")
        print(f"Model info: {client.get_model_info()}")


if __name__ == "__main__":
    asyncio.run(test_embedding())
