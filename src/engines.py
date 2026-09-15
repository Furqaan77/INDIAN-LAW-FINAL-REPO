"""
Answer engines: a controlled comparison of answer models on IDENTICAL IndianLawGPT RAG evidence.

    claude     Claude API      — Anthropic Claude + RAG (the teacher / reference)
    lora_qwen  LoRA Qwen + RAG — Qwen3-1.7B + EXPERIMENTAL LoRA adapter, local MLX service
    qwen       Plain Qwen      — base Qwen3-1.7B + RAG, local Ollama (the control)

Every engine runs the same pipeline: hybrid retrieval → reranking → evidence selection → prompt → answer
model → structured-output validation → citation mapping → citation verification (rag_chain). Only the
answer model differs.

Identical evidence: retrieval runs once per (question, top_k) and the selected evidence is frozen under an
evidence_id (a hash of the question, top_k and every selected passage). Later requests for the same
question — by evidence_id, or by question within EVIDENCE_CACHE_TTL_S — reuse the frozen bundle instead
of retrieving again, so engines cannot see different evidence.

No silent fallback: if the selected engine is unavailable the answer fails with that engine's own message.
One retry policy (ENGINE_MAX_RETRIES after a MALFORMED or TRUNCATED output) applies to every engine and is
recorded. Each request is logged to ENGINE_TELEMETRY_PATH.
"""
import json
import os
import threading
import time
from collections import OrderedDict
from typing import Callable, Dict, List, Optional

from config import settings
from llm_provider import OUTPUT_FAILED, OUTPUT_VALID, get_named_provider
from logging_config import get_logger
from rag_chain import DATASET_ANSWER_INSTRUCTION, answer_from_evidence, retrieve_evidence

logger = get_logger("engines")

ENGINE_KEYS = ("claude", "qwen", "lora_qwen")

FORMAT_RETRY_INSTRUCTION = (
    "Your previous reply was not one complete, valid JSON object. Reply again with ONLY a single JSON object "
    'of the form {"citations": [{"doc_id": "...", "evidence_quote": "..."}], "answer": "..."}. '
    "Keep every evidence_quote under 30 words and the answer concise."
)


def engine_spec(key: str) -> Dict:
    """Display and routing metadata for one engine (model names follow the current settings)."""
    if key == "claude":
        return {"key": key, "label": "Claude API", "subtitle": "Claude · RAG", "model": settings.anthropic_model,
                "description": "Claude API with the IndianLawGPT evidence pipeline.",
                "role": "Teacher / reference model", "runtime": "Anthropic API",
                "provider": "Anthropic", "provider_name": "anthropic", "adapter": None, "adapter_label": None,
                "experimental": False, "unavailable_message": "Claude API unavailable."}
    if key == "qwen":
        return {"key": key, "label": "Plain Qwen", "subtitle": f"{settings.lora_base_model} · Base · RAG", "model": settings.ollama_model,
                "description": f"Base {settings.lora_base_model.replace('-', ' ')} using the same IndianLawGPT evidence.",
                "role": "Base local model (control)", "runtime": "Ollama (local)",
                "provider": "Ollama", "provider_name": "ollama", "adapter": None, "adapter_label": None,
                "experimental": False, "unavailable_message": "Plain Qwen unavailable. Check Ollama."}
    if key == "lora_qwen":
        return {"key": key, "label": "LoRA Qwen", "subtitle": f"{settings.lora_base_model} · LoRA · RAG · Experimental",
                "model": settings.lora_base_model,
                "description": "Experimental LoRA Qwen using the same IndianLawGPT evidence.",
                "role": "Experimental fine-tuned student", "runtime": "MLX local service",
                "provider": "MLX (local service)", "provider_name": "lora_mlx",
                "adapter": settings.lora_adapter_name, "adapter_label": settings.lora_adapter_label, "experimental": True,
                "unavailable_message": "LoRA Qwen unavailable. Check the local MLX model service."}
    raise ValueError(f"Unknown engine '{key}'. Supported: {', '.join(ENGINE_KEYS)}")


def _public_spec(spec: Dict) -> Dict:
    return {k: v for k, v in spec.items() if k not in ("provider_name", "unavailable_message")}


