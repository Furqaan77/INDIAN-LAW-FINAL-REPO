# Project Overview

## What IndianLawGPT Is
IndianLawGPT is an AI-powered legal research tool tailored for Indian law. Data (case law, PDFs)
and search are local (SQLite + Chroma); embeddings and answer generation call the OpenAI and
Anthropic APIs respectively.

## The Problem It Solves
Standard AI language models frequently hallucinate legal citations, creating fake case laws that look authentic. IndianLawGPT solves this by forcing the AI to cite sources from a verified local database, actively verifying these citations before presenting them to the user.

## Scope
Originally a strict POC on Section 138 of the Negotiable Instruments Act, 1881 (cheque
dishonour/bounce cases) with ~194 hand-curated judgments. The ingestion pipeline now also
accepts arbitrary legal PDFs (statutes, commentaries, further judgments) as its primary data
source going forward, so scope is expected to broaden as PDFs are added — the pipeline is not
hardcoded to Section 138.

## What Makes IndianLawGPT Different
**Citation Verification:** The system intercepts the AI's response and checks every single case ID cited against the local database. If a case isn't in the database, it's flagged as unverified (⚠️). Verified citations are marked clearly (✅).

## Main Technologies
- **Python**
- **SQLite** (Storage & Keyword Search)
- **ChromaDB** (Vector Search)
- **Anthropic Claude API** (Answer Generation)
- **OpenAI Embeddings API** (Embeddings)
- **Streamlit** (Web UI — temporary POC)
- **pypdf** (PDF text extraction)

All four providers (embeddings, LLM, vector DB) are swappable via `.env` — see
`docs/ai/ARCHITECTURE.md`.

## Simple Request Lifecycle
1. **Question**: User asks a legal question in the UI.
2. **Hybrid Search**: System searches both ChromaDB (meaning) and SQLite (exact keywords), then reranks/selects context.
3. **LLM Generation**: Anthropic Claude generates a JSON response with natural language answer and evidence quotes.
4. **Deterministic Mapping**: Python maps the generated quotes to the retrieved chunks to securely extract the `[SOURCE: doc_id]`.
5. **Citation Verifier**: The system verifies the extracted tags against SQLite.
6. **Answer**: User sees the final answer with verified/unverified markers.

## Simple Project Structure
- `data/`: Raw judgment JSONs, PDFs (`data/pdfs/`), and the evaluation question set.
- `db/`: The local SQLite and ChromaDB databases.
- `src/`: Core Python scripts (ingestion, search, verification, app).

## Intentionally Not Part of this POC
- Drafting legal documents
- Chat history/memory
- Docker or cloud deployment
- Fine-tuning models
