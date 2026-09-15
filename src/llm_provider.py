"""
LLM provider abstraction for answer generation.

Swap providers via LLM_PROVIDER in .env: "anthropic" (Claude) or "ollama"
(a local model such as qwen3:1.7b). Add a new class + branch in
get_llm_provider() to support another provider without touching
rag_chain.py, which only depends on the LLMProvider interface below.

Client pattern mirrors the sibling Health Coach AI project:
`langchain_anthropic.ChatAnthropic(model=..., max_tokens=..., timeout=...)`,
picking up ANTHROPIC_API_KEY from the environment itself.

Structured output uses Claude tool calling (`with_structured_output`) rather
than asking for JSON in the prompt: once answers became long Markdown, the
model frequently returned plain Markdown with no JSON wrapper, silently
dropping every citation. The tool's `citations` parameter comes before
`answer`, because when the long answer came first the model sometimes wrote
the citations inside the answer string instead of filling the parameter;
that case is still recovered deterministically below. Text parsing remains
as a last fallback.

Structured output contract: generate_structured_answer() always returns a
dict shaped like:
    {"answer": str, "citations": [{"doc_id": str, "evidence_quote": str}, ...]}
"""
import abc
import html
import json
import re
from functools import lru_cache
from typing import Any, Dict, List, Tuple

from config import settings
from logging_config import get_logger

logger = get_logger("llm_provider")

ANSWER_TOOL_NAME = "submit_legal_answer"

ANSWER_TOOL = {
    "name": ANSWER_TOOL_NAME,
    "description": "Submit the verbatim evidence quotes, then the legal answer that cites them.",
    "input_schema": {
        "type": "object",
        "properties": {
            "citations": {
                "type": "array",
                "description": "The evidence, listed first: one entry per claim, in the order the answer cites them.",
                "items": {
                    "type": "object",
                    "properties": {
                        "doc_id": {
                            "type": "string",
                            "description": "The doc_id from the cited excerpt's '--- doc_id: ... ---' header.",
                        },
                        "evidence_quote": {
                            "type": "string",
                            "description": "The exact verbatim text (at least 5 words) from that excerpt proving the claim.",
                        },
                    },
                    "required": ["doc_id", "evidence_quote"],
                },
            },
            "answer": {
                "type": "string",
                "description": "The Markdown answer, with inline [n] markers referring to entries in citations. No citation list inside it.",
            },
        },
        "required": ["citations", "answer"],
    },
}

_JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)
_ANSWER_FIELD_PATTERN = re.compile(r'"answer"\s*:\s*"(.*?)"\s*,\s*"citations"', re.DOTALL)
_CITATION_OBJECT_PATTERN = re.compile(r'\{\s*"(?:doc_id|case_id)"\s*:.*?\}', re.DOTALL)
_EMBEDDED_CITATION = re.compile(
    r"<citation>\s*<doc_id>(.*?)</doc_id>\s*<evidence_quote>(.*?)</evidence_quote>\s*</citation>", re.DOTALL,
)
_EMBEDDED_BLOCK_STARTS = ("<citations>", '<parameter name="citations">', "</answer>")
_TRAILING_TAGS = re.compile(r"(?:\s*</?(?:answer|parameter)[^>]*>)+\s*$")


