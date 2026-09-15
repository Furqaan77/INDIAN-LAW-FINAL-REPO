"""
Shared plumbing for the teacher-dataset (distillation) pipeline.

This pipeline sits beside the IndianLawGPT app and only imports it: retrieval, reranking, Claude
generation, citation mapping and citation verification all come from src/ unchanged.
"""
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
DATA_DIR = ROOT / "data" / "distill"

# Teacher answers must always come from Claude, whatever the app's .env selects.
os.environ["LLM_PROVIDER"] = "anthropic"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config import settings  # noqa: E402
from logging_config import get_logger  # noqa: E402

SEED = 42


def run_dir(name: str) -> Path:
    path = DATA_DIR / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_jsonl(path: Path) -> List[Dict]:
    """Reads a JSONL file, skipping a truncated final line left by an interrupted write."""
    if not path.exists():
        return []
    records = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def latest_by_id(records: Iterable[Dict]) -> Dict[str, Dict]:
    """Append-only files can hold several attempts for one id; the last one wins."""
    latest: Dict[str, Dict] = {}
    for record in records:
        latest[record["id"]] = record
    return latest


def append_jsonl(path: Path, record: Dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def write_jsonl(path: Path, records: Iterable[Dict]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    tmp.replace(path)


def log_failure(run: Path, stage: str, reason: str, **details) -> None:
    append_jsonl(run / "failures.jsonl", {"at": now_iso(), "stage": stage, "reason": reason, **details})


def short_hash(*parts: str, length: int = 12) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:length]


_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "the", "and", "for", "under", "what", "which", "that", "with", "this", "from", "does", "are", "was",
    "were", "can", "how", "who", "whether", "any", "act", "section", "law", "indian", "india", "into", "has",
    "have", "his", "her", "their", "its", "not", "been", "will", "would", "should", "shall", "may", "such",
    "about", "when", "where", "there", "they", "them", "than", "then", "also", "only", "other", "same", "each",
}


def question_tokens(text: str) -> frozenset:
    return frozenset(token for token in _TOKEN.findall(text.lower()) if len(token) > 2 and token not in _STOPWORDS)


def normalized_text(text: str) -> str:
    return " ".join(_TOKEN.findall(text.lower()))


def jaccard(a: frozenset, b: frozenset) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


@lru_cache(maxsize=8)
def _structured_claude(tool_json: str, max_tokens: int):
    settings.require_anthropic_key()
    from langchain_anthropic import ChatAnthropic

    llm = ChatAnthropic(model=settings.anthropic_model, max_tokens=max_tokens, timeout=90)
    return llm.with_structured_output(json.loads(tool_json), include_raw=True)


def call_claude_tool(tool: Dict, system: str, user: str, max_tokens: int = 800, attempts: int = 3) -> Dict:
    """One structured Claude call with retries for transient failures (network, rate limits, overload)."""
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = _structured_claude(json.dumps(tool, sort_keys=True), max_tokens)
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            response = llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
            parsed = response.get("parsed")
            if isinstance(parsed, dict) and parsed:
                return parsed
            last_error = ValueError(f"no structured output (parsing_error={response.get('parsing_error')})")
        except Exception as error:
            last_error = error
        if attempt < attempts:
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Claude call failed after {attempts} attempts: {last_error}")
