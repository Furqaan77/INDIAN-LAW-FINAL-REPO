# LoRA Qwen + RAG integration — three answer engines on identical evidence

IndianLawGPT can answer a research question with one of three **answer engines**. All three use the same
retrieval, the same selected evidence, the same prompt, the same structured-output validation and the same
citation mapping and verification. **Only the answer model changes.**

| Button | Engine key | Answer model | Runtime | Header shown in the UI |
|---|---|---|---|---|
| Claude API | `claude` | `ANTHROPIC_MODEL` (claude-sonnet-5) | Anthropic API | Claude · RAG |
| LoRA Qwen + RAG | `lora_qwen` | Qwen3-1.7B (4-bit MLX) + LoRA adapter `lora_demo_qwen3_1.7b` | local MLX service | Qwen3-1.7B · LoRA · RAG · Experimental **EXPERIMENTAL** |
| Plain Qwen | `qwen` | Qwen3-1.7B base (`qwen3:1.7b`) | local Ollama | Qwen3-1.7B · Base · RAG |

The LoRA adapter is labelled **"Experimental LoRA Pilot — 30 examples"**. It is a research pilot, not a
production model: in its benchmark it scored higher than the base MLX model on the overall score but lower on
legal correctness, and the pilot verdict was **REGRESSION — INVESTIGATE** (see "Pilot results").

---

## 1. Architecture

```
question
  │
  ▼
retrieve_evidence()            src/rag_chain.py   hybrid retrieval (Chroma + FTS5) → RRF rerank → evidence selection
  │  evidence bundle + evidence_id (hash of question, top_k and every selected passage)
  ▼
EvidenceCache (freeze)         src/engines.py     reused by evidence_id, or by question + top_k within EVIDENCE_CACHE_TTL_S
  │
  ▼
engine selection               src/engines.py     claude │ lora_qwen │ qwen   (no fallback)
  │
  ▼
answer_from_evidence()         src/rag_chain.py   identical SYSTEM_PROMPT + excerpts + question (+ dataset instruction)
  │   generate_fn → provider.generate_structured_answer()      src/llm_provider.py
  │   validate → VALID / MALFORMED / TRUNCATED / FAILED, one recorded retry
  ▼
citation mapping               src/rag_chain.py   evidence_quote → retrieved chunk (the model's doc_id is ignored)
  ▼
citation verification          src/citation_verifier.py   [SOURCE: id] checked against SQLite
  ▼
result + engine metadata + telemetry (data/telemetry/engine_requests.jsonl)
```

`answer_question()` is now `retrieve_evidence()` followed by `answer_from_evidence()`. With no engine selected
it behaves exactly as before (configured `LLM_PROVIDER`, no dataset instruction), so the existing research
path, the evaluation suite and the distillation scripts are unchanged. No retrieval, embedding, reranking,
corpus, citation-mapping or verification logic was changed.

## 2. Providers

All providers implement `LLMProvider.generate_structured_answer(system_prompt, user_content)` and return
`{"answer", "citations", "generation"}`. `generation` carries `output_status`, `raw_output`, token counts and
`finish_reason`; older callers that read only `answer` and `citations` are unaffected.

| Provider | Class | Invocation |
|---|---|---|
| Anthropic | `AnthropicProvider` | LangChain `ChatAnthropic.with_structured_output(ANSWER_TOOL, include_raw=True)` — tool-calling structured output |
| Ollama | `OllamaProvider` | `POST {OLLAMA_BASE_URL}/api/chat`, `think: false`, `format` = the `ANSWER_TOOL` JSON schema (constrained decoding) |
| LoRA MLX | `LoRAQwenProvider` | `POST {LORA_QWEN_URL}/generate {system, user, max_tokens}`; the response must name the configured adapter |

`get_named_provider(name)` builds a provider per engine, independent of `LLM_PROVIDER`.

## 3. Adapter

| | |
|---|---|
| Path | `artifacts/lora_demo_qwen3_1.7b/adapters.safetensors` (19 MB; step-60 weights) |
| Base model | `distill/finetune/models/Qwen3-1.7B-4bit` (mlx-community, unchanged, not merged) |
| Training | LoRA rank 8, scale 20, 16 layers, lr 1e-4, 60 steps (2 epochs × 30 VERIFIED examples), seed 42 |
| Label | Experimental LoRA Pilot — 30 examples |

The adapter is loaded at inference time only; the base model is never merged or overwritten.

**Selecting another adapter** (e.g. a future `artifacts/lora/qwen3_1.7b_pilot_280/`):

```bash
# service
distill/finetune/.venv/bin/python distill/finetune/lora_server.py \
    --adapter artifacts/lora/qwen3_1.7b_pilot_280 --adapter-name qwen3_1.7b_pilot_280 --port 8095
# app (.env)
LORA_ADAPTER_NAME=qwen3_1.7b_pilot_280
LORA_ADAPTER_LABEL="Experimental LoRA — 280 examples"
```

