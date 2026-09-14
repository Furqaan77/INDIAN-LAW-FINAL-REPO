# IndianLawGPT POC: Final Repository Structure

## Final Folder Structure
```text
indianlawgpt/
│
├── src/                      # PRIMARY APPLICATION (Git-tracked)
│   ├── app.py                # Streamlit UI
│   ├── rag_chain.py          # RAG pipeline orchestration
│   ├── search.py             # Hybrid retrieval logic
│   ├── citation_verifier.py  # Validation of LLM citations
│   ├── db.py                 # SQLite configuration
│   ├── chunk_embed.py        # Offline embedding logic
│   ├── ingest.py             # Offline data ingestion
│   ├── fetch_judgments.py    # Offline scraper 
│   └── kanoon_client.py      # Indian Kanoon API client
│
├── data/                     # RUNTIME DATA (Git-tracked)
│   ├── scraped_judgments/    # Raw JSON judgments
│   └── case_lists/           # Original search queries and curation lists
│
├── db/                       # RUNTIME DATABASE (Git-tracked)
│   ├── nyayasetu.db          # SQLite structured metadata and FTS5 index
│   └── chroma/               # ChromaDB semantic vector index
│
├── docs/                     # DOCUMENTATION (Git-tracked)
│   └── ...                   # Architectural documentation
│
├── tools/                    # DEVELOPMENT TOOLS (Git-ignored)
│   ├── analysis/             # Dataset coverage, schema checking
│   ├── evaluation/           # RAG evaluation scripts, audit generation
│   └── testing/              # Smoke tests, threshold regression tests
│
├── evaluation/               # GENERATED REPORTS (Git-ignored)
│   ├── audits/               # Deep-dive text dumps
│   ├── reports/              # Final Markdown reports (coverage, fixes)
│   └── results/              # JSON evaluation outputs
│
├── archive/                  # HISTORICAL (Git-ignored)
│   └── data_dumps/           # Temporary dumps
│
├── .env                      # Environment Variables (Git-ignored)
├── .gitignore                # Gitignore configuration
├── requirements.txt          # Python dependencies
└── README.md                 # Primary entrypoint documentation
```

## Runtime Dependencies & Files
To run the primary application, the following files MUST be present:
1. `src/*`: The core python scripts.
2. `db/nyayasetu.db`: The SQLite corpus. Without this, FTS5 keyword search and case metadata lookups fail.
3. `db/chroma/`: The local vector database. Without this, semantic search fails.
4. `requirements.txt`: Python packages (`streamlit`, `chromadb`, `sentence-transformers`, `sqlite3`, etc.)

## How to Run the POC
1. Ensure the virtual environment is activated and dependencies are installed.
2. Ensure Ollama is running locally with `llama3.1:8b` pulled.
3. Run the Streamlit application:
```bash
streamlit run src/app.py
```

## How to Run Evaluations Separately
Evaluation scripts have been moved to `tools/evaluation/`. They automatically append `src/` to their python path, meaning they can be run securely from the root:
```bash
python tools/evaluation/evaluate_rag.py
```
Outputs from these runs should be directed to `evaluation/results/`.

## Ignored Development Files
The `.gitignore` has been updated to explicitly ignore:
*   `tools/`
*   `evaluation/`
*   `archive/`
*   `venv/` & `__pycache__/`
*   `.env`

**Why?** These folders contain highly valuable historical context (proving the origin of the dataset, diagnosing the Q2 stance mismatch, and demonstrating the citation verification fix). However, they are NOT required to run the final Streamlit application. They are preserved locally for the developer but shielded from Git to keep the primary repository lean and purpose-built.

## Deleted Files
*   `archive/obsolete_code/citation_verifier.py.bak`
*   `archive/obsolete_code/rag_chain.py.bak`
*   `archive/obsolete_code/nyayasetu_backup.db`
*   Temporary script fragments at the project root (`organize_repo.py`, `final_cleanup.py`, etc.)

**Why?** These were redundant backups and temporary scaffolding used for the reorganization task. They hold no historical or runtime value.

## Known Limitations
*   **Stance Mismatch**: The local 8B LLM occasionally hallucinates contradictory stance logic when handling double-negatives in complex case law. This is a known POC limitation documented in `evaluation/reports/stance_prompt_fix_2026_08_31_1500/`. A fragile Python deterministic fix was intentionally rejected.
*   **Hardware Constrained**: Inference takes 1-3 minutes per query due to the CPU-only environment.

## Conclusion
The IndianLawGPT POC is now strictly segregated. The Git tree reflects a clean, production-ready snapshot of the architecture, while the historical journey remains securely logged in the local ignored directories. The POC is frozen.
