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

import os

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIM = 384  # dimensionality of the vectors this model emits

# Where fastembed keeps the downloaded ONNX weights. Unset locally → fastembed's
# default (a temp dir). That default is wrong in a container: /tmp does not survive
# a restart, so every deploy would re-download the model on the first request and
# stall it. The Dockerfile sets this to a baked-in image path and pre-downloads at
# BUILD time, so runtime never fetches anything.
CACHE_DIR = os.getenv("FASTEMBED_CACHE") or None

_model = None


def _get_model():
    """Lazily construct the (heavyweight) embedding model as a process singleton."""
    global _model
    if _model is None:
        from fastembed import TextEmbedding

        kwargs = {"cache_dir": CACHE_DIR} if CACHE_DIR else {}
        _model = TextEmbedding(model_name=MODEL_NAME, **kwargs)
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
