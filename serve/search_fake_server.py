"""serve/search_fake_server.py - a SearXNG-shaped instance for serve/test_websearch.py (no network beyond localhost).

    python serve/search_fake_server.py --port 0      prints the port, then answers until Ctrl+C

It answers in the ways a real instance does when something is wrong, chosen per server through `httpd.mode`:

    "json"     results as JSON (the good case); a query starting with "!" answers 302 to the destination
    "no-json"  403 with an HTML page, as an instance without `json` in search.formats does
    "html"     200 with text/html instead of JSON
    "empty"    JSON with no results
    "slow"     waits `httpd.delay` seconds before answering
    "429"      too many requests

And pages for the reader: /page (HTML with a script, a style and a link), /long (about 30 KB of paragraphs),
/plain (text/plain), /image.png (image/png), /moved (302 to /page), /loop (a redirect to itself), /missing (404),
/slow-page (waits).
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

RESULTS = [
    {"title": "Qwen3.8 Flash Next &amp; friends", "url": "https://example.org/qwen",
     "content": "The  model   card,   with entities &amp; spaces.", "engine": "brave", "publishedDate": "2026-10-01"},
    {"title": "A duplicate link", "url": "https://example.org/qwen", "content": "the same url again", "engine": "google"},
    {"title": "Second result", "url": "https://example.com/second", "content": "Another result.", "engine": "google"},
    {"title": "Third", "url": "https://example.net/third", "content": "", "engine": "duckduckgo"},
]
ANSWERS = [{"answer": "Qwen3.8 Flash Next is a mixture-of-experts model."}]
UNRESPONSIVE = [["duckduckgo", "CAPTCHA"], []]

PAGE = b"""<!doctype html><html><head><title>t</title><style>p{color:red}</style>
<script>var x = "<p>not text</p>";</script></head><body>
<h1>Reading a page</h1><p>First paragraph with a <a href="https://example.org/deeper">deeper link</a>.</p>
<p>Second   paragraph.</p><ul><li>one</li><li>two</li></ul>
<noscript>ignored</noscript><pre>code block</pre></body></html>"""

LONG = (b"<!doctype html><html><body>" + b"".join(b"<p>paragraph %d: " % i + b"filler text " * 12 + b"</p>"
                                                 for i in range(40)) + b"</body></html>")


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

    def do_GET(self):
        mode = getattr(self.server, "mode", "json")
        path, qs = urlsplit(self.path).path, parse_qs(urlsplit(self.path).query)
        query = (qs.get("q") or [""])[0]
        if path == "/page":
            return self._body(200, "text/html; charset=utf-8", PAGE)
        if path == "/long":
            return self._body(200, "text/html; charset=utf-8", LONG)
        if path == "/plain":
            return self._body(200, "text/plain; charset=utf-8", b"plain text page\nwith a second line\n")
        if path == "/image.png":
            return self._body(200, "image/png", b"\x89PNG\r\n\x1a\n" + b"0" * 64)
        if path == "/moved":
            self.send_response(302)
            self.send_header("Location", "/page")
            self.end_headers()
            return
        if path == "/loop":
            self.send_response(302)
            self.send_header("Location", "/loop")
            self.end_headers()
            return
        if path == "/missing":
            return self._body(404, "text/html", b"<p>no</p>")
        if path == "/slow-page":
            time.sleep(float(getattr(self.server, "delay", 3)))
            return self._body(200, "text/html", PAGE)
        if path != "/search":
            return self._body(404, "text/html", b"<p>no</p>")
        if mode == "slow":
            time.sleep(float(getattr(self.server, "delay", 3)))
        if mode == "429":
            return self._body(429, "text/html", b"<p>slow down</p>")
        if mode == "no-json":
            return self._body(403, "text/html", b"<p>json is not enabled</p>")
        if mode == "html":
            return self._body(200, "text/html", b"<div>results</div>")
        if query.startswith("!"):
            self.send_response(302)
            self.send_header("Location", "https://example.org/bang")
            self.end_headers()
            return
        body = {"query": query, "results": [] if mode == "empty" else RESULTS,
                "answers": [] if mode == "empty" else ANSWERS, "unresponsive_engines": UNRESPONSIVE}
        self._body(200, "application/json; charset=utf-8", json.dumps(body).encode("utf-8"))


def search_server(port: int = 0, mode: str = "json", delay: float = 3.0) -> ThreadingHTTPServer:
    """A server answering on 127.0.0.1:port (0: any free port), already serving on a thread."""
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.mode, httpd.delay = mode, delay
    threading.Thread(target=httpd.serve_forever, daemon=True, name="fake-searxng").start()
    return httpd


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--mode", default="json")
    a = ap.parse_args()
    server = search_server(a.port, a.mode)
    print(f"listening on http://127.0.0.1:{server.server_address[1]}/search", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        sys.exit(0)
