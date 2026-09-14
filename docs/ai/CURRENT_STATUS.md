# Current Status (IndianLawGPT)

## V3.1 — Live end-to-end verification + statute corpus (2026-09-14)
- **Live pipeline verified with real API keys** (previously only smoke-tested without them).
  Rebuilt the vector index for all 194 case-law judgments via real OpenAI embeddings (7,296
  chunks), then ran representative Section 138 questions through the full pipeline end-to-end.
- **Three genuine bugs found and fixed during live testing**:
  1. `search_keyword()` (`db.py`) passed raw natural-language questions straight into SQLite
     FTS5 MATCH, which treats `?` and other punctuation as syntax — every real question broke
     keyword search silently. Fixed by tokenizing/quoting terms before the query.
  2. The configured Claude model rejects the `temperature` parameter outright (400 error).
     Removed it from the `ChatAnthropic` call in `llm_provider.py` (omitting it is safe for
     every model; pinning it isn't).
  3. `ANTHROPIC_MAX_TOKENS` defaulted to 1500, too low for a thorough legal answer plus full
     verbatim evidence quotes — responses got truncated mid-JSON, silently dropping every
     citation for that answer. Raised the default to 4096 and added a salvage-parser fallback
     that recovers whatever individual citations it can from a malformed/truncated response
     instead of discarding all of them.
  4. `sqlite3.OperationalError: database is locked` during large ingestion runs — a long-lived
     write transaction (committed only periodically) blocked concurrent reads through a
     separate connection. Fixed by enabling WAL mode (`PRAGMA journal_mode=WAL`) in
     `get_connection()`.
- **Statute corpus ingested**: `data/statutes/indian_law_corpus.jsonl` — 38,238 pre-segmented
  sections across 837 Indian Central Acts (sourced from
  [IndianLegalCorpus](https://github.com/AbdullahAnwar26/IndianLegalCorpus)) — via the new
  `ingest_statutes.py`. Each section is its own `documents` row (`source_type='statute'`),
  matching the natural citation unit ("Section 10 of the Indian Contract Act, 1872"). Result:
  38,432 total documents (194 case law + 38,238 statute), 64,651 vector chunks. Zero errors
  across the full run.
- **Eval suite refreshed**: two questions previously marked "expect no citation" (Hindu
  Marriage Act grounds for divorce, Motor Vehicles Act speed-limit framework) now correctly
  return grounded, verified citations against the new statute corpus — the old expectations
  were stale, not a bug. Replaced with genuinely out-of-scope questions (a fictional contract
  type, a foreign jurisdiction) to keep testing correct refusal. **Final: 11/11 passed, 0
  unverified citations.**
- **Project renamed** to IndianLawGPT across docs, README, and the Streamlit UI (the physical
  `db/nyayasetu.db` filename and `SQLITE_DB_PATH`/`CHROMA_PATH` defaults were deliberately left
  unchanged — renaming them is a follow-up, not done here to avoid touching a live DB path
  mid-ingestion).
- Nothing from this session has been committed or pushed — a separate repo is planned for
  further development.

## V3 Changes Completed (2026-09-14)
- **Provider swap**: Embeddings moved from local `sentence-transformers` to the OpenAI
  Embeddings API; generation moved from Groq/Ollama to Anthropic Claude. Both are behind
  swappable provider interfaces (`embeddings.py`, `llm_provider.py`), configured entirely via
  `.env` (`EMBEDDING_PROVIDER`, `LLM_PROVIDER`, model names, etc.) — no hardcoded keys anywhere.
- **Kanoon dependency removed**: `kanoon_client.py` and `fetch_judgments.py` deleted. PDFs are
  now the primary intended data source, ingested through a new pipeline (`pdf_extract.py` →
  `text_cleaning.py` → `legal_chunker.py` → `ingest_pdf.py`). The existing 194 scraped
  judgments remain valid data and continue to ingest through the JSON path (`ingest.py`).
- **Generalized schema**: SQLite's `cases` table is now `documents` (with `source_type`), so
  case-law and PDF-derived content share one table, one FTS index, and one citation-
  verification path. Full metadata (file name, page range, section heading, court/date for
  case law) is preserved per chunk for traceability.
- **Citation verification preserved and generalized**: still fully deterministic — the LLM
  never asserts a citable ID directly, only an `evidence_quote`; Python matches that quote
  against retrieved chunk text and takes the authoritative `doc_id` from vector-store metadata.
  The regex moved from a domain-hardcoded `NI138-\d+` pattern to a general `[SOURCE: doc_id]`
  token so PDFs and future document types verify through the same path.
- **Hybrid retrieval improved**: added a reranking/context-selection pass (`rerank.py`); fixed
  a latent V2 gap where keyword-only hits carried empty text and could never actually be cited.
- **Evaluation harness added**: `evaluate_rag.py` + `data/eval/eval_questions.json` — a
  regression guard on citation-verification health, runnable any time the pipeline changes.
- **Logging/error handling**: structured logging (`logging_config.py`, `LOG_LEVEL` env var)
  across all new/changed modules; retrieval and generation failures in `rag_chain.py` degrade
  to a clear message instead of crashing the app; missing API keys raise a clear, immediate
  error naming the exact env var to set.

## Migration note
The vector index (`db/chroma/`) was cleared — vectors from the old `all-MiniLM-L6-v2` model
are not compatible with OpenAI embeddings and must be rebuilt. `db/nyayasetu.db` was migrated
to the new `documents` schema with all 194 existing judgments re-ingested. Before first use:
set `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` in `.env`, then run
`python src/chunk_embed.py` to rebuild the vector index for the existing case law, and
`python src/ingest_pdf.py --input data/pdfs/` once PDFs are added.

## Health Check
- All new/changed modules verified to import and compile cleanly; SQLite ingestion, keyword
  search, citation verification, legal/PDF chunking, and PDF text extraction were smoke-tested
  end-to-end with synthetic and real sample data.
- The Streamlit app boots and serves without import errors.
- Live embedding/generation calls were **not** exercised in this pass (no API keys available in
  the dev environment) — the OpenAI and Anthropic call paths, and their error-handling
  fallbacks for a missing key, were verified directly.

## Next Steps / Future Roadmap
- Run `chunk_embed.py` and `ingest_pdf.py` against real OpenAI/Anthropic keys and confirm
  `evaluate_rag.py` passes with real citations once PDFs are provided.
- OCR for scanned/image-only PDFs (currently logged as a warning, not handled).
- Scale dataset with the provided PDF corpus; explore production deployment configurations.