If the service's adapter name differs from `LORA_ADAPTER_NAME`, the app refuses its answers and reports the
engine unavailable — it can never silently answer with the wrong adapter or the base model.

## 4. MLX serving

`distill/finetune/lora_server.py` is a small standard-library HTTP service that runs in the fine-tune
virtualenv (`mlx-lm 0.31.3`, `MLX 0.32.2`). It does no retrieval and no citation work.

```bash
# from the repository root
distill/finetune/.venv/bin/python distill/finetune/lora_server.py \
    --adapter artifacts/lora_demo_qwen3_1.7b --adapter-name lora_demo_qwen3_1.7b --port 8095
```

| Endpoint | Returns |
|---|---|
| `GET /health` | `status`, `model`, `adapter_name`, `adapter_path`, `adapter_sha256` (first 16 hex), `max_tokens` |
| `POST /generate` | `text`, `finish_reason` (`stop`/`length`), `prompt_tokens`, `output_tokens`, `seconds`, adapter identity |

Generation uses the Qwen3 chat template with `enable_thinking=False` and greedy decoding. MLX compute streams are
thread-local, so the model is loaded and every generation runs on one dedicated worker thread (requests are
served one at a time); the HTTP server is threaded so `/health` still answers while a generation is running. `mlx_lm server` was not used because it does not report
which adapter is loaded and has no way for the app to detect a misconfigured start.

## 5. RAG flow and the identical-evidence guarantee

1. `retrieve_evidence(question, top_k)` runs the unchanged hybrid retrieval and returns the selected hits plus
   `evidence_id = "ev-" + sha256(question, top_k, doc_ids, passage texts)[:16]`.
2. `engines.frozen_evidence()` stores the bundle in a thread-safe, TTL-limited cache.
3. Any later request for the same research — from another engine button, Compare All 3, or `POST /api/answer`
   with `evidence_id` — reuses the frozen bundle; retrieval is not run again.
4. Every result reports `engine.evidence_id`, `engine.evidence_reused` and `evidence.doc_ids`; the UI comparison
   table warns if two answers were produced from different evidence.

The prompt is identical for all engines: the production `SYSTEM_PROMPT`, the excerpts, the question and — with
`ENGINE_ANSWER_INSTRUCTION=dataset` (default) — the distillation answer instruction
(`rag_chain.DATASET_ANSWER_INSTRUCTION`, the text the LoRA student was trained with; `generate_teacher.py` now
imports the same constant, hash `75a80607c37b`, unchanged). Set `ENGINE_ANSWER_INSTRUCTION=none` to send the
plain research prompt to every engine instead.

## 6. Structured output validation

Contract: one JSON object `{"citations": [{"doc_id", "evidence_quote"}], "answer": "..."}`.

| Status | Meaning |
|---|---|
| VALID | the whole object parses, `citations` is a list, `answer` is non-empty |
| MALFORMED | anything else (invalid JSON, missing fields, answer lost) |
| TRUNCATED | generation stopped at the token limit (`length` / `max_tokens`) |
| FAILED | the engine raised (service unreachable, HTTP error, wrong adapter, API error) |

Claude tool-call defects seen in testing, all reported as MALFORMED (never VALID), recovered for display:

- `citations` delivered as a string (sometimes wrapped in `<parameter name="citations">` markup) — parsed by
  `_coerce_citations`;
- tool-call closing tags (`</answer>`, `</parameter>`, `</invoke>`) left at the end of the answer — removed by
  `_strip_tool_markup`;
- the whole call packed into the `citations` string with the `answer` argument empty — recovered by
  `_unpack_tool_arguments`.

When the structured answer is still empty, the provider logs the parsed field types, tool-call count, content
block types and stop reason, so the defect can be diagnosed without logging prompts or keys.

Retry policy (identical for every engine): after MALFORMED or TRUNCATED, retry up to `ENGINE_MAX_RETRIES`
(default 1) with a short format reminder appended to the user content. The first-attempt status, final status
and retry count are recorded. FAILED is not retried. Salvage helpers may still recover text from a malformed
output for display, but such output is never reported as VALID.

**No fallback.** An unavailable engine returns `error: "generation"`, `output_status: FAILED` and its own message:

- "Claude API unavailable."
- "Plain Qwen unavailable. Check Ollama."
- "LoRA Qwen unavailable. Check the local MLX model service."

## 7. Citation verification

