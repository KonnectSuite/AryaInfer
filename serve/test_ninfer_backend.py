"""serve/test_ninfer_backend.py - the Ninfer backend without a GPU: its registry entry, and the process/proxy
primitive against a fake Ninfer server on a loopback port.

    python -m unittest serve.test_ninfer_backend -v
"""
from __future__ import annotations

import json
import socket
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from serve import models
from serve.server import NinferBackend


class _FakeNinfer(BaseHTTPRequestHandler):
    def log_message(self, *a) -> None:   # the test's own server says nothing
        pass

    def do_GET(self) -> None:
        if self.path != "/v1/models":
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps({"data": [{"id": "m"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        n = int(self.headers.get("Content-Length") or 0)
        req = json.loads(self.rfile.read(n) or b"{}")
        body = json.dumps({"model": req.get("model"), "choices": [{"message": {"content": "ok"}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class NinferBackendTest(unittest.TestCase):
    def test_registry_describes_a_ninfer_config(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            tok = d / "tok"
            tok.mkdir()
            (tok / "vocab.json").write_text("{}")
            cfg = {
                "backend": "ninfer", "exe": sys.executable, "args": [], "tokenizer": str(tok),
                "model_name": "m-ninfer", "display_name": "M NInfer", "aliases": ["mx"],
                "ninfer": {"command": ["ninfer-serve", "x.ninfer", "--max-context", "102400", "--vision"]},
            }
            p = d / "strata-m.json"
            p.write_text(json.dumps(cfg))
            e = models.describe(p)
            self.assertIsNotNone(e)
            self.assertEqual(e["backend"], "ninfer")
            self.assertEqual(e["context"], 102400)
            self.assertTrue(e["multimodal"])
            self.assertTrue(e["mtp"])
            self.assertEqual(e["id"], "m-ninfer")
            self.assertEqual(e["display_name"], "M NInfer")
            self.assertEqual(e["status"], "available")

    def test_start_post_stop(self) -> None:
        port = _free_port()
        srv = ThreadingHTTPServer(("127.0.0.1", port), _FakeNinfer)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            b = NinferBackend({"host": "127.0.0.1", "port": port, "model_id": "m", "ready_s": 15,
                               "command": [sys.executable, "-c", "import time; time.sleep(30)"], "shutdown_wsl": False})
            b.start()
            self.assertIsNotNone(b.proc)
            self.assertIsNone(b.proc.poll())
            with b.post("/v1/chat/completions", {"model": "x", "stream": False}) as r:
                reply = json.loads(r.read())
            self.assertEqual(reply["choices"][0]["message"]["content"], "ok")
            b.stop()
            self.assertIsNone(b.proc)
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main()
