# Project Context: IndianLawGPT

## Vision
IndianLawGPT is an offline-capable, local-first RAG (Retrieval-Augmented Generation) system for Indian Legal judgments (specifically Section 138 of the Negotiable Instruments Act).

## Core Directives
1. **Zero Hallucination Tolerance**: The system strictly maps generated quotes to retrieved chunks. Unverified citations must be flagged to the user.
2. **Speed**: The system utilizes a V2 optimization caching ML models and leveraging Groq's API (`USE_GROQ=true`) to bring latency down from ~150s to ~2s per query.
3. **Robustness**: Local CPU execution via Ollama (`llama3.1:8b`) remains the fallback. To support smaller, less capable models, formatting constraints have been lifted from the LLM prompt. The system uses deterministic Python mapping to enforce output structures.

## AI Agent Rules
- **DO NOT** modify the V2 Groq optimization (`@st.cache_resource` in `search.py` and `USE_GROQ` branching in `rag_chain.py`).
- **DO NOT** reintroduce LLM citation formatting constraints. The prompt explicitly forbids the LLM from outputting `[CASE: xxx]`. The Python logic in `rag_chain.py` handles this.
- **DO NOT** modify `citation_verifier.py`. It is the last line of defense against hallucinations.
- **ALWAYS** check `run_ui_test_cached.py` to ensure Streamlit threading and caching still function if you touch `search.py` or `rag_chain.py`.
