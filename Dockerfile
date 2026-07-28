# Market Consensus API.
#
# Docker rather than Railway's nixpacks autodetection, for one reason that matters:
# the embedding model is downloaded and cached at BUILD time (see FASTEMBED_CACHE
# below). With nixpacks it would download on first use into an ephemeral temp dir,
# so every deploy would stall its first request on a model fetch — and that request
# is already the slow ~40s cold path.

FROM python:3.13-slim

# curl is for the container healthcheck; nothing else needs a compiler because
# fastembed ships ONNX wheels (that's why it's used instead of sentence-transformers).
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    # Read by pipeline/embed.py. Must match the path warmed below and be inside the
    # image (NOT the volume) so it's immutable and present on every cold start.
    FASTEMBED_CACHE=/opt/models

WORKDIR /app

# Dependencies first — this layer caches across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Warm the embedding model into the image. This is the whole reason for the
# Dockerfile: ~130MB fetched once at build, never at runtime.
RUN python -c "\
from fastembed import TextEmbedding; \
TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='/opt/models'); \
print('embedding model cached into image')"

COPY . .

# The corpus lives on the mounted volume; scripts/bootstrap_corpus.py seeds it from
# seed/corpus.seed.db on first boot only. Railway injects $PORT.
ENV CONSENSUS_DB=/data/corpus.db
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT:-8000}/health" || exit 1

CMD ["sh", "-c", "python scripts/bootstrap_corpus.py && exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
