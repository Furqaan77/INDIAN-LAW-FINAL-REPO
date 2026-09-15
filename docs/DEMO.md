# IndianLawGPT — Demo Guide

A research prototype. Not a production system and not legal advice.

---

## 1. What IndianLawGPT is

IndianLawGPT is an evidence-grounded legal research system for Indian law. It retrieves statutory sections and
judgments from a local legal database, has an answer engine write an analysis **only from the retrieved passages**,
and then checks every citation deterministically. If a quotation is not in the evidence, or a source does not exist in
the database, the citation is rejected and the rejection is shown.

## 2. What has been built

| Capability | Where to see it in the demo |
|---|---|
| Indian legal knowledge base: 38,238 statutory sections from 832 Central Acts, 194 judgments, 64,651 indexed passages (live figures) | Home page figures |
| Hybrid retrieval: semantic (OpenAI embeddings, Chroma) + keyword (SQLite FTS5) | Evidence rail → *All retrieved evidence* shows each source's retriever and rank |
| Legal-reference detection ("Section 138 of the NI Act", "Section 438 CrPC") | Sources tagged *Named in the question* |
| Old law ↔ new law mapping (IPC↔BNS, CrPC↔BNSS, IEA↔BSA, Income-tax Act 1961↔2025) | Sources tagged *Old/new-law counterpart*; the **Old → New law** page |
| Reranking (reciprocal rank fusion) | Ranked order of *All retrieved evidence* |
| Frozen evidence shared by all engines | Flow strip on the research page: `N evidence sources · frozen · ev-…` |
| Three answer engines: Claude API, Plain Qwen, LoRA Qwen (experimental) | *Choose answer engine* buttons; *Model details* |
| No silent fallback between engines | An unavailable engine shows **Engine unavailable** |
| Deterministic citation mapping and verification | *Citation verification* panel under each answer; *Show rejected quotations* |
| Source and document reader with highlighted passages | *Open source* on any cited source |
| Insufficient-evidence behaviour | Demo question 8 |

## 3. Architecture

```
Legal PDFs / Statutes / Judgments
        ↓
Text extraction
        ↓
Legal structure + chunking            sections, headings, page spans
        ↓
OpenAI embeddings                     text-embedding-3-small
        ↓
Vector database + SQLite FTS          Chroma · BM25
        ↓
Hybrid retrieval                      semantic + keyword
        ↓
Legal reference detection             explicit sections, old ↔ new law counterparts
        ↓
Reranking                             reciprocal rank fusion, reserved slots for named sources
        ↓
Frozen evidence                       one evidence_id per question
        ↓
Answer engine                         Claude API │ Plain Qwen │ LoRA Qwen
        ↓
Citation mapping                      each quotation → the retrieved passage that contains it
        ↓
Citation verification                 each source checked in the legal database
        ↓
Verified legal answer
```

Code: `src/search.py`, `src/legal_references.py`, `src/rerank.py`,
`src/rag_chain.py`, `src/engines.py`, `src/llm_provider.py`, `src/citation_verifier.py`, `src/api.py`; UI in
`frontend/src`. Engine details: `docs/LOQA_QWEN_RAG_INTEGRATION.md`.

## 4. How to start the demo

Four processes, each in its own terminal, from the repository root (`LegalPOC/`).

```bash
# 1. Ollama (Plain Qwen). Use the Ollama desktop app, or in a normal terminal:
ollama serve                      # model: ollama pull qwen3:1.7b  (once)

# 2. LoRA Qwen service (see section 5)
distill/finetune/.venv/bin/python distill/finetune/lora_server.py \
    --adapter artifacts/lora_demo_qwen3_1.7b --adapter-name lora_demo_qwen3_1.7b --port 8095

# 3. API (needs OPENAI_API_KEY and ANTHROPIC_API_KEY in .env)
cd src && ../.venv/bin/uvicorn api:app --port 8010

# 4. Frontend
cd frontend && npm run dev -- --port 5174 --strictPort
```

Open **http://localhost:5174**. (Port 5174 is used because 5173 may be taken by another local project; any free
port works — Vite proxies `/api` to `http://127.0.0.1:8010`.)

Pre-flight check (about 8 minutes, uses a few Claude calls):

