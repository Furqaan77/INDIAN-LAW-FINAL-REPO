# IndianLawGPT POC: Repository Structure

This document outlines the organization of the IndianLawGPT repository, explaining where core code, data, tools, and evaluation artifacts reside.

## 1. Primary Application (`src/`)
This is the core runtime logic of the IndianLawGPT RAG application. Everything required to understand and run the pipeline is located here.
*   `app.py`: Streamlit frontend UI.
*   `rag_chain.py`: Orchestrator connecting retrieval, generation, and citation verification.
*   `search.py`: Hybrid search implementation (ChromaDB + SQLite FTS5).
*   `citation_verifier.py`: Extracts and deterministically validates LLM citations against evidence.
*   `db.py`: SQLite connection and initialization logic.
*   `ingest.py`, `chunk_embed.py`: Offline pipeline scripts to insert scraped cases into SQLite and ChromaDB.
*   `fetch_judgments.py`, `kanoon_client.py`: Human-in-the-loop scraping and data acquisition tools.

## 2. Data (`data/` & `db/`)
Contains the local structured knowledge base and raw scraped files.
*   `data/scraped_judgments/`: Raw JSON judgment files scraped from Indian Kanoon.
*   `data/case_lists/`: Curated `.txt` lists and original search query logs defining the dataset.
*   `db/nyayasetu.db`: The master structured database (SQLite) containing parsed text, metadata, and the FTS5 keyword index.
*   `db/chroma/`: The ChromaDB local vector store containing embedded semantic chunks.

*(Note: These files are required for the offline application to run and have deliberately NOT been git-ignored.)*

## 3. Development / Testing Tools (`tools/`)
Scripts used to analyze data, evaluate the pipeline, or debug the system. These scripts are not part of the runtime app.
*   `tools/evaluation/`: Scripts to run deterministic LLM evaluations (e.g., `evaluate_rag.py`, `smart_audit.py`).
*   `tools/testing/`: Scripts testing edge cases and logic (e.g., `test_bicycle.py`, `test_q1_fix.py`).
*   `tools/analysis/`: Scripts to examine database structures, generate dataset coverage reports, and repair schemas (e.g., `generate_coverage.py`, `check_schema.py`).

## 4. Evaluation Artifacts (`evaluation/`)
Contains non-executable generated artifacts and reports from running the tools. These are heavily git-ignored to prevent repository bloat.
*   `evaluation/results/`: Raw JSON output from running `evaluate_rag.py`.
*   `evaluation/audits/`: Granular outputs from deeper inspections (e.g., `audit_dump.txt`).
*   `evaluation/reports/`: Final human-readable markdown reports (e.g., Stance Fix experiments, Dataset Coverage, Threshold fixes).

## 5. Archive (`archive/`)
Historical items preserved for reference but completely unused by the active codebase.
*   `archive/obsolete_code/`: Outdated copies of core files (`rag_chain.py.bak`).
*   `archive/data_dumps/`: Temporary text dumps of the pipeline.

## 6. Gitignore Rules
The `.gitignore` is configured to exclude:
*   Local python caches (`__pycache__/`) and virtual environments (`venv/`).
*   Generated evaluation outputs in `evaluation/`.
*   Archive items (`archive/`).
*   Environment files (`.env`).
*   *It explicitly tracks `db/` and `data/` because the IndianLawGPT POC is designed to run offline against this pre-built corpus.*

## 7. How to Run
### Primary Application
Activate your virtual environment and run:
```bash
streamlit run src/app.py
```

### Evaluations
To run an evaluation tool from the root directory:
```bash
python tools/evaluation/evaluate_rag.py
```
*(Tools automatically configure their import paths to reference `src/` modules).*
