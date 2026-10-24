# CortexStone Memory Embeddings

## Selected Embedding Model

- **Model ID:** `BAAI/bge-small-en-v1.5`
- **Vector Dimension:** `384`
- **Normalization:** L2 (Unit-length vectors, $\sum x_i^2 = 1.0$)
- **Cost / License:** Free, open-source (MIT/Apache), runs 100% locally with zero paid API dependencies.

## Architecture

The embedding layer conforms to the `EmbeddingProvider` abstract interface defined in `base.py`:
- `embed_text(text: str) -> list[float]`: Embeds a single text string.
- `embed_batch(texts: list[str]) -> list[list[float]]`: Batch inference preserving input ordering.
- `embed_query(query: str) -> list[float]`: Prepends BGE's asymmetric query instruction (`Represent this sentence for searching relevant passages: `) for optimal semantic retrieval ranking.
- `embed_document(document: str) -> list[float]`: Embeds documents/memories prefix-free.
- `dimension -> int`: Returns `384`.
- `provider_name -> str`: Identifies the provider and underlying model (`fastembed:BAAI/bge-small-en-v1.5`).

## Installation Requirements

Local embedding generation requires an ONNX- or PyTorch-based inference backend.

### Option 1: FastEmbed (Recommended)
FastEmbed uses ONNX Runtime, requires no GPU, and offers high-throughput, low-latency CPU embedding:
```bash
pip install "cortexstone[embeddings]"
# or directly:
pip install fastembed>=0.4.0
```

### Option 2: SentenceTransformers (Alternative Fallback)
```bash
pip install sentence-transformers>=3.0.0
```

## Initialization & Usage

### 1. Default Initialization
```python
from cortexstone.memory.embeddings import BGEEmbeddingProvider

# Uses centralized BAAI/bge-small-en-v1.5 and dimension 384
provider = BGEEmbeddingProvider()

# Single text
vector = await provider.embed_text("Apurva deployed CortexStone.")
assert len(vector) == 384

# Query with automatic BGE search instruction prefix
query_vec = await provider.embed_query("Who deployed CortexStone?")
assert len(query_vec) == 384

# Batch processing
vectors = await provider.embed_batch(["text 1", "text 2"])
assert len(vectors) == 2
```

### 2. Custom Configuration
```python
from cortexstone.memory.embeddings import BGEEmbeddingProvider, EmbeddingConfig

config = EmbeddingConfig(
    provider_id="fastembed",
    model_id="BAAI/bge-small-en-v1.5",
    dimension=384,
    batch_size=64,
    request_timeout_seconds=30.0,
)
provider = BGEEmbeddingProvider(config=config)
```

### 3. Wiring into MemoryRetrievalService
```python
from cortexstone.memory.embeddings import BGEEmbeddingProvider
from cortexstone.memory.retrieval import MemoryRetrievalService

provider = BGEEmbeddingProvider()
service = MemoryRetrievalService(repository=memory_repo, embedding_provider=provider)
```

## Security & Reliability Invariants

1. **Zero Secret Leakage:** Embedding inputs are validated strictly, and vector validation/error logs never echo raw memory content, API tokens, or secrets.
2. **Dimension Integrity:** Output vectors are validated against the declared 384-dimensional constraint. Any mismatch raises `EmbeddingDimensionMismatchError`.
3. **Finite Floating-Point Numbers:** Vectors containing `NaN`, positive `inf`, or negative `inf` are rejected with `InvalidEmbeddingVectorError`.
4. **Non-blocking Concurrency:** Local CPU inference is executed on worker threads using `asyncio.to_thread`.