```bash
curl -s localhost:8010/api/engines          # all three engines "available": true
.venv/bin/python distill/diagnostics/demo_smoke_test.py
```

Before presenting:

- **Do not run the benchmark during the demo.** It uses the same local LoRA service and Ollama model, so LoRA answers
  would queue behind it.
- Check Anthropic credits (the Claude engine returns *Engine unavailable* when credits run out).
- Warm the local models by asking one question with Plain Qwen and LoRA Qwen (first load takes 10–20 s).

## 5. How to start the LoRA server

```bash
distill/finetune/.venv/bin/python distill/finetune/lora_server.py \
    --adapter artifacts/lora_demo_qwen3_1.7b --adapter-name lora_demo_qwen3_1.7b --port 8095
curl -s localhost:8095/health
# {"status": "ok", "model": "Qwen3-1.7B-4bit", "adapter_name": "lora_demo_qwen3_1.7b", "adapter_sha256": "0fbc556685d8f7a2", ...}
```

It loads the 4-bit Qwen3-1.7B base with the LoRA adapter (never merged), answers one generation at a time, and reports
its adapter on every response. The API refuses answers from a service that serves a different adapter.

## 6. How to use the three engines

The engines are chosen in the question box itself, on the home page and at the bottom of every answer.

1. Under the question, **Answer with** shows three toggle buttons: **Claude API**, **Plain Qwen**, **LoRA Qwen**
   (EXPERIMENTAL), plus **All 3**. Select one, any two, or all three (at least one stays selected). The choice is
   remembered for the next question.
2. Type any question (or click an example) and press Enter.
3. **One engine selected:** a single answer with the Evidence rail on the right. Click a citation marker `[1]` to
   highlight its source; open *All retrieved evidence* to show how each source was found.
