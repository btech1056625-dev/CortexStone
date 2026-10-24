"""Production embedding provider for BAAI/bge-small-en-v1.5.

Integrates BAAI/bge-small-en-v1.5 (384 dimensions) into the CortexStone memory
subsystem, conforming to `EmbeddingProvider`.

Key features:
1. Exact 384-dimensional vector output with L2 normalization.
2. Supports lightweight, CPU-efficient local inference via FastEmbed (primary)
   or SentenceTransformers (fallback).
3. Dependency injection support for mock backends during unit testing without
   requiring network downloads.
4. Asynchronous, non-blocking execution via `asyncio.to_thread`.
5. Automatic query prefixing (`Represent this sentence for searching relevant passages: `)
   for optimal BGE retrieval ranking, while keeping documents prefix-free.
6. Rigorous validation of input strings and generated vector dimensions.
"""

import asyncio
from typing import Any

from cortexstone.memory.embeddings.base import EmbeddingProvider
from cortexstone.memory.embeddings.config import (
    BGE_SMALL_DIMENSION,
    BGE_SMALL_MODEL_ID,
    BGE_SMALL_QUERY_INSTRUCTION,
    EmbeddingConfig,
    EmbeddingDimensionMismatchError,
    EmbeddingProviderError,
    normalize_embedding_vector,
    validate_embedding_vector,
)


