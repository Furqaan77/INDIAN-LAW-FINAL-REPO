"""
LLM provider abstraction for answer generation.

Swap providers via LLM_PROVIDER in .env. Only "anthropic" is implemented
today; add a new class + branch in get_llm_provider() to support another
provider without touching rag_chain.py, which only depends on the
LLMProvider interface below.

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


def _salvage_partial_json(text: str) -> Dict[str, Any]:
    """A truncated or malformed response breaks json.loads for the whole object; recover the
    answer and each individually parseable citation instead of dropping all of them."""
    answer_match = _ANSWER_FIELD_PATTERN.search(text)
    answer = answer_match.group(1) if answer_match else ""

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


class LLMProvider(abc.ABC):
    @abc.abstractmethod
    def generate_structured_answer(self, system_prompt: str, user_content: str) -> Dict[str, Any]:
        """Returns {"answer": str, "citations": [{"doc_id", "evidence_quote"}, ...]}."""


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
        if isinstance(parsed, dict) and parsed.get("answer"):
            answer, embedded = _recover_embedded_citations(parsed["answer"])
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
            return {"answer": answer, "citations": sanitized}

        logger.warning(
            "Structured answer missing or empty (parsing_error=%s); falling back to text parsing",
            response.get("parsing_error"),
        )
        raw_text = _message_text(getattr(response.get("raw"), "content", ""))
        fallback = _extract_json_object(raw_text)
        if not fallback:
            return {"answer": raw_text.strip(), "citations": []}
        return {"answer": fallback.get("answer", "") or "", "citations": _sanitize_citations(fallback.get("citations"))}


@lru_cache(maxsize=1)
def get_llm_provider() -> LLMProvider:
    provider = settings.llm_provider.lower()
    if provider == "anthropic":
        logger.info("Using Anthropic LLM provider (model=%s)", settings.anthropic_model)
        return AnthropicProvider()
    raise ValueError(
        f"Unknown LLM_PROVIDER '{provider}'. Supported: 'anthropic'. "
        "Add a new branch in llm_provider.get_llm_provider() to support more."
    )
