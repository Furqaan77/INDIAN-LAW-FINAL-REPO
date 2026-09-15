# IndianLawGPT — Indian Legal AI (RAG)

A local-first RAG pipeline for Indian legal Q&A with strict zero-hallucination citation
verification, over curated case-law judgments, the full Indian Central Acts statute corpus, and
legal PDFs (further statutes, commentaries, judgments you provide).

## Architecture (V3)

```
PDFs ──► pdf_extract.py ──► text_cleaning.py ──► legal_chunker.py ──┐
                                                                     │
Case-law JSON ──► ingest.py ──────────────────────────────────────┐ │
                                                                    │ │
Statute corpus (JSONL) ──► ingest_statutes.py ───────────────────┐│ │
                                                                   ▼▼ ▼
                                              SQLite `documents` table (+ FTS5)
                                                                   │
                                          embeddings.py (OpenAI) ──┼──► vector_store.py (Chroma)
                                                                   │
                                                                   ▼
                                                   search.py — hybrid retrieval
                                              (ChromaDB semantic + SQLite FTS5 keyword)
                                                                   │
                                                       rerank.py — context selection
                                                                   │
                                              rag_chain.py — prompt assembly
                                                                   │
                                          llm_provider.py — Anthropic Claude (JSON answer +
                                                    evidence_quote citations)
                                                                   │
                                     Deterministic Python citation mapping (matches each
                                  evidence_quote against retrieved chunk text; extracts the
                                       authoritative doc_id from Chroma metadata — the
                                                model's own doc_id is never trusted)
                                                                   │
                                            citation_verifier.py — checks every [SOURCE: id]
                                                  token against the SQLite `documents` table
                                                                   │
                                          Streamlit UI (POC) — verified vs. unverified citations
```

## Why this order matters

An AI legal answer is only as good as (a) whether the right source was retrieved and (b)
whether the citation it produced actually exists. The LLM generates a JSON array of
`evidence_quotes`. Python deterministically string-matches these quotes against the retrieved
chunks and extracts the authoritative `doc_id` directly from the vector store's metadata
payload. `citation_verifier.py` then acts as the final gatekeeper against hallucinated
citations — a case ID or document that isn't in the database, or wasn't actually the source of
the matched quote, is always shown as unverified, never as fact.

## Modular by design

Every provider is swappable through `.env`, with no code changes required to swap them:

- `EMBEDDING_PROVIDER` (`embeddings.py`) — OpenAI today.
- `LLM_PROVIDER` (`llm_provider.py`) — Anthropic Claude today.
- `VECTOR_DB_PROVIDER` (`vector_store.py`) — Chroma today.

Add a new provider by adding one class + one branch in the relevant factory function; nothing
else in the codebase needs to change.

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Set OPENAI_API_KEY (embeddings) and ANTHROPIC_API_KEY (answer generation)

# 3. Initialize the database and ingest data
python src/init_db.py
python src/ingest.py --input data/sample_judgments/       # or data/scraped_judgments/
python src/chunk_embed.py                                  # embeds case law into the vector store

# To add PDFs: drop files into data/pdfs/, then
python src/ingest_pdf.py --input data/pdfs/

# 4. Run the web application
cd src && ../.venv/bin/python -m uvicorn api:app --host 127.0.0.1 --port 8010   # HTTP API
cd frontend && npm install && npm run dev                                      # http://127.0.0.1:5173

# (The original Streamlit POC still works: streamlit run src/app.py)
```

The web frontend (`frontend/`, Vite + React + TypeScript + Tailwind) talks to the pipeline only through
`src/api.py`: research answers stream progress as Server-Sent Events, then return numbered citations with
their verified source passages; the document reader, statute/case search and the old → new law map
(IPC↔BNS, CrPC↔BNSS, IEA↔BSA, Income-tax 1961↔2025) are separate endpoints. Research history is kept in
the browser. `frontend/qa/visual-qa.mjs` is a Playwright script that screenshots every screen for review.

## Demo (research prototype)

The question box has three answer-engine toggles — **Claude API** (Claude + IndianLawGPT RAG), **Plain Qwen**
(Qwen3 1.7B via Ollama + RAG) and **LoRA Qwen** (experimental fine-tuned Qwen3 1.7B via a local MLX service + RAG).
Choose one, two or all three: selected engines answer side by side from the **same frozen evidence**, with no fallback
between them. Every answer shows its evidence, the quotations the verifier matched or rejected, and model details.

```bash
ollama serve                                                    # Plain Qwen (ollama pull qwen3:1.7b once)
distill/finetune/.venv/bin/python distill/finetune/lora_server.py \
    --adapter artifacts/lora_demo_qwen3_1.7b --adapter-name lora_demo_qwen3_1.7b --port 8095   # LoRA Qwen