Unchanged, and applied to every engine: each `evidence_quote` is normalised and must occur in a retrieved
chunk; that chunk's own `doc_id` becomes the source (the model's claimed `doc_id` is ignored). Markers `[n]`
are renumbered to mapped sources and markers without a matching quote are removed. The mapped ids are then
verified against SQLite by `citation_verifier.verify_citations`. Answers whose quotes are paraphrased (common
for the 1.7B models) therefore end with zero citations rather than unsupported ones. Insufficient evidence is
handled by the system prompt's refusal rules for every engine.

## 8. API

| Endpoint | Purpose |
|---|---|
| `POST /api/research` `{question, mode, engine?, evidence_id?}` | SSE stream (unchanged events). Without `engine`: the previous behaviour |
| `POST /api/answer` `{question, model: claude\|lora_qwen\|qwen, mode?, evidence_id?}` | JSON answer from one engine |
| `GET /api/engines` | each engine's identity and availability (no generation) |

Result additions: `engine` (key, label, subtitle, model, provider, adapter, adapter_label, experimental, rag,
evidence_id, evidence_reused, retrieved_sources, retrieval_s, generation_s, total_s, input/output tokens,
citation_count, verified_citations, unverified_citations, retry_count, output_status, first_output_status,
message) and `evidence` (evidence_id, reused, doc_ids). `models.llm` now names the model that actually answered.

Telemetry: one JSON line per engine request in `ENGINE_TELEMETRY_PATH` (default
`data/telemetry/engine_requests.jsonl`) with the fields above plus question and error (no keys or prompts).

## 9. UI

Files: `components/research/CommandBar.tsx`, `components/research/EngineControls.tsx`,
`components/research/CompareView.tsx`, `pages/ResearchPage.tsx`, `lib/engines.ts`, `lib/researchSessions.ts`.

- **Engine toggles in the question box** (home page and "Research another question"): `Claude API`, `Plain Qwen`,
  `LoRA Qwen` (EXPERIMENTAL tag), plus `All 3`. Multi-select, at least one; the selection is remembered per browser
  and carried in the URL (`?engines=claude,qwen,lora_qwen`; the older `?engine=` still opens).
- **One engine selected:** single answer with the Evidence rail, answer header (model line, EXPERIMENTAL badge and
  adapter label for LoRA, output-status chip).
- **Two or three engines selected:** side-by-side columns, one per engine. `ensureRuns` runs the selected engines one
  after another — the first retrieves and freezes the evidence, the others reuse it by `evidence_id`; engines
  deselected while queued are skipped and failed runs are not retried automatically (each column has *Try again*).
  Each column shows Queued / current step / answer, citation verification, an **Evidence** drawer and Model details.
  A comparison table above the columns (output status, verified/cited, rejected quotations, retries, total time)
  confirms identical evidence.
- The same toggles above the answer add or remove engines for the current question.
- **Model details** (collapsible): engine, model, role, runtime, adapter, status, evidence id, retrieved sources,
  generation time, total time, citations, verified citations, retries, output status (with first-attempt status).
- History stores each engine's answer under the same research id and reopens with those engines; entries saved before
  this change still open.

## 10. Benchmark

```bash
# prerequisites: LoRA service on :8095, Ollama running with qwen3:1.7b, ANTHROPIC_API_KEY in .env
.venv/bin/python distill/finetune/benchmark.py benchmark --models claude,qwen,lora_qwen --run heldout_pilot_v2
.venv/bin/python distill/finetune/benchmark.py report --models claude,qwen,lora_qwen --run heldout_pilot_v2
# smoke test
.venv/bin/python distill/finetune/benchmark.py benchmark --models claude,qwen,lora_qwen --limit 2 --run smoke
```

- Benchmark: the frozen 50-question held-out set `distill/finetune/data/eval_prompts_pilot_v2.jsonl` with its
  stored evidence and prompts (not re-retrieved, not modified). The report counts prompts identical to the frozen prompt.
- Path: `engines.generate_with_engine` — the same validation, retry and citation pipeline as the UI.
- Scoring reused from the pilot: `generate_teacher.quality_checks`, the blind Claude rubric and the pre-registered
  overall score (`pilot_lora_grade`), aggregates (`pilot_lora_report.aggregate`).
- Output: `data/distill/engine_benchmark/<run>/` — `records.jsonl` (resumable), `benchmark_results.json/.csv`, `report.md`, `run_config.json`.
- The report has two separate tables: **LEGAL QUALITY** (overall, fully correct, evidence fully supported,
  hallucinations, correct refusals, wrong refusals) and **FORMAT / CITATION** (accurate citations,
  verified/unverified, quote match, valid/first-attempt valid/malformed/truncated/failed, retries, answer lost,
  latency, length, tokens).
- The run refuses to start if any requested engine is unavailable (no partial silent benchmark).
- Mid-run infrastructure failures are never counted as model results: on an Anthropic credit or authentication
  error the run stops; rerunning the same command resumes and redoes every record that is FAILED or ungraded
  (the report uses the latest record per model and question).

