"""serve/comfy_fake_server.py - a ComfyUI-shaped instance for serve/test_comfyui.py (no GPU, no network beyond localhost).

    python serve/comfy_fake_server.py --port 0      prints the port, then answers until Ctrl+C

It answers what the client uses: /system_stats, /object_info (the node classes the shipped graphs need, with the loader
enums), POST /prompt, GET /queue, GET /history/<id>, GET /view, POST /upload/image, POST /interrupt and POST /queue.

`httpd.mode` decides how a job ends:

    "ok"        the history entry carries an output image (the good case)
    "error"     the workflow fails (status_str error with messages)
    "no-output" it reports completed without an image
    "slow"      the history entry appears only after `httpd.delay` seconds

`httpd.missing_node` removes one class from /object_info and `httpd.missing_model` one file from its enum, so Check
can be tested against a ComfyUI that is out of date.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

# a real 1x1 PNG: the download path sniffs the bytes, so a placeholder will not do
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

MODELS = {
    "unet_name": ["qwen_image_2.1_turbo_int8_convrot.safetensors"],
    "clip_name": ["qwen3vl_8b_w4a8.safetensors"],
    "vae_name": ["qwen_image_2.1_vae_bf16.safetensors"],
    "image": ["example.png"],
}

CLASSES = [
    "UNETLoader", "CLIPLoader", "VAELoader", "QwenImage21Cache", "TextEncodeQwenImage21", "CFGGuider", "RandomNoise",
    "KSamplerSelect", "ManualSigmas", "SamplerCustomAdvanced", "VAEDecode", "SaveImage", "EmptyLatentImage",
    "LoadImage", "ImageScale", "MaskComposite", "PreviewImage",
]


def object_info(server) -> dict:
    out = {}
    for name in CLASSES:
        if name == getattr(server, "missing_node", None):
            continue
        required = {}
        if name == "UNETLoader":
            required["unet_name"] = [list(MODELS["unet_name"])]
        elif name == "CLIPLoader":
            required["clip_name"] = [list(MODELS["clip_name"])]
            required["type"] = [["qwen_image", "sd3"]]
        elif name == "VAELoader":
            required["vae_name"] = [list(MODELS["vae_name"])]
        elif name == "LoadImage":
            required["image"] = [list(MODELS["image"])]
        missing = getattr(server, "missing_model", None)
        if missing:
            for field in ("unet_name", "clip_name", "vae_name", "image"):
                if field in required:
                    required[field][0] = [m for m in required[field][0] if m != missing]
        out[name] = {"input": {"required": required}, "output": []}
    return out


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *args):
        pass

    def _body(self, status: int, ctype: str, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, value):
        self._body(status, "application/json", json.dumps(value).encode())

    def do_GET(self):
        server = self.server
        path, qs = urlsplit(self.path).path, parse_qs(urlsplit(self.path).query)
        if path == "/system_stats":
            return self._json(200, {"system": {"comfyui_version": "0.0-fake", "python_version": "3.13.0 (fake)"},
                                    "devices": [{"name": "fake-gpu", "vram_free": 8 << 30, "vram_total": 16 << 30}]})
        if path == "/object_info":
            return self._json(200, object_info(server))
        if path == "/queue":
            now = time.time()
            pending = [[0, pid, {}, {}, []] for pid, (_g, at) in server.prompts.items() if now < at + getattr(server, "delay", 0)]
            return self._json(200, {"queue_running": [], "queue_pending": pending})
        if path.startswith("/history/"):
            prompt_id = path[len("/history/"):]
            entry = server.prompts.get(prompt_id)
            if entry is None:
                return self._json(200, {})
            if time.time() < entry[1] + getattr(server, "delay", 0):
                return self._json(200, {})
            return self._json(200, {prompt_id: self._history_entry(prompt_id)})
        if path == "/view":
            name = (qs.get("filename") or [""])[0]
            if not name:
                return self._body(404, "text/plain", b"no name")
            return self._body(200, "image/png", PNG)
        return self._json(404, {"error": "not found"})

    def _history_entry(self, prompt_id: str) -> dict:
        mode = getattr(self.server, "mode", "ok")
        if mode == "error":
            return {"status": {"status_str": "error", "completed": False,
                               "messages": [["execution_error", {"node_type": "KSampler",
                                                                 "exception_message": "it failed on purpose"}]]},
                    "outputs": {}}
        if mode == "no-output":
            return {"status": {"status_str": "success", "completed": True}, "outputs": {}}
        return {"status": {"status_str": "success", "completed": True},
                "outputs": {"13": {"images": [{"filename": f"fake-{prompt_id}.png", "subfolder": "",
                                               "type": "output"}]}}}

    def do_POST(self):
        server = self.server
        path = urlsplit(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        if path == "/prompt":
            try:
                req = json.loads(body or b"{}")
            except ValueError:
                return self._json(400, {"error": "bad JSON"})
            if not isinstance(req, dict) or not isinstance(req.get("prompt"), dict):
                return self._json(400, {"error": "no prompt"})
            if getattr(server, "mode", "ok") == "reject":
                return self._json(400, {"error": {"type": "prompt_outputs_failed_validation"},
                                        "node_errors": {"14": {"errors": ["prompt is wrong"]}}})
            prompt_id = f"p{len(server.prompts) + 1}-{int(time.time() * 1000) % 100000}"
            server.prompts[prompt_id] = (req["prompt"], time.time())
            return self._json(200, {"prompt_id": prompt_id, "number": 1, "node_errors": {}})
        if path == "/queue":
            try:
                req = json.loads(body or b"{}")
            except ValueError:
                return self._json(400, {"error": "bad JSON"})
            server.deleted.extend(req.get("delete") or [])
            return self._json(200, {})
        if path == "/upload/image":
            text = body.decode("latin-1", "replace")
            match = re.search(r'filename="([^"]*)"', text)
            name = match.group(1) if match else ""
            index = len(server.uploads) + 1
            stored = f"upload-{index}" + (("." + name.rsplit(".", 1)[-1]) if "." in name else ".png")
            server.uploads.append({"name": name, "stored": stored, "bytes": len(body)})
            return self._json(200, {"name": stored, "subfolder": "", "type": "input"})
        if path == "/interrupt":
            server.interrupts += 1
            return self._json(200, {})
        return self._json(404, {"error": "not found"})


def comfy_server(mode: str = "ok", delay: float = 0.0):
    """A fake ComfyUI on a free port, already answering."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.prompts: dict[str, tuple[dict, float]] = {}
    httpd.uploads: list[dict] = []
    httpd.deleted: list[str] = []
    httpd.interrupts = 0
    httpd.mode, httpd.delay = mode, delay
    httpd.missing_node = None
    httpd.missing_model = None
    threading.Thread(target=httpd.serve_forever, daemon=True, name="comfy-fake").start()
    return httpd


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="a fake ComfyUI for serve/test_comfyui.py")
    parser.add_argument("--port", type=int, default=8188)
    args = parser.parse_args()
    if args.port == 0:
        httpd = comfy_server()
        print(f"listening on http://127.0.0.1:{httpd.server_address[1]}", flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        httpd.shutdown()
    else:
        httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
        httpd.prompts, httpd.uploads, httpd.deleted, httpd.interrupts = {}, [], [], 0
        httpd.mode, httpd.delay, httpd.missing_node, httpd.missing_model = "ok", 0.0, None, None
        print(f"listening on http://127.0.0.1:{args.port}", flush=True)
        httpd.serve_forever()
