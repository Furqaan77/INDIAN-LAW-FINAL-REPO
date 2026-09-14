# IndianLawGPT Development Guide

## Environment Setup
1. Create a virtual environment: `python -m venv venv`
2. Activate it: `venv\Scripts\activate` (Windows) or `source venv/bin/activate` (Mac/Linux)
3. Install dependencies: `pip install -r requirements.txt`
4. Set up the `.env` file (copy from `.env.example`).
   - `OPENAI_API_KEY`: Required for embeddings.
   - `ANTHROPIC_API_KEY`: Required for answer generation.
   - See `.env.example` for the full list of provider/tuning settings (all optional besides
     the two keys above — everything else has a sane default).

## Ingesting Data
```bash
python src/init_db.py
python src/ingest.py --input data/sample_judgments/   # or data/scraped_judgments/
python src/chunk_embed.py                              # embeds case law into the vector store

# PDFs: drop files into data/pdfs/, then
python src/ingest_pdf.py --input data/pdfs/
```
The vector index must be rebuilt (`chunk_embed.py` / `ingest_pdf.py`) whenever
`EMBEDDING_MODEL` changes — vectors from different models aren't comparable.

## Running the Application
```bash
python -m streamlit run src/app.py
```
*Note: the vector store client is cached at process scope (`vector_store.py`, via
`functools.lru_cache`), not via Streamlit's `@st.cache_resource` — if you modify ingestion or
embedding code, restart the Streamlit server to pick up a rebuilt index.*

## Testing & Evaluation

### RAG Evaluation Suite
```bash
python src/evaluate_rag.py
python src/evaluate_rag.py --out data/eval/results/run.json   # also write a JSON report
```
Runs the question set in `data/eval/eval_questions.json` through the full pipeline and reports
citation-verification health — a regression guard on the hallucination guarantee, not a
legal-correctness grader.

## Code Standards
- **Instrument Everything**: Wrap major pipeline steps with `instrumentation.start()` and
  `instrumentation.end()` to track latencies; use `logging_config.get_logger(__name__)` for
  actual error/diagnostic logging (the two are complementary — timing vs. events).
- **Strict Citations**: Never allow the LLM to format `[SOURCE: id]` tokens itself. Use the
  deterministic Python citation mapper in `rag_chain.py` to extract the authoritative `doc_id`
  securely from the vector store's metadata payload, then verify it in `citation_verifier.py`.
- **New providers**: add a class + one branch in the relevant `get_*()` factory
  (`embeddings.py`, `llm_provider.py`, `vector_store.py`) — don't special-case a provider
  inline elsewhere in the codebase.
- **Do not modify `.env` loading**: `config.py` loads `.env` once via `python-dotenv`; other
  entry points (`app.py`) may also call `load_dotenv()` defensively, which is harmless (idempotent).