## 11. Pilot results (30-example LoRA, 50 held-out questions, strict scoring)

| Metric | Base Qwen MLX + RAG | LoRA Qwen + RAG | Plain Qwen (Ollama, JSON-constrained) |
|---|---|---|---|
| Overall (0–100) | 28.8 | 39.7 (+10.9, 95% CI [3.3, 18.2]) | 68.2 |
| Fully correct | 15/50 | 6/50 | 23/50 |
| Evidence fully supported | 13/50 | 6/50 | — |
| Accurate citations | 0/50 | 31/50 | 37/50 |
| Hallucinations | 28/50 | 15/50 | — |
| Valid strict JSON | 0/50 | 26/50 | — |
| Median latency | 8.3 s | 16.4 s | — |

The overall gain came from format and citation behaviour; legal correctness fell (22 questions worse, 2 better).
Verdict: **REGRESSION — INVESTIGATE**. Claude + RAG is the teacher and is graded against its own reference
(ceiling, 100). Full report: `data/distill/pilot_lora/summary.md`.

## 12. Limitations

- The LoRA adapter was trained on 30 examples with compact contexts; the app sends full contexts (distribution shift).
- The MLX service has no schema-constrained decoding; Ollama does. Format comparisons between the two Qwen paths
  partly measure the runtime, not only the weights.
- The two Qwen paths use different quantisations (MLX 4-bit vs Ollama Q4_K_M).
- The format retry changes the prompt for the retried attempt (recorded as `retry_count`).
- The evidence cache is in-process memory; an API restart re-retrieves (and re-freezes) evidence.
- Local engines serve one request at a time; Compare All 3 runs engines sequentially.
- Claude's legal-quality scores in benchmarks are against Claude-written references (ceiling, not independent).

## 13. Future training plan

1. Fix the student's format defects without changing legal content: train on the full app context, keep
   `mask_prompt`, add JSON-validity checks to data building, raise `max_tokens` headroom, choose the checkpoint by
   validation loss (step 30 was better than step 60).
2. Scale to ~280 VERIFIED examples balanced by category (including multiple-authorities and insufficient-evidence),
   never using benchmark ids or seed documents.
3. Train a new adapter into `artifacts/lora/qwen3_1.7b_pilot_280/`; serve it with `--adapter-name`; select it with
   `LORA_ADAPTER_NAME` — no app changes needed.
4. Run `benchmark.py` on the same frozen benchmark and judge on **legal quality first**; format/citation gains alone
   are not an improvement.

## 14. Reproduction

```bash
# 1. Ollama (use the desktop app or a normal terminal; a sandboxed shell cannot reach Metal)
ollama pull qwen3:1.7b

# 2. LoRA MLX service
distill/finetune/.venv/bin/python distill/finetune/lora_server.py \
    --adapter artifacts/lora_demo_qwen3_1.7b --adapter-name lora_demo_qwen3_1.7b --port 8095
curl -s localhost:8095/health

# 3. API
cd src && ../.venv/bin/uvicorn api:app --port 8010
curl -s localhost:8010/api/engines

# 4. Frontend
cd frontend && npm run dev          # or: npm run build

# 5. One question, three engines, identical evidence
curl -s -X POST localhost:8010/api/answer -H 'Content-Type: application/json' \
     -d '{"question": "What is the punishment under Section 138 of the Negotiable Instruments Act?", "model": "claude"}'
# pass the returned engine.evidence_id with "model": "lora_qwen" and "model": "qwen"

# 6. Tests
.venv/bin/python distill/diagnostics/test_legal_references.py
.venv/bin/python distill/diagnostics/test_generator_validation.py
.venv/bin/python distill/diagnostics/test_teacher_grading.py
.venv/bin/python src/evaluate_rag.py
```

Environment variables (all optional): `LORA_QWEN_URL`, `LORA_ADAPTER_NAME`, `LORA_ADAPTER_LABEL`,
`LORA_BASE_MODEL`, `LORA_MAX_TOKENS` (1600), `LORA_TIMEOUT` (300), `ENGINE_MAX_RETRIES` (1),
`ENGINE_ANSWER_INSTRUCTION` (`dataset`|`none`), `EVIDENCE_CACHE_TTL_S` (3600), `ENGINE_TELEMETRY_PATH`.

## 15. Git safety

`.gitignore` now excludes `artifacts/`, `distill/finetune/models/`, `distill/finetune/adapters/`, `*.safetensors`,
`*.gguf`, `data/distill/`, `data/telemetry/` and `distill/finetune/eval/`. Model weights, adapters, training
artifacts, datasets and telemetry are not tracked. Never commit `.env`.