def _message_text(content: Any) -> str:
    """ChatAnthropic's .content is either a str or a list of content blocks; keep only the text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return str(content or "")


def _recover_embedded_citations(answer: str) -> Tuple[str, List[Dict[str, str]]]:
    """Splits off a citations block the model wrote inside the answer string, returning the
    clean answer and whatever citations the block contains."""
    starts = [index for index in (answer.find(token) for token in _EMBEDDED_BLOCK_STARTS) if index != -1]
    if not starts:
        return answer, []
    cut = min(starts)
    tail = answer[cut:]

    citations = [
        {"doc_id": html.unescape(doc_id.strip()), "evidence_quote": html.unescape(quote.strip())}
        for doc_id, quote in _EMBEDDED_CITATION.findall(tail)
    ]
    if not citations:
        array = re.search(r"\[.*\]", tail, re.DOTALL)
        if array:
            try:
                decoded = json.loads(array.group(0), strict=False)
                citations = [c for c in decoded if isinstance(c, dict)] if isinstance(decoded, list) else []
            except json.JSONDecodeError:
                citations = []

    return _TRAILING_TAGS.sub("", answer[:cut]).rstrip(), citations


def _coerce_citations(value: Any) -> List[Any]:
    """Tool calls occasionally deliver the citations array as a string instead of a real array:
    plain JSON, JSON wrapped in the model's own `<parameter name="...">` markup, or XML-style
    <citation> elements. Accept all of these; salvage individual objects if the array is cut off."""
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value.strip():
        return []

    xml_citations = _EMBEDDED_CITATION.findall(value)
    if xml_citations:
        return [
            {"doc_id": html.unescape(doc_id.strip()), "evidence_quote": html.unescape(quote.strip())}
            for doc_id, quote in xml_citations
        ]

    start, end = value.find("["), value.rfind("]")
    if start != -1 and end > start:
        try:
            decoded = json.loads(value[start:end + 1], strict=False)
            if isinstance(decoded, list):
                return decoded
        except json.JSONDecodeError:
            pass

    salvaged = []
    for match in _CITATION_OBJECT_PATTERN.finditer(value):
        try:
            obj = json.loads(match.group(0), strict=False)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            salvaged.append(obj)
    return salvaged


def _json_string_field(text: str, field: str) -> str:
    """Reads the string value of `"field": "..."` wherever it appears in malformed JSON — before or after other
    fields, with escaped quotes, or cut off at the end of a truncated reply — and decodes its escapes."""
    match = re.search(rf'"{field}"\s*:\s*"', text or "")
    if not match:
        return ""
    index, chunks = match.end(), []
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            chunks.append(text[index:index + 2])
            index += 2
            continue
        if char == '"':
            break
        chunks.append(char)
        index += 1
    raw = "".join(chunks).rstrip("\\")
    try:
        return json.loads(f'"{raw}"', strict=False)
    except ValueError:
        return raw.replace("\\n", "\n").replace('\\"', '"')


def _salvage_partial_json(text: str) -> Dict[str, Any]:
    """A truncated or malformed response breaks json.loads for the whole object; recover the
    answer and each individually parseable citation instead of dropping all of them."""
    answer = _json_string_field(text, "answer")

    citations = []
    for m in _CITATION_OBJECT_PATTERN.finditer(text):
        try:
            obj = json.loads(m.group(0), strict=False)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            citations.append(obj)

    if citations:
        logger.info("Salvaged %d citation(s) from an otherwise-unparseable LLM response", len(citations))
    return {"answer": answer, "citations": citations}


def _extract_json_object(text: str) -> Dict[str, Any]:
    match = _JSON_OBJECT_PATTERN.search(text or "")
    if not match:
        return {}
    try:
        # strict=False accepts literal newlines inside strings, which Markdown answers contain.
        parsed = json.loads(match.group(0), strict=False)
    except json.JSONDecodeError:
        logger.warning("LLM response contained a JSON-like block that failed to parse whole; attempting to salvage individual fields")
        salvaged = _salvage_partial_json(text or "")
        return salvaged if (salvaged["answer"] or salvaged["citations"]) else {}
    return parsed if isinstance(parsed, dict) else {}


def _sanitize_citations(raw_citations: Any) -> list:
    if not isinstance(raw_citations, list):
        return []
    citations = []
    for c in raw_citations:
        if not isinstance(c, dict):
            continue
        doc_id = c.get("doc_id") or c.get("case_id")  # tolerate either key from the model
        quote = c.get("evidence_quote")
        if not doc_id or not isinstance(quote, str) or len(quote.split()) < 3:
            continue
        citations.append({"doc_id": str(doc_id), "evidence_quote": quote})
    return citations


OUTPUT_VALID, OUTPUT_MALFORMED, OUTPUT_TRUNCATED, OUTPUT_FAILED = "VALID", "MALFORMED", "TRUNCATED", "FAILED"


def validate_structured_output(text: str) -> str:
    """Strict check of a model's raw output against the answer contract: the whole object must parse as
    JSON with a citations list and a non-empty answer string. The salvage helpers above may still recover
    parts of an invalid output for display, but such an output is never reported as VALID."""
    content = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end <= start:
        return OUTPUT_MALFORMED
    try:
        obj = json.loads(content[start:end + 1])
    except ValueError:
        return OUTPUT_MALFORMED
    if not isinstance(obj, dict) or not isinstance(obj.get("citations"), list) or not str(obj.get("answer") or "").strip():
        return OUTPUT_MALFORMED
    return OUTPUT_VALID


_TRAILING_TOOL_MARKUP = re.compile(r"(?:\s*</(?:answer|parameter|invoke|antml:invoke|function_calls)>)+\s*$")


def _strip_tool_markup(answer: str) -> str:
    """Removes tool-call closing tags (</answer>, </parameter>, </invoke>) the model sometimes leaves at the end
    of the answer argument when its tool call is malformed."""
    return _TRAILING_TOOL_MARKUP.sub("", answer) if isinstance(answer, str) else answer


_PACKED_ANSWER = re.compile(r'<parameter name="answer">(.*?)(?:</parameter>|</answer>|</invoke>|$)', re.DOTALL)


def _unpack_tool_arguments(parsed: Any) -> Dict[str, Any]:
    """Claude occasionally writes the entire submit_legal_answer call into the citations string —
    `<parameter name="citations">[...]` followed by `<parameter name="answer">...` — leaving the real answer
    argument empty. Returns {"answer", "citations"} recovered from that string, or {} if it isn't that shape."""
    if not isinstance(parsed, dict) or str(parsed.get("answer") or "").strip():
        return {}
    value = parsed.get("citations")
    if not isinstance(value, str):
        return {}
    match = _PACKED_ANSWER.search(value)
    if not match or not match.group(1).strip():
        return {}
    answer, embedded = _recover_embedded_citations(html.unescape(match.group(1)).strip())
    citations = _sanitize_citations(_coerce_citations(value[:match.start()]) or embedded)
    return {"answer": answer, "citations": citations}


