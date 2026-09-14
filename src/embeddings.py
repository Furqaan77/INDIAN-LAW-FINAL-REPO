"""
Embedding provider abstraction.

Swap providers via EMBEDDING_PROVIDER in .env. Only "openai" is implemented
today; add a new class + branch in get_embedding_function() to support
another provider without touching any caller.

Client pattern deliberately mirrors the sibling Health Coach AI project
(src/embed_corpus.py there): `langchain_openai.OpenAIEmbeddings(model=...)`,
which picks up OPENAI_API_KEY from the environment itself rather than us
threading a key through by hand. We still pre-check the key so a missing
one fails with a clear message immediately instead of on first use.

The returned object implements chromadb's EmbeddingFunction protocol
(`__call__(self, input: list[str]) -> list[list[float]]`) so it plugs
directly into vector_store.py.
"""
from functools import lru_cache
from typing import List

from config import settings
from logging_config import get_logger

logger = get_logger("embeddings")


class OpenAIEmbeddingFunction:
    """Chroma-compatible embedding function backed by langchain_openai.OpenAIEmbeddings."""

    def __init__(self, model: str = None):
        self.model = model or settings.embedding_model
        self._embeddings = None

    @property
    def embeddings(self):
        if self._embeddings is None:
            settings.require_openai_key()
            from langchain_openai import OpenAIEmbeddings
            self._embeddings = OpenAIEmbeddings(model=self.model)
        return self._embeddings

    def name(self) -> str:
        return f"openai:{self.model}"

    def __call__(self, input: List[str]) -> List[List[float]]:
        if not input:
            return []
        try:
            return self.embeddings.embed_documents(list(input))
        except Exception:
            logger.exception("OpenAI embeddings request failed (model=%s, batch_size=%d)", self.model, len(input))
            raise

    def embed_query(self, input: List[str]) -> List[List[float]]:
        """Chroma calls this (not __call__) for the query side of collection.query().
        Some embedding models score differently for a short query vs. a stored
        document; text-embedding-3 doesn't need that distinction, so this just
        reuses embed_documents for consistency."""
        return self(input)


@lru_cache(maxsize=1)
def get_embedding_function():
    """Returns the configured embedding function, cached for process lifetime."""
    provider = settings.embedding_provider.lower()
    if provider == "openai":
        logger.info("Using OpenAI embedding function (model=%s)", settings.embedding_model)
        return OpenAIEmbeddingFunction()
    raise ValueError(
        f"Unknown EMBEDDING_PROVIDER '{provider}'. Supported: 'openai'. "
        "Add a new branch in embeddings.get_embedding_function() to support more."
    )
