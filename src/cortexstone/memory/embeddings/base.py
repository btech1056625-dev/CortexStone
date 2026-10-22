"""Abstract interface and contracts for text embedding providers.

Defines the asynchronous interface `EmbeddingProvider` that concrete providers
(e.g., local FastEmbed, SentenceTransformers, or hosted Nebius/OpenAI) must implement.

Includes support for:
- Core embedding operations: `embed_text()` and `embed_batch()`
- Distinguishing query vs document semantics: `embed_query()` and `embed_document()`
- Provider properties: `provider_name` and `dimension`
"""

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """Abstract asynchronous base class for embedding generation."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the unique identifier/name of this embedding provider."""
        raise NotImplementedError

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the vector dimensionality produced by this model (e.g., 384, 768, 1024, 1536)."""
        raise NotImplementedError

    @abstractmethod
    async def embed_text(self, text: str) -> list[float]:
        """Generate an embedding vector for a single string.

        Args:
            text: Plaintext content to embed. Must not contain raw secrets.

        Returns:
            List of floats representing the embedding vector.
        """
        raise NotImplementedError

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embedding vectors for a batch of strings.

        Args:
            texts: List of strings to embed.

        Returns:
            List of embedding vectors, matching input order.
        """
        raise NotImplementedError

    async def embed_query(self, query: str) -> list[float]:
        """Generate an embedding vector specifically for a search query.

        Models such as BGE or E5/Qwen may apply query-specific prefixes or instructions.
        Default implementation delegates to embed_text(query) for full backward compatibility.

        Args:
            query: Plaintext query string.

        Returns:
            Embedding vector for the query.
        """
        return await self.embed_text(query)

    async def embed_document(self, document: str) -> list[float]:
        """Generate an embedding vector specifically for a stored document/memory item.

        Default implementation delegates to embed_text(document) for full backward compatibility.

        Args:
            document: Plaintext memory content.

        Returns:
            Embedding vector for the document.
        """
        return await self.embed_text(document)
