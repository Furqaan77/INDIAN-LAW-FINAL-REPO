# Frontend build — checkpoint (updated 2026-09-15)

Nothing has been committed or pushed (a separate repo is planned).

## Status: citation regression resolved

The evaluation suite is back to **11/11 with 0 unverified citations**. What was wrong, in order:
1. Prompt-only JSON: once answers became long Markdown, Claude often returned plain Markdown with no JSON.
   → Switched to tool-calling structured output (`with_structured_output`).
2. With `answer` first in the tool schema, Claude sometimes wrote the citations inside the answer string.
   → `citations` now comes first in the schema; embedded citation blocks are still recovered.
3. Claude sometimes sent `citations` as a string wrapped in its own `<parameter name="…">` markup.
   → `_coerce_citations` decodes plain JSON, `<parameter>`-wrapped JSON and `<citation>` XML.

Other bugs fixed during QA: Chroma client init race under concurrent API requests (lock),
HTML entities in scraped judgments shown raw (decoded in the API and client), dangling "vs ." case
titles, source-reader highlight bar not staying pinned, noisy compare diff (normalised comparison and
off by default when the texts differ heavily), bundle split by route (initial JS 685 kB → 481 kB).

## Visual QA done
Home, research progress, answer + evidence rail, citation hover preview and active state, source reader
with highlighted passages, search, compare, 404 / missing-research states, mobile (home, research,
evidence sheet) and dark mode — all reviewed with no console errors.

## How to run

```bash
cd src && ../.venv/bin/python -m uvicorn api:app --host 127.0.0.1 --port 8010   # port 8000 is used by another project
cd frontend && npm install && npm run dev                                      # http://127.0.0.1:5173
node frontend/qa/visual-qa.mjs home research citations source compare search mobile dark errors  # needs Playwright
cd src && ../.venv/bin/python evaluate_rag.py                                  # regression guard (11/11)
```

## Remaining / known limitations
1. Retrieval quality (backend): "punishment for cheating under the BNS" never retrieves BNS §318 —
   needs act-aware statute retrieval (filter/boost by a named Act, weight section headings).
2. Answers are sometimes nondeterministic in how many sources they cite; the eval guards presence of
   verified citations, not their number.
3. Data artifacts: some IPC sections end with the next chapter's heading; some scraped case titles omit
   the other party. Clean at ingestion time (requires re-embedding the affected text).
4. `db/` is ~1 GB — decide gitignore-and-rebuild vs. Git LFS for the new repo.
