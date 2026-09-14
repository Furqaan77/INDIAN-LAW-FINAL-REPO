"""
Central configuration for IndianLawGPT.

All provider selection (embeddings / vector DB / LLM) and tunables live here,
driven entirely by environment variables so the stack can be swapped without
touching code. Nothing here ever hardcodes a secret — API keys are read from
the environment only, and validation is lazy (a missing key only raises when
that specific provider is actually used).
"""
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _get_int(name: str, default: int) -> int:
    val = os.environ.get(name)
    if val is None or val == "":
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    val = os.environ.get(name)
    if val is None or val == "":
        return default
    try:
        return float(val)
    except ValueError:
        return default


def _get_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None or val == "":
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    # --- Providers (swap via env, no code changes) ---
    embedding_provider: str = field(default_factory=lambda: os.environ.get("EMBEDDING_PROVIDER", "openai"))
    vector_db_provider: str = field(default_factory=lambda: os.environ.get("VECTOR_DB_PROVIDER", "chroma"))
    llm_provider: str = field(default_factory=lambda: os.environ.get("LLM_PROVIDER", "anthropic"))

    # --- OpenAI embeddings ---
    openai_api_key: str = field(default_factory=lambda: os.environ.get("OPENAI_API_KEY", ""))
    embedding_model: str = field(default_factory=lambda: os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small"))
    embedding_batch_size: int = field(default_factory=lambda: _get_int("EMBEDDING_BATCH_SIZE", 100))

    # --- Anthropic (Claude) generation ---
    anthropic_api_key: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))
    anthropic_model: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5"))
    # 1500 was observed to truncate mid-JSON on thorough legal answers that cite multiple
    # excerpts with full verbatim quotes — a cut-off response breaks json.loads and silently
    # drops every citation for that answer. 4096 gives real headroom for that case.
    anthropic_max_tokens: int = field(default_factory=lambda: _get_int("ANTHROPIC_MAX_TOKENS", 4096))

    # --- Vector DB (Chroma) ---
    chroma_path: str = field(default_factory=lambda: os.environ.get(
        "CHROMA_PATH", os.path.join(os.path.dirname(__file__), "..", "db", "chroma")
    ))
    chroma_collection: str = field(default_factory=lambda: os.environ.get("CHROMA_COLLECTION", "legal_documents"))

    # --- SQLite ---
    sqlite_db_path: str = field(default_factory=lambda: os.environ.get(
        "SQLITE_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "db", "nyayasetu.db")
    ))

    # --- Chunking ---
    chunk_target_chars: int = field(default_factory=lambda: _get_int("CHUNK_TARGET_CHARS", 1200))
    chunk_overlap_chars: int = field(default_factory=lambda: _get_int("CHUNK_OVERLAP_CHARS", 150))

    # --- Retrieval ---
    default_top_k: int = field(default_factory=lambda: _get_int("DEFAULT_TOP_K", 5))
    retrieval_candidate_k: int = field(default_factory=lambda: _get_int("RETRIEVAL_CANDIDATE_K", 15))
    semantic_score_threshold: float = field(default_factory=lambda: _get_float("SEMANTIC_SCORE_THRESHOLD", 0.35))
    rerank_enabled: bool = field(default_factory=lambda: _get_bool("RERANK_ENABLED", True))
    max_chunks_per_document: int = field(default_factory=lambda: _get_int("MAX_CHUNKS_PER_DOCUMENT", 2))

    # --- Logging ---
    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO"))

    # --- HTTP API ---
    cors_origins: str = field(default_factory=lambda: os.environ.get(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ))

    def require_openai_key(self) -> str:
        if not self.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Add it to your .env file — it is required for "
                f"embedding_provider='{self.embedding_provider}'."
            )
        return self.openai_api_key

    def require_anthropic_key(self) -> str:
        if not self.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Add it to your .env file — it is required for "
                f"llm_provider='{self.llm_provider}'."
            )
        return self.anthropic_api_key


settings = Settings()