class EvidenceCache:
    """Thread-safe, time-limited store of frozen evidence bundles."""

    def __init__(self, max_entries: int = 256):
        self._entries: "OrderedDict[str, Dict]" = OrderedDict()
        self._by_question: Dict[str, str] = {}
        self._lock = threading.Lock()
        self.max_entries = max_entries

    @staticmethod
    def question_key(question: str, top_k: int) -> str:
        return f"{' '.join(question.lower().split())}|{top_k}"

    def _fresh(self, bundle: Dict) -> bool:
        return time.time() - bundle["created_at"] <= settings.evidence_cache_ttl_s

    def get(self, evidence_id: Optional[str]) -> Optional[Dict]:
        with self._lock:
            bundle = self._entries.get(evidence_id or "")
            return bundle if bundle and self._fresh(bundle) else None

    def find(self, question: str, top_k: int) -> Optional[Dict]:
        with self._lock:
            bundle = self._entries.get(self._by_question.get(self.question_key(question, top_k), ""))
            return bundle if bundle and self._fresh(bundle) else None

    def put(self, bundle: Dict) -> None:
        with self._lock:
            self._entries[bundle["evidence_id"]] = bundle
            self._entries.move_to_end(bundle["evidence_id"])
            self._by_question[self.question_key(bundle["question"], bundle["top_k"])] = bundle["evidence_id"]
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)


evidence_cache = EvidenceCache()
_telemetry_lock = threading.Lock()


