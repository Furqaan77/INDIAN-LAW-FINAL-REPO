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

    # --- Ollama (local generation; used when LLM_PROVIDER=ollama) ---
    ollama_base_url: str = field(default_factory=lambda: os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    ollama_model: str = field(default_factory=lambda: os.environ.get("OLLAMA_MODEL", "qwen3:1.7b"))
    ollama_num_ctx: int = field(default_factory=lambda: _get_int("OLLAMA_NUM_CTX", 8192))
    ollama_max_tokens: int = field(default_factory=lambda: _get_int("OLLAMA_MAX_TOKENS", 1024))
    ollama_timeout: int = field(default_factory=lambda: _get_int("OLLAMA_TIMEOUT", 180))
    ollama_keep_alive: str = field(default_factory=lambda: os.environ.get("OLLAMA_KEEP_ALIVE", "30m"))

    # --- LoRA Qwen (EXPERIMENTAL; local MLX service distill/finetune/lora_server.py) ---
    lora_qwen_url: str = field(default_factory=lambda: os.environ.get("LORA_QWEN_URL", "http://127.0.0.1:8095"))
    # Must match the adapter name the service reports; swap both to test another adapter.
    lora_adapter_name: str = field(default_factory=lambda: os.environ.get("LORA_ADAPTER_NAME", "lora_demo_qwen3_1.7b"))
    lora_adapter_label: str = field(default_factory=lambda: os.environ.get("LORA_ADAPTER_LABEL", "Experimental LoRA Pilot — 30 examples"))
    lora_base_model: str = field(default_factory=lambda: os.environ.get("LORA_BASE_MODEL", "Qwen3-1.7B"))
    lora_max_tokens: int = field(default_factory=lambda: _get_int("LORA_MAX_TOKENS", 1600))
    lora_timeout: int = field(default_factory=lambda: _get_int("LORA_TIMEOUT", 300))

    # --- Answer engines (research UI + three-model benchmark; src/engines.py) ---
    # Retries after a MALFORMED or TRUNCATED structured output, applied identically to every engine.
    engine_max_retries: int = field(default_factory=lambda: _get_int("ENGINE_MAX_RETRIES", 1))
    # "dataset": append the distillation answer instruction (what the LoRA student was trained with) for
    # every engine, so all engines see the identical prompt; "none": the app's plain research prompt.
    engine_answer_instruction: str = field(default_factory=lambda: os.environ.get("ENGINE_ANSWER_INSTRUCTION", "dataset"))
    evidence_cache_ttl_s: int = field(default_factory=lambda: _get_int("EVIDENCE_CACHE_TTL_S", 3600))
    engine_telemetry_path: str = field(default_factory=lambda: os.environ.get(
        "ENGINE_TELEMETRY_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "telemetry", "engine_requests.jsonl")
    ))

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
    # "rrf" fuses semantic, keyword, explicit-reference and old/new-mapping rankings (rerank.py);
    # "weighted" is the previous 0.75 x semantic + 0.25 x word-overlap scoring, kept for rollback.
    rerank_strategy: str = field(default_factory=lambda: os.environ.get("RERANK_STRATEGY", "rrf"))
    rrf_k: int = field(default_factory=lambda: _get_int("RRF_K", 60))
    # Weighted strategy only: the rrf strategy gives each selected document one evidence block.
    max_chunks_per_document: int = field(default_factory=lambda: _get_int("MAX_CHUNKS_PER_DOCUMENT", 1))
    reference_lookup_enabled: bool = field(default_factory=lambda: _get_bool("REFERENCE_LOOKUP_ENABLED", True))
    mapping_lookup_enabled: bool = field(default_factory=lambda: _get_bool("MAPPING_LOOKUP_ENABLED", True))
    mapping_max_per_reference: int = field(default_factory=lambda: _get_int("MAPPING_MAX_PER_REFERENCE", 3))
    # Final-context slots never given to reserved (explicitly required) sources, kept for discovery.
    min_discovery_slots: int = field(default_factory=lambda: _get_int("MIN_DISCOVERY_SLOTS", 2))
    act_scope_enabled: bool = field(default_factory=lambda: _get_bool("ACT_SCOPE_ENABLED", True))
    case_law_subquery_enabled: bool = field(default_factory=lambda: _get_bool("CASE_LAW_SUBQUERY_ENABLED", True))
    section_context_max_chars: int = field(default_factory=lambda: _get_int("SECTION_CONTEXT_MAX_CHARS", 4000))
    section_context_chunks: int = field(default_factory=lambda: _get_int("SECTION_CONTEXT_CHUNKS", 2))

    # --- Logging ---
    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO"))

    # --- HTTP API ---
    cors_origins: str = field(default_factory=lambda: os.environ.get(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ))

    @property
    def llm_model(self) -> str:
        """The model actually generating answers, whichever provider is selected."""
        return self.ollama_model if self.llm_provider.lower() == "ollama" else self.anthropic_model

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