cd src && ../.venv/bin/uvicorn api:app --port 8010              # API
cd frontend && npm run dev -- --port 5174 --strictPort          # open http://localhost:5174
.venv/bin/python distill/diagnostics/demo_smoke_test.py         # optional pre-flight check
```

Full guide: [docs/DEMO.md](docs/DEMO.md). Engine integration details: [docs/LOQA_QWEN_RAG_INTEGRATION.md](docs/LOQA_QWEN_RAG_INTEGRATION.md).

*Note: the vector store must be rebuilt after switching embedding providers/models — vectors
from different models aren't comparable, so `chunk_embed.py` / `ingest_pdf.py` need to be
re-run whenever `EMBEDDING_MODEL` changes.*

## Adding new data

**Case-law JSON** — shape of `data/sample_judgments/*.json`:

```json
{
  "case_id": "NI138-2019-0042",
  "title": "Rajesh Kumar v. State Bank of India",
  "court": "Delhi High Court",
  "date": "2019-06-14",
  "judges": ["Justice A. Sharma"],
  "full_text": "..."
}
```

```bash
python src/ingest.py --input data/sample_judgments/
python src/chunk_embed.py
```

**PDFs** — drop any number of PDFs (statutes, commentaries, judgments) into `data/pdfs/`
(subfolders are fine) and run:

```bash
python src/ingest_pdf.py --input data/pdfs/
```

Already-ingested, unchanged PDFs are skipped automatically on re-runs (tracked by content
hash), so this is safe to run repeatedly as more PDFs are added over time. Pass `--force` to
re-ingest everything.

**Statute corpus** — `data/statutes/indian_law_corpus.jsonl` is a pre-segmented corpus of
Indian Central Acts (one record per statutory section, with act/section metadata), sourced from
[IndianLegalCorpus](https://github.com/AbdullahAnwar26/IndianLegalCorpus). Each section becomes
its own `documents` row (`source_type='statute'`) — the natural unit lawyers cite ("Section 10
of the Indian Contract Act, 1872") — so no further chunking is needed for the vast majority of
sections. Ingest with:

```bash
python src/ingest_statutes.py --input data/statutes/indian_law_corpus.jsonl
```

Already-ingested, unchanged sections are skipped automatically on re-runs (same idempotency
approach as PDFs, keyed by section content rather than a file hash). Pass `--force` to
re-embed everything, or `--limit N` to ingest only the first N records (useful for a smoke test
before a full run).

## Evaluation

```bash
python src/evaluate_rag.py
```

Runs a fixed set of test questions (`data/eval/eval_questions.json`) through the full pipeline
and reports citation-verification health: whether each question got a verified citation when
expected, and — critically — whether any unverified citation slipped through. This is a
regression guard on the citation-hallucination guarantee, not a legal-correctness grader.

## What's NOT in this MVP

OCR, citation graph, LoRA fine-tuning, drafting mode, multi-turn memory, Hindi/Whisper support,
Docker. Get this working end-to-end first.

## Folder structure

```
indianlawgpt/
├── src/
│   ├── app.py                # Streamlit UI (temporary POC UI)
│   ├── config.py             # Central, env-driven settings (all providers/tunables)
│   ├── logging_config.py     # Structured logging setup
│   ├── rag_chain.py          # RAG orchestration (retrieval -> LLM -> citation mapping)
│   ├── search.py             # Hybrid retrieval (ChromaDB + SQLite FTS5)
│   ├── rerank.py             # Context selection / reranking
│   ├── embeddings.py         # OpenAI embedding provider (swappable)
│   ├── llm_provider.py       # Anthropic Claude provider (swappable)
│   ├── vector_store.py       # Chroma vector store (swappable)
│   ├── citation_verifier.py  # Validation of LLM citations against SQLite
│   ├── db.py                 # SQLite schema + access (source-agnostic `documents` table)
│   ├── legal_chunker.py      # Structure-aware chunking (case-law + PDF, shared)
│   ├── pdf_extract.py        # Per-page PDF text extraction
│   ├── text_cleaning.py      # Header/footer/hyphenation cleanup
│   ├── ingest.py             # Ingest case-law JSON into SQLite
│   ├── ingest_pdf.py         # Full PDF ingestion pipeline (extract -> embed -> index)
│   ├── ingest_statutes.py    # Ingest the pre-segmented statute corpus (JSONL)
│   ├── chunk_embed.py        # Embed/index case-law documents already in SQLite
│   └── evaluate_rag.py       # Evaluation harness (citation-verification regression guard)
│
├── data/
│   ├── sample_judgments/     # Hand-crafted example case-law JSON
│   ├── scraped_judgments/    # Previously scraped case-law JSON (194 judgments)
│   ├── pdfs/                 # Drop PDFs here for ingestion (create as needed)
│   ├── statutes/             # Indian Central Acts corpus (JSONL, one record per section)
│   └── eval/                 # Evaluation question set
│
├── db/                       # SQLite (`nyayasetu.db`) + Chroma vector index
│
└── docs/
    ├── ai/                   # AI architecture & status
    └── dev/                  # Developer guides
```
