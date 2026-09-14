# AI Development Changelog

## [V3 Architecture] - 2026-09-14
### Added
- Swappable provider layer: `config.py` (env-driven settings), `embeddings.py`, `llm_provider.py`,
  `vector_store.py` — each a small interface + factory, so the embedding provider, LLM provider,
  and vector DB can each be changed via `.env` alone.
- OpenAI Embeddings API integration (replaces local `sentence-transformers`).
- Anthropic Claude integration for answer generation (replaces Groq/Ollama), following the same
  `langchain_anthropic.ChatAnthropic` client pattern used in the sibling Health Coach AI project.
- PDF ingestion pipeline: `pdf_extract.py`, `text_cleaning.py`, `legal_chunker.py` (shared with
  case-law chunking), `ingest_pdf.py` — page-number- and section-aware, idempotent by content hash.
- `rerank.py`: context-selection pass between hybrid retrieval and prompt assembly.
- `logging_config.py`: structured logging across all modules (`LOG_LEVEL` env var).
- `evaluate_rag.py` + `data/eval/eval_questions.json`: citation-verification regression harness.

### Changed
- SQLite `cases` table generalized to `documents` (adds `source_type`, `file_name`,
  `metadata_json`) so case-law and PDF content share one table, one FTS index, and one
  citation-verification path.
- Citation token generalized from a domain-hardcoded `[CASE: NI138-\d+]` pattern to
  `[SOURCE: doc_id]`, verified the same deterministic way (LLM never asserts an ID directly).
- `search.py` no longer depends on Streamlit (`@st.cache_resource` moved to a plain
  process-level cache in `vector_store.py`), so it can be called from ingestion/eval scripts too.
- Hybrid retrieval fix: keyword-only hits previously carried empty text and could never actually
  be cited; they now pull the document's stored full text.
- `rag_chain.py`: retrieval and generation failures now degrade to a clear error response
  instead of raising an uncaught exception.

### Removed
- `kanoon_client.py`, `fetch_judgments.py` (Indian Kanoon API ingestion workflow).
- `ollama`, `groq` dependencies; unused `langchain`/`langchain-community`/`sentence-transformers`
  replaced with `langchain-openai`, `langchain-anthropic`, `pypdf`.
- The old Chroma vector index (`db/chroma/`) — incompatible with the new embedding model and
  rebuilt from scratch via `chunk_embed.py` / `ingest_pdf.py`.

## [V2 Architecture] - 2026-09-03
### Added
- Integrated Groq Cloud API for near-instant (~2s) generation via `qwen/qwen3.6-27b`.
- Deterministic Python Metadata Mapping: `rag_chain.py` now maps `evidence_quote` directly to the retrieved chunk metadata, extracting authoritative `case_id` safely.
- Added `@st.cache_resource` in Streamlit to eliminate the 30s ML model initialization penalty.
- Configured JSON schema enforcement for both Groq and Ollama.

### Removed
- Entirely removed the 48-second `CITATION_REMINDER` retry loop from `rag_chain.py` as it is no longer needed.
- Removed prompt instructions demanding the LLM embed citation tokens inside prose.

### Changed
- Fixed `.env` loading upstream in `app.py` so `USE_GROQ=true` is respected natively.
- Hybrid search deduplication now safely handles multiple chunks returned from the same case.

## [V1 Baseline]
- Initial creation of IndianLawGPT RAG MVP.
- Basic hybrid search (ChromaDB + SQLite).
- Strict hallucination verification via `citation_verifier.py`.