4. **Two or three engines selected:** the answers appear **side by side**, one column per engine. Retrieval runs once;
   the first engine freezes the evidence and the others answer from it one after another (each column shows *Queued*,
   the current step, then the answer). Above the columns, the flow strip shows the frozen evidence id and a table
   compares output status, verified/cited, rejected quotations, retries and time, confirming identical evidence.
   Each column has its own citation verification, **Evidence** button (opens that engine's sources) and **Model details**.
5. Change engines after asking with the same toggles above the answer: adding an engine answers the same question from
   the same evidence; removing one hides its column.
6. **Model details** under any answer: engine, model, role, runtime, adapter, evidence id, timings, citations, retries,
   output status.

| Engine | What it is | Role | Runtime |
|---|---|---|---|
| Claude API | Claude + IndianLawGPT RAG | Teacher / reference model | Anthropic API |
| Plain Qwen | Qwen3 1.7B + RAG | Base local model (control) | Ollama |
| LoRA Qwen | Fine-tuned Qwen3 1.7B + RAG — **EXPERIMENTAL** | Experimental fine-tuned student | MLX local service |

If an engine is down, its button dot turns red and the answer area shows **Engine unavailable** with the engine's own
message (for example "LoRA Qwen unavailable. Check the local MLX model service."). No other model answers.

## 7. Demo questions

Shown as clickable examples under the question box on the home page; stored in
`frontend/src/demo/demoQuestions.ts` (edit freely). Clicking one asks it with the engines currently selected. Each was run against the current corpus before being added.

| # | Capability | Question |
|---|---|---|
| 1 | Procedural question | What is the limitation period for filing a complaint under Section 138 of the Negotiable Instruments Act? |
| 2 | Punishment | What is the punishment for dishonour of a cheque under Section 138 of the Negotiable Instruments Act? |
| 3 | Multiple sections | How do Sections 138 and 142 of the Negotiable Instruments Act work together when a cheque is dishonoured? |
| 4 | Old law → new law | Which section of the Bharatiya Nagarik Suraksha Sanhita corresponds to anticipatory bail under Section 438 of the Code of Criminal Procedure? |
| 5 | Legal definition | How does Section 415 of the Indian Penal Code define cheating? |
| 6 | Section identification | What section of the Motor Vehicles Act governs how speed limits are fixed for vehicles on Indian roads? |
| 7 | Case law | Can a cheque given as security, rather than for an existing debt, still attract Section 138 liability? |
| 8 | Insufficient evidence | Under Indian law, what is the standard warranty period for a spacecraft launch services contract? |
| 9 | Old → new law map | IPC Section 420 → Bharatiya Nyaya Sanhita (opens the law map) |

Case law in the corpus is a focused collection on Section 138 of the Negotiable Instruments Act; statutory coverage is
all Central Acts from India Code.

## 8. What the citation verifier does

The answer engine is never trusted to cite correctly. For every answer, whichever engine wrote it:

1. The engine must return each claim's evidence as an exact quotation.
2. **Mapping** — each quotation is normalised and searched for in the retrieved passages. The source is the passage
   that actually contains it; the document id the model claimed is ignored. A quotation found in no passage is
   **rejected** and its citation marker is removed from the answer.
3. **Verification** — every mapped source id is checked against the legal database (`citation_verifier.py`).
4. The UI reports all of it: quotations proposed, matched and rejected (with the rejected text), and sources
   verified. Nothing is repaired silently.

This is fully deterministic — no model judges the citations.

**What it does not do:** verification proves that a quotation really exists in a real, retrieved source. It does
**not** prove that the quotation supports the claim made in the answer. Example from the demo test (question 8,
spacecraft launch warranty): LoRA Qwen answered "twelve years, as it is the term of lease" and cited a genuine
quotation from Section 13 of the Sale of Goods Act — the citation is *verified*, but the claim is invented. Claude,
on the same evidence, said the excerpts do not address the question. Judging whether evidence supports a claim
needs a legal reader (or, in the research benchmark, a separate grader); it is not something the verifier claims.

## 9. Current limitations

- Research prototype: accuracy is not guaranteed; always read the source.
- Case law is limited to 194 judgments, mostly on Section 138 NI Act; questions on other areas rely on statutes only.
- Retrieval can miss a governing section when a question names no section (e.g. "How does the Consumer Protection Act
  define a consumer?" retrieves the Act's other sections but not its definitions section); the answer then says the
  evidence is insufficient rather than guessing.
- The 1.7B Qwen models often paraphrase instead of quoting exactly, so many of their citations are rejected by the
  verifier; their answers are shorter and less reliable than Claude's. They can also answer questions the evidence
  does not cover (see §8) — use Claude for the insufficient-evidence demonstration.
- Citation verification confirms quotations exist in real sources; it does not check that they support the claim (§8).
- Claude occasionally returns a malformed tool call (citations as a string); it is recovered for display and reported
  as MALFORMED, and the engine path retries once.
- Local engines answer one request at a time; latency is roughly 10–30 s per answer.
- Evidence freezing lives in API memory; restarting the API re-retrieves evidence for a question.
- History is stored in the browser (localStorage), per device.

## 10. Current LoRA research status

- Adapter `artifacts/lora_demo_qwen3_1.7b` (label: *Experimental LoRA Pilot — 30 examples*): LoRA rank 8 on 4-bit
  Qwen3-1.7B, trained on 30 verified Claude + RAG answers.
- Pilot benchmark (50 held-out questions, strict scoring): overall score 39.7 vs 28.8 for the base MLX model, driven by
  citation formatting (accurate citations 31/50 vs 0/50); **legal correctness fell** (fully correct 6/50 vs 15/50).
  Verdict: *REGRESSION — INVESTIGATE*. Full report: `data/distill/pilot_lora/summary.md`.
- A three-engine benchmark through the app's engine path is paused at 102 of 150 answers (Claude and Plain Qwen complete,
  LoRA 2/50); resume with the command in `docs/LOQA_QWEN_RAG_INTEGRATION.md` §10 when the machine is free.

**LoRA fine-tuning remains experimental and is currently under evaluation.** It is shown for comparison only and is not
presented as better than Claude or as production-ready.

## 11. What is planned next

1. Finish the paused three-engine benchmark and report legal quality separately from format/citation behaviour.
2. Build ~280 verified training examples with full app context; fix the student's JSON format defects; select the
   checkpoint by validation loss; re-evaluate on the same frozen benchmark, judged on legal correctness first.
3. Expand case law beyond Section 138 NI Act.
4. Improve retrieval of definitions sections for questions that name an Act but no section.
