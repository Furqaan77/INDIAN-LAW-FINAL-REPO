"""
Vector store abstraction.

Swap providers via VECTOR_DB_PROVIDER in .env. Only "chroma" is implemented
today; add a new class + branch in get_vector_store() to support another
backend (e.g. pgvector, Qdrant) without touching search.py or the ingestion
scripts, which only depend on the VectorStore interface below.

Deliberately has no Streamlit dependency (unlike the old search.py) so it can
be called from ingestion scripts, evaluation scripts and tests, not just the
Streamlit app. Callers that want per-session caching (e.g. Streamlit) should
wrap get_vector_store() with their own cache.
"""
import threading
from functools import lru_cache
from typing import Any, Dict, List, Optional

from config import settings
from embeddings import get_embedding_function
from logging_config import get_logger

logger = get_logger("vector_store")


class ChromaVectorStore:
    def __init__(self, path: str = None, collection_name: str = None):
        self.path = path or settings.chroma_path
        self.collection_name = collection_name or settings.chroma_collection
        self._collection = None
        self._init_lock = threading.Lock()

    @property
    def collection(self):
        if self._collection is not None:
            return self._collection
        # The API serves requests on a thread pool; two first requests opening the client at once
        # race inside Chroma's shared-client cache (KeyError), so initialisation is serialised.
        with self._init_lock:
            if self._collection is None:
                import chromadb
                logger.info("Opening Chroma collection '%s' at %s", self.collection_name, self.path)
                client = chromadb.PersistentClient(path=self.path)
                embed_fn = get_embedding_function()
                # Explicit cosine space: query() below computes similarity as (1 - distance),
                # which is only a meaningful [-1, 1] score under cosine distance — Chroma's
                # default is squared L2, which would make that math nonsensical.
                self._collection = client.get_or_create_collection(
                    name=self.collection_name, embedding_function=embed_fn,
                    metadata={"hnsw:space": "cosine"},
                )
        return self._collection

    def upsert(self, ids: List[str], documents: List[str], metadatas: List[Dict[str, Any]], batch_size: int = 500):
        if not ids:
            return
        total_batches = (len(ids) + batch_size - 1) // batch_size
        for i in range(total_batches):
            start, end = i * batch_size, (i + 1) * batch_size
            try:
                self.collection.upsert(
                    ids=ids[start:end],
                    documents=documents[start:end],
                    metadatas=metadatas[start:end],
                )
            except Exception:
                logger.exception("Vector store upsert failed for batch %d/%d", i + 1, total_batches)
                raise
            logger.info("Upserted batch %d/%d (%d chunks)", i + 1, total_batches, end - start)

    def delete_by_doc_id(self, doc_id: str):
        try:
            self.collection.delete(where={"doc_id": doc_id})
        except Exception:
            logger.exception("Failed to delete existing chunks for doc_id=%s", doc_id)
            raise

    def query(
        self, query_text: str, top_k: int = 10, where: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        try:
            results = self.collection.query(query_texts=[query_text], n_results=top_k, where=where)
        except Exception:
            logger.exception("Vector store query failed")
            raise

        hits = []
        docs = results.get("documents") or [[]]
        metas = results.get("metadatas") or [[]]
        dists = results.get("distances") or [[]]
        if not docs or not docs[0]:
            return hits
        for doc, meta, dist in zip(docs[0], metas[0], dists[0]):
            hits.append({"text": doc, "metadata": meta, "score": 1 - dist})
        return hits


@lru_cache(maxsize=1)
def get_vector_store() -> ChromaVectorStore:
    provider = settings.vector_db_provider.lower()
    if provider == "chroma":
        return ChromaVectorStore()
    raise ValueError(
        f"Unknown VECTOR_DB_PROVIDER '{provider}'. Supported: 'chroma'. "
        "Add a new branch in vector_store.get_vector_store() to support more."
    )