def _record_telemetry(record: Dict) -> None:
    try:
        path = os.path.abspath(settings.engine_telemetry_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with _telemetry_lock, open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("Could not write engine telemetry")


def frozen_evidence(question: str, top_k: int, evidence_id: Optional[str] = None, on_stage=None) -> Dict:
    """The evidence bundle for this question: reused from the cache when possible, otherwise retrieved once."""
    bundle = evidence_cache.get(evidence_id) or evidence_cache.find(question, top_k)
    if bundle is not None:
        if on_stage:
            on_stage("ranking", "done", {"selected": len(bundle["hits"]), "reused": True})
        return {**bundle, "reused": True}
    bundle = retrieve_evidence(question, top_k=top_k, on_stage=on_stage)
    if not bundle.get("error"):
        evidence_cache.put(bundle)
    return {**bundle, "reused": False}


def generate_with_engine(question: str, engine: str, evidence: Dict, mode: str = "research", on_stage=None,
                         answer_instruction: Optional[str] = "default") -> Dict:
    """Runs one engine on an already-frozen evidence bundle (used by the UI path and the benchmark)."""
    spec = engine_spec(engine)
    instruction = (DATASET_ANSWER_INSTRUCTION if settings.engine_answer_instruction == "dataset" else None) \
        if answer_instruction == "default" else answer_instruction
    attempts: List[Dict] = []
    errors: List[str] = []

    chosen = {"index": -1, "answer_recovered": False, "raw_output_shown": False}

    def generate(system_prompt: str, user_content: str) -> Dict:
        provider = get_named_provider(spec["provider_name"])
        prompt = user_content
        outputs = []
        for attempt in range(settings.engine_max_retries + 1):
            try:
                output = provider.generate_structured_answer(system_prompt, prompt)
            except Exception as error:
                errors.append(str(error))
                attempts.append({"attempt": attempt + 1, "output_status": OUTPUT_FAILED, "error": str(error)})
                raise
            generation = output.get("generation") or {"output_status": OUTPUT_VALID}
            attempts.append({"attempt": attempt + 1, **{k: v for k, v in generation.items() if k != "raw_output"},
                             "raw_output": (generation.get("raw_output") or "")[:6000]})
            outputs.append(output)
            if generation.get("output_status") == OUTPUT_VALID:
                break
            prompt = f"{user_content}\n\n{FORMAT_RETRY_INSTRUCTION}"

        # Use the latest attempt that produced answer text: a retry that loses the answer must not hide an earlier one.
        usable = [i for i, out in enumerate(outputs) if str(out.get("answer") or "").strip()]
        index = usable[-1] if usable else len(outputs) - 1
        selected = outputs[index]
        chosen["index"] = index
        status = (selected.get("generation") or {}).get("output_status", OUTPUT_VALID)
        chosen["answer_recovered"] = bool(usable) and status != OUTPUT_VALID
        if not usable:
            raw = ((selected.get("generation") or {}).get("raw_output") or "").strip()
            if raw:
                # Nothing parseable: show the model's own output, unedited and labelled, rather than no answer at all.
                chosen["raw_output_shown"] = True
                selected = {**selected, "answer": "**The model's reply could not be parsed.** Its raw output is shown "
                                                  "below, unedited.\n\n```text\n" + raw[:4000] + "\n```"}
        return selected

    result = answer_from_evidence(question, evidence, mode=mode, answer_instruction=instruction, on_stage=on_stage,
                                  generate_fn=generate, model_label=spec["subtitle"], unavailable_message=spec["unavailable_message"])
    failed = result.get("error") == "generation"
    final = attempts[chosen["index"]] if attempts and not failed else (attempts[-1] if attempts else {})
    citations = result.get("citations") or []
    timings = result.get("timings") or {}
    result["engine"] = {
        **_public_spec(spec), "rag": True,
        "evidence_id": evidence.get("evidence_id"), "evidence_reused": bool(evidence.get("reused")),
        "retrieved_sources": len(evidence.get("hits") or []),
        "retrieval_s": 0.0 if evidence.get("reused") else round(evidence.get("retrieval_s") or 0.0, 3),
        "generation_s": timings.get("generation_s"), "total_s": timings.get("total_s"),
        "input_tokens": final.get("input_tokens"), "output_tokens": final.get("output_tokens"),
        "citation_count": len(citations), "verified_citations": sum(1 for c in citations if c.get("verified")),
        "unverified_citations": len(result.get("unverified") or []),
        "retry_count": max(0, len(attempts) - 1),
        "used_attempt": (chosen["index"] + 1 if chosen["index"] >= 0 else len(attempts)) if attempts and not failed else None,
        "answer_recovered": chosen["answer_recovered"] and not failed,
        "raw_output_shown": chosen["raw_output_shown"] and not failed,
        "output_status": OUTPUT_FAILED if failed else final.get("output_status", OUTPUT_FAILED),
        "first_output_status": attempts[0]["output_status"] if attempts else OUTPUT_FAILED,
        "error": errors[-1] if failed and errors else None,
        "message": spec["unavailable_message"] if failed else None,
    }
    result["evidence"] = {"evidence_id": evidence.get("evidence_id"), "reused": bool(evidence.get("reused")),
                          "doc_ids": [h["doc_id"] for h in evidence.get("hits") or []]}
    result["engine_attempts"] = attempts
    _record_telemetry({
        "at": time.time(), "question": question, "mode": mode,
        **{k: result["engine"][k] for k in ("key", "model", "provider", "adapter", "evidence_id", "evidence_reused", "retrieved_sources",
                                            "retrieval_s", "generation_s", "total_s", "input_tokens", "output_tokens", "citation_count",
                                            "verified_citations", "unverified_citations", "retry_count", "output_status",
                                            "first_output_status", "error")},
    })
    return result


def run_engine(question: str, engine: str, top_k: int = 5, mode: str = "research", evidence_id: Optional[str] = None,
               on_stage: Optional[Callable] = None) -> Dict:
    """UI entry point: freeze (or reuse) the evidence for this question, then answer with the selected engine only."""
    spec = engine_spec(engine)
    evidence = frozen_evidence(question, top_k, evidence_id=evidence_id, on_stage=on_stage)
    if evidence.get("error"):
        return {
            "answer_markdown": "The search service is currently unavailable. Please try again shortly.", "citations": [],
            "retrieved_documents": [], "verified": [], "unverified": [], "unmatched_citations": 0,
            "accuracy_note": "Retrieval failed", "mode": mode, "error": "retrieval",
            "engine": {**_public_spec(spec), "rag": True, "output_status": OUTPUT_FAILED, "retry_count": 0,
                       "message": "Retrieval failed before any model was called."},
        }
    return generate_with_engine(question, engine, evidence, mode=mode, on_stage=on_stage)


def engine_status() -> List[Dict]:
    """Availability of each engine, checked without generating (no API spend)."""
    import urllib.request

    statuses = []
    for key in ENGINE_KEYS:
        spec = _public_spec(engine_spec(key))
        available, detail = False, ""
        try:
            if key == "claude":
                available = bool(settings.anthropic_api_key)
                detail = "API key configured" if available else "ANTHROPIC_API_KEY is not set"
            elif key == "qwen":
                with urllib.request.urlopen(f"{settings.ollama_base_url.rstrip('/')}/api/tags", timeout=3) as response:
                    names = {m.get("name") for m in json.load(response).get("models", [])}
                available = settings.ollama_model in names
                detail = "Ollama running, model present" if available else f"Ollama running, but {settings.ollama_model} is not pulled"
            else:
                health = get_named_provider("lora_mlx").health()
                available = health.get("adapter_name") == settings.lora_adapter_name
                detail = (f"adapter {health.get('adapter_name')} (sha256 {health.get('adapter_sha256')})" if available
                          else f"service is serving adapter {health.get('adapter_name')!r}, expected {settings.lora_adapter_name!r}")
        except Exception as error:
            detail = engine_spec(key)["unavailable_message"] + f" ({error})"
        statuses.append({**spec, "available": available, "detail": detail})
    return statuses

