"""Embeddings — local, free, 384-dim vectors for semantic subject search.

Backend: `fastembed` (ONNX runtime) with BAAI/bge-small-en-v1.5 (384-dim). Chosen
over sentence-transformers because it avoids the PyTorch dependency, keeping the
deployed image light — while giving MiniLM-class quality. The model is downloaded
once on first use and cached under ~/.cache.

Kept behind this small interface (`embed_texts` / `embed_one` / `DIM`) so the
backend can be swapped without touching callers. The vectors feed pgvector
similarity search (or the local SQLite fallback) in the item store.
"""

from __future__ import annotations

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIM = 384  # dimensionality of the vectors this model emits

_model = None


def _get_model():
    """Lazily construct the (heavyweight) embedding model as a process singleton."""
    global _model
    if _model is None:
        from fastembed import TextEmbedding

        _model = TextEmbedding(model_name=MODEL_NAME)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts → list of 384-float vectors (order preserved)."""
    if not texts:
        return []
    model = _get_model()
    # fastembed yields numpy arrays; convert to plain lists for JSON/DB portability.
    return [vec.tolist() for vec in model.embed(texts)]


def embed_one(text: str) -> list[float]:
    """Embed a single text → one 384-float vector."""
    return embed_texts([text])[0]