def _parse_json_answer(content: str) -> Dict[str, Any]:
    parsed = _extract_json_object(content)
    if not parsed:
        return {"answer": content.strip(), "citations": []}
    answer, embedded = _recover_embedded_citations(str(parsed.get("answer") or ""))
    citations = _coerce_citations(parsed.get("citations")) or embedded
    return {"answer": answer, "citations": _sanitize_citations(citations)}


class LLMProvider(abc.ABC):
    @abc.abstractmethod
    def generate_structured_answer(self, system_prompt: str, user_content: str) -> Dict[str, Any]:
        """Returns {"answer": str, "citations": [{"doc_id", "evidence_quote"}, ...], "generation": {...}}.
        `generation` (output_status, raw_output, token counts, finish_reason) is telemetry for the answer
        engines; callers that only read answer and citations are unaffected."""


class AnthropicProvider(LLMProvider):
    def __init__(self, model: str = None, max_tokens: int = None, timeout: int = 90):
        self.model = model or settings.anthropic_model
        self.max_tokens = max_tokens or settings.anthropic_max_tokens
        self.timeout = timeout
        self._structured = None

    @property
    def structured_llm(self):
        if self._structured is None:
            settings.require_anthropic_key()
            from langchain_anthropic import ChatAnthropic
            # Not all Claude models accept `temperature` (some reject it with a 400), so it's omitted.
            llm = ChatAnthropic(model=self.model, max_tokens=self.max_tokens, timeout=self.timeout)
            self._structured = llm.with_structured_output(ANSWER_TOOL, include_raw=True)
        return self._structured

    def generate_structured_answer(self, system_prompt: str, user_content: str) -> Dict[str, Any]:
        from langchain_core.messages import HumanMessage, SystemMessage

        try:
            response = self.structured_llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_content)])
        except Exception:
            logger.exception("Anthropic API call failed (model=%s)", self.model)
            raise

        parsed = response.get("parsed")
        raw_message = response.get("raw")
        usage = getattr(raw_message, "usage_metadata", None) or {}
        stop_reason = (getattr(raw_message, "response_metadata", None) or {}).get("stop_reason")
        generation = {
            "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"), "finish_reason": stop_reason,
        }
        if isinstance(parsed, dict) and parsed.get("answer"):
            answer, embedded = _recover_embedded_citations(_strip_tool_markup(parsed["answer"]))
            citations = _coerce_citations(parsed.get("citations")) or embedded
            if embedded and citations is embedded:
                logger.info("Recovered %d citation(s) the model wrote inside the answer text", len(embedded))
            sanitized = _sanitize_citations(citations)
            if not sanitized:
                raw_value = parsed.get("citations")
                logger.warning(
                    "Answer returned without usable citations (citations type=%s, preview=%r)",
                    type(raw_value).__name__, repr(raw_value)[:200],
                )
            generation.update({
                "output_status": OUTPUT_TRUNCATED if stop_reason == "max_tokens"
                else OUTPUT_VALID if isinstance(parsed.get("citations"), list) else OUTPUT_MALFORMED,
                "raw_output": json.dumps({"citations": parsed.get("citations"), "answer": parsed.get("answer")}, ensure_ascii=False, default=str),
            })
            return {"answer": answer, "citations": sanitized, "generation": generation}

        malformed = OUTPUT_TRUNCATED if stop_reason == "max_tokens" else OUTPUT_MALFORMED
        packed = _unpack_tool_arguments(parsed)
        if packed:
            # The model wrote the whole tool call into the citations string; recover it, but never as VALID.
            logger.warning("Recovered answer and %d citation(s) packed inside the citations string", len(packed["citations"]))
            generation.update({"output_status": malformed, "raw_output": json.dumps(parsed, ensure_ascii=False, default=str)})
            return {**packed, "generation": generation}

        logger.warning(
            "Structured answer missing or empty (parsing_error=%s, parsed fields=%s, tool_calls=%d, content blocks=%s, stop=%s); "
            "falling back to text parsing",
            response.get("parsing_error"),
            {k: type(v).__name__ for k, v in parsed.items()} if isinstance(parsed, dict) else type(parsed).__name__,
            len(getattr(raw_message, "tool_calls", None) or []),
            [b.get("type") for b in raw_message.content if isinstance(b, dict)] if isinstance(getattr(raw_message, "content", None), list) else type(getattr(raw_message, "content", None)).__name__,
            stop_reason,
        )
        raw_text = _message_text(getattr(response.get("raw"), "content", ""))
        generation.update({"output_status": malformed, "raw_output": raw_text})
        fallback = _extract_json_object(raw_text)
        if not fallback:
            return {"answer": raw_text.strip(), "citations": [], "generation": generation}
        return {"answer": fallback.get("answer", "") or "", "citations": _sanitize_citations(fallback.get("citations")), "generation": generation}


