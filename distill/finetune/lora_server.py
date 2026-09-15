"""
Local MLX inference service for Qwen3-1.7B + an EXPERIMENTAL LoRA adapter.

IndianLawGPT's `lora_qwen` answer engine (src/llm_provider.py LoRAQwenProvider) calls this service. It
does no retrieval and no citation work: it receives the exact system prompt and user content the app built
from the shared RAG evidence, and returns the raw model text. Parsing, validation, citation mapping and
citation verification all happen in the app, exactly as for Claude and base Qwen.

The service reports the adapter it loaded (name + checksum) on /health and on every /generate response;
the app refuses responses from a service serving a different adapter (or none).

Why a small service instead of `mlx_lm server`: that server does not expose which adapter is loaded, so a
misconfigured start would silently answer with the base model — unacceptable for a model comparison.

Endpoints:
    GET  /health    -> {"status", "model", "adapter_name", "adapter_path", "adapter_sha256", "max_tokens"}
    POST /generate  {"system": str, "user": str, "max_tokens": int?}
                    -> {"text", "finish_reason", "prompt_tokens", "output_tokens", "seconds", "model", "adapter_name", "adapter_sha256"}

Start (from the repository root, with the fine-tune venv):
    distill/finetune/.venv/bin/python distill/finetune/lora_server.py \
        --adapter artifacts/lora_demo_qwen3_1.7b --adapter-name lora_demo_qwen3_1.7b --port 8095
"""
import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from mlx_lm import load, stream_generate

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = ROOT / "distill" / "finetune" / "models" / "Qwen3-1.7B-4bit"
DEFAULT_ADAPTER = ROOT / "artifacts" / "lora_demo_qwen3_1.7b"


def adapter_checksum(adapter_path):
    weights = Path(adapter_path) / "adapters.safetensors"
    if not weights.exists():
        return None
    digest = hashlib.sha256()
    with weights.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()[:16]


class Service:
    def __init__(self, model_path, adapter_path, adapter_name, max_tokens):
        self.model_path = str(model_path)
        self.adapter_path = str(adapter_path) if adapter_path else None
        self.adapter_name = adapter_name if adapter_path else "none"
        self.adapter_sha256 = adapter_checksum(adapter_path) if adapter_path else None
        self.max_tokens = max_tokens
        # MLX streams are thread-local: the model is loaded and every generation runs on this one worker thread,
        # so HTTP handler threads (e.g. /health) never touch MLX and requests are served one at a time.
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mlx")
        self.model, self.tokenizer = self.worker.submit(load, self.model_path, adapter_path=self.adapter_path).result()

    def identity(self):
        return {"model": Path(self.model_path).name, "adapter_name": self.adapter_name, "adapter_path": self.adapter_path,
                "adapter_sha256": self.adapter_sha256}

    def generate(self, system, user, max_tokens):
        return self.worker.submit(self._generate, system, user, max_tokens).result()

    def _generate(self, system, user, max_tokens):
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        prompt = self.tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=False, enable_thinking=False)
        text, last = [], None
        started = time.perf_counter()
        for response in stream_generate(self.model, self.tokenizer, prompt, max_tokens=max_tokens):
            text.append(response.text)
            last = response
        return {
            "text": "".join(text), "finish_reason": getattr(last, "finish_reason", None),
            "prompt_tokens": getattr(last, "prompt_tokens", None), "output_tokens": getattr(last, "generation_tokens", None),
            "seconds": round(time.perf_counter() - started, 3), **self.identity(),
        }


def make_handler(service):
    class Handler(BaseHTTPRequestHandler):
        server_version = "IndianLawGPT-LoRA-MLX/1.0"

        def _send(self, status, payload):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                self._send(200, {"status": "ok", "max_tokens": service.max_tokens, "experimental": True, **service.identity()})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/generate":
                self._send(404, {"error": "not found"})
                return
            try:
                request = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                system, user = request["system"], request["user"]
                max_tokens = int(request.get("max_tokens") or service.max_tokens)
            except (ValueError, KeyError, TypeError) as error:
                self._send(400, {"error": f"invalid request: {error}"})
                return
            try:
                self._send(200, service.generate(system, user, max_tokens))
            except Exception as error:  # report generation failures as such; the app marks the answer FAILED
                self._send(500, {"error": f"generation failed: {error}"})

        def log_message(self, fmt, *args):
            print(f"[lora-service] {self.address_string()} {fmt % args}", flush=True)

    return Handler


def main():
    parser = argparse.ArgumentParser(description="Local MLX service for Qwen3-1.7B + LoRA adapter (experimental).")
    parser.add_argument("--model", default=str(DEFAULT_MODEL))
    parser.add_argument("--adapter", default=str(DEFAULT_ADAPTER), help="Adapter directory, or 'none' for the base model.")
    parser.add_argument("--adapter-name", default=None, help="Name reported to the app (default: adapter directory name).")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8095)
    parser.add_argument("--max-tokens", type=int, default=1600)
    args = parser.parse_args()

    adapter = None if args.adapter == "none" else args.adapter
    name = args.adapter_name or (Path(adapter).name if adapter else "none")
    print(f"[lora-service] loading {args.model} with adapter {adapter or 'none'} ({name})", flush=True)
    service = Service(args.model, adapter, name, args.max_tokens)
    print(f"[lora-service] ready on http://{args.host}:{args.port} — adapter {service.adapter_name} sha256 {service.adapter_sha256}", flush=True)
    # Threaded so /health answers while a generation is running; generation itself stays serialised by the lock.
    ThreadingHTTPServer((args.host, args.port), make_handler(service)).serve_forever()


if __name__ == "__main__":
    main()