class BGEEmbeddingProvider(EmbeddingProvider):
    """Local embedding provider for BAAI/bge-small-en-v1.5 (384 dimensions)."""

    def __init__(
        self,
        config: EmbeddingConfig | None = None,
        model: Any | None = None,
    ) -> None:
        """Initialize the BGE embedding provider.

        Args:
            config: Optional typed EmbeddingConfig. If omitted, uses centralized
                BAAI/bge-small-en-v1.5 defaults (384 dimensions).
            model: Optional pre-loaded model or test mock to inject.
                If None, the model is loaded lazily on first inference call.

        Raises:
            EmbeddingDimensionMismatchError: If the configured dimension is not 384.
        """
        self._config = config or EmbeddingConfig(
            provider_id="fastembed",
            model_id=BGE_SMALL_MODEL_ID,
            dimension=BGE_SMALL_DIMENSION,
            query_instruction=BGE_SMALL_QUERY_INSTRUCTION,
        )

        if self._config.dimension != BGE_SMALL_DIMENSION:
            raise EmbeddingDimensionMismatchError(
                expected=BGE_SMALL_DIMENSION,
                actual=self._config.dimension,
            )

        self._model = model

    @property
    def provider_name(self) -> str:
        """Unique provider identifier."""
        return f"{self._config.provider_id}:{self._config.model_id}"

    @property
    def dimension(self) -> int:
        """Vector dimensionality (384 for bge-small-en-v1.5)."""
        return self._config.dimension

    @property
    def model_id(self) -> str:
        """Underlying model identifier."""
        return self._config.model_id

    @property
    def query_instruction(self) -> str:
        """Instruction prefix for search queries."""
        return self._config.query_instruction

    def _get_model(self) -> Any:
        """Retrieve or lazily initialize the underlying embedding model.

        Supports fastembed (primary) and sentence-transformers (fallback).

        Returns:
            Backend model instance.

        Raises:
            EmbeddingProviderError: If neither backend library is installed
                or if model initialization fails.
        """
        if self._model is not None:
            return self._model

        provider_id = self._config.provider_id.lower()

        # 1. FastEmbed backend (preferred: lightweight, ONNX runtime, CPU optimized)
        if provider_id in ("fastembed", "local", "default"):
            try:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(model_name=self._config.model_id)
                return self._model
            except ImportError as err:
                if provider_id == "fastembed":
                    raise EmbeddingProviderError(
                        "The 'fastembed' package is required for BGEEmbeddingProvider. "
                        "Install it via 'pip install fastembed' or "
                        "'pip install \"cortexstone[embeddings]\"'."
                    ) from err
            except Exception as exc:
                model_name = self._config.model_id
                err_type = type(exc).__name__
                raise EmbeddingProviderError(
                    f"Failed to load FastEmbed model '{model_name}': {err_type}"
                ) from exc

        # 2. SentenceTransformers fallback
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._config.model_id)
            return self._model
        except ImportError as err:
            raise EmbeddingProviderError(
                "Neither 'fastembed' nor 'sentence-transformers' is installed. "
                "Install fastembed via 'pip install fastembed' or "
                "'pip install \"cortexstone[embeddings]\"' to run BAAI/bge-small-en-v1.5 locally."
            ) from err
        except Exception as exc:
            model_name = self._config.model_id
            err_type = type(exc).__name__
            raise EmbeddingProviderError(
                f"Failed to load SentenceTransformer model '{model_name}': {err_type}"
            ) from exc

    def _sync_encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Synchronously encode a batch of texts using the underlying model backend."""
        model = self._get_model()

        # Case A: FastEmbed model (has .embed() returning an iterator of numpy arrays)
        if hasattr(model, "embed"):
            raw_iter = model.embed(texts, batch_size=self._config.batch_size)
            raw_vectors = [list(map(float, vec)) for vec in raw_iter]

        # Case B: SentenceTransformers model (has .encode() returning numpy ndarray)
        elif hasattr(model, "encode"):
            raw_output = model.encode(
                texts,
                batch_size=self._config.batch_size,
                normalize_embeddings=False,
            )
            raw_vectors = [list(map(float, vec)) for vec in raw_output]

        # Case C: Generic test mock or custom callable
        elif hasattr(model, "embed_batch"):
            raw_vectors = model.embed_batch(texts)
        elif callable(model):
            raw_vectors = model(texts)
        else:
            raise EmbeddingProviderError(
                f"Model backend {type(model).__name__} does not provide an embed or encode method."
            )

        if len(raw_vectors) != len(texts):
            raise EmbeddingProviderError(
                f"Backend returned {len(raw_vectors)} vectors for {len(texts)} input texts."
            )

        # Validate and normalize each vector
        normalized_vectors: list[list[float]] = []
        for idx, vec in enumerate(raw_vectors):
            try:
                validate_embedding_vector(vec, expected_dimension=self.dimension)
                normed = normalize_embedding_vector(vec, expected_dimension=self.dimension)
                normalized_vectors.append(normed)
            except Exception as exc:
                raise EmbeddingProviderError(
                    f"Vector validation/normalization failed for item {idx}: {type(exc).__name__}"
                ) from exc

        return normalized_vectors

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate normalized 384-d embedding vectors for a batch of strings.

        Args:
            texts: List of non-empty strings to embed.

        Returns:
            List of L2-normalized float vectors matching input order.

        Raises:
            ValueError: If texts is empty, non-list, or contains blank/invalid strings.
            EmbeddingProviderError: If the backend fails during inference.
        """
        if not isinstance(texts, (list, tuple)):
            raise ValueError("texts must be a list or tuple of strings.")
        if len(texts) == 0:
            raise ValueError("texts list must not be empty.")

        cleaned_texts: list[str] = []
        for idx, item in enumerate(texts):
            if not isinstance(item, str):
                type_name = type(item).__name__
                raise ValueError(f"Text at index {idx} must be a string, got {type_name}.")
            clean = item.strip()
            if not clean:
                raise ValueError(f"Text at index {idx} must not be empty or blank.")
            cleaned_texts.append(clean)

        return await asyncio.to_thread(self._sync_encode_batch, cleaned_texts)

    async def embed_text(self, text: str) -> list[float]:
        """Generate an embedding vector for a single plaintext string.

        Args:
            text: Plaintext content to embed.

        Returns:
            L2-normalized 384-dimensional vector.

        Raises:
            ValueError: If text is empty or blank.
            EmbeddingProviderError: If inference fails.
        """
        if not isinstance(text, str):
            raise ValueError("text must be a string.")
        clean = text.strip()
        if not clean:
            raise ValueError("Text to embed must not be empty or blank.")

        results = await self.embed_batch([clean])
        return results[0]

    async def embed_query(self, query: str) -> list[float]:
        """Generate an embedding vector for a search query.

        Appends the BGE query instruction prefix for asymmetric passage retrieval.

        Args:
            query: Plaintext query.

        Returns:
            L2-normalized 384-dimensional query vector.
        """
        if not isinstance(query, str):
            raise ValueError("query must be a string.")
        clean = query.strip()
        if not clean:
            raise ValueError("Query text must not be empty or blank.")

        prefixed_query = f"{self._config.query_instruction}{clean}"
        return await self.embed_text(prefixed_query)

    async def embed_document(self, document: str) -> list[float]:
        """Generate an embedding vector for a memory document.

        Stored documents are embedded directly without the retrieval query prefix.

        Args:
            document: Plaintext memory content.

        Returns:
            L2-normalized 384-dimensional document vector.
        """
        if not isinstance(document, str):
            raise ValueError("document must be a string.")
        clean = document.strip()
        if not clean:
            raise ValueError("Document text must not be empty or blank.")

        return await self.embed_text(clean)