class OllamaProvider(LLMProvider):
    """A local model served by Ollama's HTTP API, called with the standard library (no extra
    dependency). Thinking is disabled for latency, and the same schema as the Claude tool is
    passed as Ollama's `format`, so the output contract matches AnthropicProvider exactly."""

    def __init__(self):
        self.model = settings.ollama_model
        self.url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
        self.last_metrics: Dict[str, Any] = {}

    def generate_structured_answer(self, system_prompt: str, user_content: str) -> Dict[str, Any]:
        import urllib.error
        import urllib.request

        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "stream": False,
            "think": False,
            "format": ANSWER_TOOL["input_schema"],
            "keep_alive": settings.ollama_keep_alive,
            "options": {
                "temperature": 0,
                "num_ctx": settings.ollama_num_ctx,
                "num_predict": settings.ollama_max_tokens,
            },
        }
        request = urllib.request.Request(
            self.url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=settings.ollama_timeout) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:300]
            logger.error("Ollama returned HTTP %s (model=%s): %s", error.code, self.model, detail)
            raise RuntimeError(f"Ollama returned HTTP {error.code} for model '{self.model}': {detail}") from error
        except (urllib.error.URLError, TimeoutError) as error:
            logger.error("Could not reach Ollama at %s: %s", self.url, error)
            raise RuntimeError(f"Could not reach Ollama at {settings.ollama_base_url} — is `ollama serve` running?") from error

        self.last_metrics = {
            "load_s": payload.get("load_duration", 0) / 1e9,
            "prompt_tokens": payload.get("prompt_eval_count"),
            "prompt_eval_s": payload.get("prompt_eval_duration", 0) / 1e9,
            "output_tokens": payload.get("eval_count"),
            "eval_s": payload.get("eval_duration", 0) / 1e9,
            "done_reason": payload.get("done_reason"),
        }
        logger.info(
            "Ollama %s: prompt %s tok in %.2fs, output %s tok in %.2fs, load %.2fs, done=%s",
            self.model, self.last_metrics["prompt_tokens"], self.last_metrics["prompt_eval_s"],
            self.last_metrics["output_tokens"], self.last_metrics["eval_s"], self.last_metrics["load_s"],
            self.last_metrics["done_reason"],
        )
        if payload.get("done_reason") == "length":
            logger.warning("Ollama output hit OLLAMA_MAX_TOKENS=%d and was cut off", settings.ollama_max_tokens)

        content = (payload.get("message") or {}).get("content", "")
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)  # defensive; thinking is disabled
        generation = {
            "output_status": OUTPUT_TRUNCATED if payload.get("done_reason") == "length" else validate_structured_output(content),
            "raw_output": content, "input_tokens": payload.get("prompt_eval_count"), "output_tokens": payload.get("eval_count"),
            "finish_reason": payload.get("done_reason"),
        }
        if not _extract_json_object(content):
            logger.warning("Ollama returned no parseable JSON; treating the output as plain text")
        return {**_parse_json_answer(content), "generation": generation}


