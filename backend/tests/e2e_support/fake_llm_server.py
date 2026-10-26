"""Deterministic OpenAI-compatible /chat/completions server for end-to-end tests.

It lets the *real* OpenAI-compatible adapter run in the backend without any paid API. The 'model' is the extractive
test double from the evaluation module. Usage: python fake_llm_server.py [port]
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.evaluation.runner import OfflineExtractiveLLM
from app.providers.base import LLMMessage

MODEL = OfflineExtractiveLLM()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # keep test output quiet
        pass

    def do_GET(self) -> None:
        self.send_response(200)
        self.end_headers()

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
        if not self.path.endswith("/chat/completions"):
            self.send_response(404)
            self.end_headers()
            return
        user = [m for m in body["messages"] if m["role"] == "user"][-1]["content"]
        result = MODEL.generate_structured(system="", messages=[LLMMessage("user", user)], schema={}, max_tokens=100)
        payload = json.dumps({"choices": [{"message": {"role": "assistant", "content": json.dumps(result)}}]}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9911
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