class LoRAQwenProvider(LLMProvider):
    """EXPERIMENTAL: Qwen3-1.7B with a LoRA adapter, served by the local MLX service
    (distill/finetune/lora_server.py). The service reports which adapter it loaded, and every response is
    checked against LORA_ADAPTER_NAME — a service serving another adapter, or none, is refused, so this
    engine can never silently answer with the base model."""

    def __init__(self):
        self.url = settings.lora_qwen_url.rstrip("/")
        self.adapter_name = settings.lora_adapter_name

    def _request(self, path: str, body: Dict[str, Any] = None, timeout: int = None) -> Dict[str, Any]:
        import urllib.error
        import urllib.request

        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(f"{self.url}{path}", data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout or settings.lora_timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"LoRA Qwen service returned HTTP {error.code}: {detail}") from error
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            raise RuntimeError(f"Could not reach the LoRA Qwen service at {self.url}: {error}") from error

    def health(self, timeout: int = 3) -> Dict[str, Any]:
        return self._request("/health", timeout=timeout)

    def generate_structured_answer(self, system_prompt: str, user_content: str) -> Dict[str, Any]:
        payload = self._request("/generate", {"system": system_prompt, "user": user_content, "max_tokens": settings.lora_max_tokens})
        if payload.get("adapter_name") != self.adapter_name:
            raise RuntimeError(
                f"LoRA Qwen service is serving adapter {payload.get('adapter_name')!r}, not the configured {self.adapter_name!r}"
            )
        content = re.sub(r"<think>.*?</think>", "", payload.get("text") or "", flags=re.DOTALL).strip()
        generation = {
            "output_status": OUTPUT_TRUNCATED if payload.get("finish_reason") == "length" else validate_structured_output(content),
            "raw_output": content, "input_tokens": payload.get("prompt_tokens"), "output_tokens": payload.get("output_tokens"),
            "finish_reason": payload.get("finish_reason"), "service_seconds": payload.get("seconds"),
            "adapter_name": payload.get("adapter_name"), "adapter_sha256": payload.get("adapter_sha256"),
        }
        logger.info("LoRA Qwen (%s): %s output tokens, status %s", self.adapter_name, payload.get("output_tokens"), generation["output_status"])
        return {**_parse_json_answer(content), "generation": generation}


@lru_cache(maxsize=1)
def get_llm_provider() -> LLMProvider:
    provider = settings.llm_provider.lower()
    if provider == "anthropic":
        logger.info("Using Anthropic LLM provider (model=%s)", settings.anthropic_model)
        return AnthropicProvider()
    if provider == "ollama":
        logger.info("Using Ollama LLM provider (model=%s, url=%s)", settings.ollama_model, settings.ollama_base_url)
        return OllamaProvider()
    raise ValueError(
        f"Unknown LLM_PROVIDER '{provider}'. Supported: 'anthropic', 'ollama'. "
        "Add a new branch in llm_provider.get_llm_provider() to support more."
    )


@lru_cache(maxsize=None)
def get_named_provider(name: str) -> LLMProvider:
    """A provider chosen per request by the answer engines (src/engines.py), independent of LLM_PROVIDER."""
    if name == "anthropic":
        return AnthropicProvider()
    if name == "ollama":
        return OllamaProvider()
    if name == "lora_mlx":
        return LoRAQwenProvider()
    raise ValueError(f"Unknown provider '{name}'. Supported: 'anthropic', 'ollama', 'lora_mlx'.")
