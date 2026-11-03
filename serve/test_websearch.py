"""serve/test_websearch.py - web search through SearXNG and the page reader (serve/websearch.py), against the fake
instance in serve/search_fake_server.py and the mock engine (no GPU, no network beyond localhost).

    python -m unittest serve.test_websearch -v
"""
from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from serve import search_fake_server as fake  # noqa: E402
from serve import websearch as W  # noqa: E402
from serve.frontend import ChatTemplate  # noqa: E402
from serve.mcp import McpHub  # noqa: E402
from serve.server import ByteTokenizer, MockEngine, Service, serve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CTX = 8192


def call_script(name, **params):
    """The model's text for one tool call, as Qwen's template asks for it."""
    body = "".join(f"<parameter={k}>\n{v}\n</parameter>\n" for k, v in params.items())
    return f"</think>\n\nLet me look it up.\n\n<tool_call>\n<function={name}>\n{body}</function>\n</tool_call>"


class ScriptedEngine(MockEngine):
    """A mock engine with one script per call (the last one repeats), remembering each prompt it was given."""

    def __init__(self, tok, scripts, max_context=CTX):
        super().__init__(tok, list(scripts), max_context=max_context)
        self.prompts = []

    def generate(self, ids, max_new, sampling, cancel, embeddings=None):
        self.prompts.append(list(ids))
        yield from super().generate(ids, max_new, sampling, cancel, embeddings)

    def prompt_text(self, i):
        return bytes(t for t in self.prompts[i] if t < 256).decode("utf-8", "replace")


# ------------------------------------------------------------------------------------------------ the settings
class Settings(unittest.TestCase):
    def test_defaults_and_values(self):
        s = W.normalize({})
        self.assertEqual((s["enabled"], s["base_url"], s["auth"], s["max_results"]), (False, "", "none", 8))
        s = W.normalize({"enabled": True, "base_url": "https://search.example.org/", "language": "pt-BR",
                         "safesearch": "1", "time_range": "week", "categories": "general, news",
                         "timeout_s": 5, "max_results": 3})
        self.assertEqual(s["base_url"], "https://search.example.org")     # the trailing slash goes
        self.assertEqual((s["language"], s["safesearch"], s["time_range"]), ("pt-BR", "1", "week"))
        self.assertEqual((s["timeout_s"], s["max_results"]), (5.0, 3))
        self.assertEqual(W.normalize(s), s)                              # a second pass changes nothing

    def test_bad_values_are_refused(self):
        for raw, why in (({"enabled": True}, "needs the SearXNG instance"),
                         ({"enabled": True, "base_url": "ftp://x"}, "must start with http"),
                         ({"enabled": True, "base_url": "http://x/?a=1"}, "base address"),
                         ({"enabled": True, "base_url": "http://x", "timeout_s": 0}, "between 2 and 60"),
                         ({"enabled": True, "base_url": "http://x", "max_results": 99}, "between 1 and 20"),
                         ({"enabled": True, "base_url": "http://x", "auth": "bearer"}, "needs a token"),
                         ({"enabled": True, "base_url": "http://x", "auth": "basic"}, "needs a user name"),
                         ({"enabled": True, "base_url": "http://x", "auth": "header"}, "needs at least one header"),
                         ({"enabled": True, "base_url": "http://x", "safesearch": "3"}, "safe search"),
                         ({"enabled": True, "base_url": "http://x", "time_range": "hour"}, "time range"),
                         ({"enabled": True, "base_url": "http://x", "language": "english"}, "language code"),
                         ({"enabled": "sometimes", "base_url": "http://x"}, "true or false")):
            with self.subTest(raw=raw), self.assertRaises(ValueError) as ctx:
                W.normalize(raw)
            self.assertIn(why, str(ctx.exception))

    def test_secrets_are_masked_and_kept(self):
        s = W.normalize({"enabled": True, "base_url": "http://x", "auth": "basic", "basic_user": "me",
                         "basic_pass": "hunter2", "token": "tok"})
        public = W.public_settings(s)
        self.assertEqual((public["basic_pass"], public["token"]), (W.MASK, W.MASK))
        self.assertNotIn("hunter2", json.dumps(public))
        merged = W.merge_secrets({**public}, s)                      # the page sends the mask back
        self.assertEqual((merged["basic_pass"], merged["token"]), ("hunter2", "tok"))
        merged = W.merge_secrets({**public, "token": "new"}, s)
        self.assertEqual(merged["token"], "new")                     # a typed value replaces it
        self.assertEqual(W.merge_secrets({"headers": {"X-Key": W.MASK}}, {"headers": {"X-Key": "s"}})["headers"],
                         {"X-Key": "s"})

    def test_the_file_is_written_atomically_and_recovered(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / W.FILE
            self.assertEqual(W.read_settings(path), {})              # missing: nothing
            settings = W.normalize({"enabled": True, "base_url": "http://x", "max_results": 4})
            W.write_settings(path, settings)
            self.assertEqual(W.read_settings(path)["max_results"], 4)
            self.assertFalse(list(Path(d).glob("*.tmp")))
            path.write_text("{not json", encoding="utf-8")            # a hand-broken file
            self.assertEqual(W.read_settings(path), {})
            aside = list(Path(d).glob(W.FILE + ".corrupt-*"))
            self.assertEqual(len(aside), 1)
            self.assertEqual(aside[0].read_text(encoding="utf-8"), "{not json")

    def test_the_run_config_block_and_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / W.FILE
            self.assertIsNone(W.settings_for({}, path))              # nothing configured: no tools at all
            self.assertIsNone(W.settings_for({"search": {"base_url": "http://a"}}, path))   # not enabled
            self.assertEqual(W.settings_for({"search": {"enabled": True, "base_url": "http://a",
                                                        "max_results": 2}}, path)["max_results"], 2)
            W.write_settings(path, W.normalize({"enabled": True, "base_url": "http://b", "max_results": 5}))
            s = W.settings_for({"search": {"enabled": True, "base_url": "http://a", "language": "en"}}, path)
            self.assertEqual((s["base_url"], s["max_results"], s["language"]), ("http://b", 5, ""))  # file wins
        with tempfile.TemporaryDirectory() as d:                     # a bad value in the run config stops the start
            with self.assertRaises(ValueError):
                W.settings_for({"search": {"enabled": True, "base_url": "not a url"}}, Path(d) / W.FILE)


class Mapping(unittest.TestCase):
    def test_url_and_headers(self):
        s = W.normalize({"enabled": True, "base_url": "http://h:8080", "language": "en", "safesearch": "2",
                         "categories": "news", "time_range": "day"})
        url = W.build_search_url(s, "qwen 3.8")
        self.assertIn("http://h:8080/search?", url)
        for piece in ("q=qwen+3.8", "format=json", "language=en", "safesearch=2", "categories=news", "time_range=day"):
            self.assertIn(piece, url)
        self.assertEqual(W.auth_headers(s)["Accept"], "application/json")
        self.assertNotIn("Authorization", W.auth_headers(s))
        bearer = W.normalize({"enabled": True, "base_url": "http://h", "auth": "bearer", "token": "t"})
        self.assertEqual(W.auth_headers(bearer)["Authorization"], "Bearer t")
        basic = W.normalize({"enabled": True, "base_url": "http://h", "auth": "basic", "basic_user": "u",
                             "basic_pass": "p"})
        self.assertTrue(W.auth_headers(basic)["Authorization"].startswith("Basic "))
        header = W.normalize({"enabled": True, "base_url": "http://h", "auth": "header",
                              "headers": {"X-Api-Key": "k"}})
        self.assertEqual(W.auth_headers(header)["X-Api-Key"], "k")

    def test_results_are_mapped(self):
        results, answer, diag = W.map_results({"results": [
            {"title": "A &amp; B", "url": "https://a/1", "content": "  some\n text ", "engine": "brave",
             "publishedDate": "2026-01-02"},
            {"title": "dup", "url": "https://a/1", "content": "again", "engine": "google"},
            {"title": "", "url": "https://a/2", "content": "", "engine": "google"},
        ], "answers": [{"answer": "An <b>answer</b>"}],
            "unresponsive_engines": [["duckduckgo", "CAPTCHA"], []]}, 10)
        self.assertEqual([r["url"] for r in results], ["https://a/1", "https://a/2"])
        self.assertEqual(results[0]["title"], "A & B")
        self.assertEqual(results[0]["snippet"], "some text")
        self.assertEqual(results[0]["published"], "2026-01-02")
        self.assertEqual(results[1]["title"], "https://a/2")          # no title: the address
        self.assertEqual(answer, "An <b>answer</b>")                  # entities decode, tags stay (it is text)
        self.assertEqual(diag["engines"], ["brave", "google"])
        self.assertEqual(diag["unresponsive"], [{"engine": "duckduckgo", "reason": "CAPTCHA"}])
        self.assertEqual(W.map_results({}, 5)[0], [])

    def test_the_text_is_capped(self):
        results = [{"title": f"t{i}", "url": f"https://a/{i}", "snippet": "x" * 50, "published": "", "engine": ""}
                   for i in range(5)]
        text, full, cut = W.format_results(results, "answer", 80)
        self.assertTrue(cut)
        self.assertGreater(full, 80)
        self.assertIn("cut:", text)
        self.assertLessEqual(len(text), 80 + 100)
        text, full, cut = W.format_results([], "", 1000)
        self.assertEqual((text, cut), ("No results.", False))


# ------------------------------------------------------------------------------------------------ the client
class Search(unittest.TestCase):
    """One instance per failure mode: the good answer and every way a SearXNG instance fails."""

    @classmethod
    def setUpClass(cls):
        cls.good = fake.search_server()
        cls.base = f"http://127.0.0.1:{cls.good.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.good.shutdown()
        cls.good.server_close()

    def settings(self, **extra):
        return W.normalize({"enabled": True, "base_url": self.base, **extra})

    def test_the_good_answer(self):
        text, full, cut, diag = W.search(self.settings(), "qwen")
        self.assertIn("Instant answer: Qwen3.8 Flash Next is a mixture-of-experts model.", text)
        self.assertIn("1. Qwen3.8 Flash Next & friends", text)
        self.assertIn("   https://example.org/qwen", text)
        self.assertIn("   The model card, with entities & spaces.", text)
        self.assertNotIn("duplicate", text)                       # the same url twice is one result
        self.assertIn("2. Second result", text)
        self.assertEqual(diag["results"], 3)
        self.assertEqual(diag["engines"], ["brave", "duckduckgo", "google"])
        self.assertEqual(diag["first_url"], "https://example.org/qwen")
        self.assertFalse(cut)

    def test_a_query_that_redirects_is_one_result(self):
        text, _, _, diag = W.search(self.settings(), "!qwen")
        self.assertIn("https://example.org/bang", text)
        self.assertEqual(diag["redirect"], "https://example.org/bang")

    def test_no_results(self):
        server = fake.search_server(mode="empty")
        try:
            text, _, _, diag = W.search(W.normalize({"enabled": True,
                                                     "base_url": f"http://127.0.0.1:{server.server_address[1]}"}),
                                        "nothing at all")
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(text, "No results.")
        self.assertEqual(diag["results"], 0)

    def test_an_instance_without_json_names_the_setting(self):
        server = fake.search_server(mode="no-json")
        try:
            with self.assertRaises(W.WebSearchError) as ctx:
                W.search(W.normalize({"enabled": True, "base_url": f"http://127.0.0.1:{server.server_address[1]}"}),
                         "qwen")
        finally:
            server.shutdown()
            server.server_close()
        self.assertIn("search.formats", str(ctx.exception))
        self.assertIn("403", str(ctx.exception))

    def test_an_html_answer_names_the_content_type(self):
        server = fake.search_server(mode="html")
        try:
            with self.assertRaises(W.WebSearchError) as ctx:
                W.search(W.normalize({"enabled": True, "base_url": f"http://127.0.0.1:{server.server_address[1]}"}),
                         "qwen")
        finally:
            server.shutdown()
            server.server_close()
        self.assertIn("text/html", str(ctx.exception))
        self.assertIn("search.formats", str(ctx.exception))

    def test_rate_limiting_says_so(self):
        server = fake.search_server(mode="429")
        try:
            with self.assertRaises(W.WebSearchError) as ctx:
                W.search(W.normalize({"enabled": True, "base_url": f"http://127.0.0.1:{server.server_address[1]}"}),
                         "qwen")
        finally:
            server.shutdown()
            server.server_close()
        self.assertIn("rate limiting", str(ctx.exception))

    def test_an_instance_that_is_not_there(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()                                             # a port nothing listens on
        with self.assertRaises(W.WebSearchError) as ctx:
            W.search(W.normalize({"enabled": True, "base_url": f"http://127.0.0.1:{port}"}), "qwen")
        self.assertTrue("refused" in str(ctx.exception).lower() or "connect" in str(ctx.exception).lower(),
                        str(ctx.exception))

    def test_a_slow_instance_times_out(self):
        server = fake.search_server(mode="slow", delay=3)
        try:
            settings = W.normalize({"enabled": True, "base_url": f"http://127.0.0.1:{server.server_address[1]}",
                                    "timeout_s": 2})
            started = time.monotonic()
            with self.assertRaises(W.WebSearchTimeout) as ctx:
                W.search(settings, "qwen")
            self.assertLess(time.monotonic() - started, 8)
        finally:
            server.shutdown()
            server.server_close()
        self.assertIn("no answer within 2", str(ctx.exception))

    def test_stop_stops_the_search(self):
        server = fake.search_server(mode="slow", delay=5)
        try:
            settings = W.normalize({"enabled": True, "base_url": f"http://127.0.0.1:{server.server_address[1]}"})
            cancel = threading.Event()
            threading.Timer(0.3, cancel.set).start()
            started = time.monotonic()
            with self.assertRaises(W.WebSearchCancelled):
                W.search(settings, "qwen", cancel)
            self.assertLess(time.monotonic() - started, 4)
        finally:
            server.shutdown()
            server.server_close()

    def test_an_empty_query_is_refused(self):
        with self.assertRaises(W.WebSearchError):
            W.search(self.settings(), "   ")


# ------------------------------------------------------------------------------------------------ the page reader
class ReadPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.good = fake.search_server()
        cls.base = f"http://127.0.0.1:{cls.good.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.good.shutdown()
        cls.good.server_close()

    def settings(self, **extra):
        return W.normalize({"enabled": True, "base_url": self.base, "allow_local": True, **extra})

    def test_a_page_becomes_text(self):
        text, full, cut, diag = W.read_page(self.settings(), self.base + "/page")
        self.assertTrue(text.startswith(self.base + "/page"))
        self.assertIn("Reading a page", text)
        self.assertIn("First paragraph with a deeper link (https://example.org/deeper)", text)
        self.assertIn("one", text)
        self.assertNotIn("not text", text)                       # the script is dropped
        self.assertNotIn("color:red", text)                      # so is the style
        self.assertNotIn("ignored", text)                        # and the noscript
        self.assertEqual(diag["status"], 200)

    def test_plain_text_and_its_cap(self):
        text, _, cut, _ = W.read_page(self.settings(max_fetch_chars=600), self.base + "/plain")
        self.assertIn("plain text page", text)
        self.assertFalse(cut)
        text, full, cut, _ = W.read_page(self.settings(max_fetch_chars=520), self.base + "/long")
        self.assertTrue(cut)
        self.assertGreater(full, 520)
        self.assertIn("cut:", text)

    def test_refusals(self):
        with self.assertRaises(W.WebSearchError) as ctx:
            W.read_page(W.normalize({"enabled": True, "base_url": self.base}), self.base + "/page")
        self.assertIn("local or private", str(ctx.exception))     # allow_local off: 127.0.0.1 refused
        for url, why, local in ((self.base + "/image.png", "not a readable page", True),
                                (self.base + "/missing", "404", True),
                                ("http://169.254.169.254/latest/meta-data/", "private", False),
                                ("http://10.0.0.1/", "private", False),
                                ("http://user:pass@example.org/", "user name and password", True),
                                ("file:///C:/Windows/win.ini", "http", True)):
            with self.subTest(url=url), self.assertRaises(W.WebSearchError) as ctx:
                W.read_page(W.normalize({"enabled": True, "base_url": self.base, "allow_local": local}), url)
            self.assertIn(why, str(ctx.exception))

    def test_redirects_are_followed_and_bounded(self):
        text, _, _, diag = W.read_page(self.settings(), self.base + "/moved")
        self.assertIn("Reading a page", text)
        self.assertEqual(diag["url"], self.base + "/page")
        with self.assertRaises(W.WebSearchError) as ctx:
            W.read_page(self.settings(), self.base + "/loop")
        self.assertIn("redirected more than", str(ctx.exception))


# ------------------------------------------------------------------------------------------------ the chat
class ChatLoop(unittest.TestCase):
    """`"strata_search": true` in the chat page's request: the model calls web_search, the server runs it, and the
    plain API (no flag) never sees the tools."""

    @classmethod
    def setUpClass(cls):
        cls.good = fake.search_server()
        cls.base = f"http://127.0.0.1:{cls.good.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.good.shutdown()
        cls.good.server_close()

    def setUp(self):
        self.httpd = None

    def tearDown(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()

    def start(self, *scripts, search=True, mcp=False):
        tok = ByteTokenizer()
        self.engine = ScriptedEngine(tok, list(scripts))
        self.svc = Service(self.engine, tok, ChatTemplate(ROOT / "serve/chat_template.jinja"))
        self.svc.mcp = McpHub({}) if mcp else None
        self.svc.search = W.SearchHub(W.normalize({"enabled": True, "base_url": self.base,
                                                   "allow_local": True})) if search else None
        self.httpd = serve(self.svc, port=0)
        self.base_url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def post(self, body, stream=True):
        body = {"model": "m", "messages": [{"role": "user", "content": "what is qwen 3.8?"}], "stream": stream, **body}
        req = urllib.request.Request(self.base_url + "/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.read().decode()

    @staticmethod
    def chunks(text):
        return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: {")]

    def test_a_search_then_the_answer(self):
        self.start(call_script("web_search", query="qwen 3.8"), "</think>\n\nIt is a mixture of experts.")
        code, text = self.post({"strata_search": True})
        self.assertEqual(code, 200, text)
        self.assertIn('"name": "web_search"', self.engine.prompt_text(0))     # the tool is in the prompt
        second = self.engine.prompt_text(1)
        self.assertIn("<function=web_search>", second)
        self.assertIn("<tool_response>", second)
        self.assertIn("mixture-of-experts model", second)                     # the result reached the model
        cs = self.chunks(text)
        calls = [c["strata_mcp"] for c in cs if "strata_mcp" in c]
        self.assertEqual([c["event"] for c in calls], ["start", "call", "result"])
        self.assertEqual((calls[1]["server"], calls[1]["tool"]), ("web", "web_search"))
        self.assertTrue(calls[2]["ok"])
        self.assertIn("Instant answer", calls[2]["text"])
        content = "".join((c["choices"][0]["delta"].get("content") or "") for c in cs)
        self.assertEqual(content, "Let me look it up.It is a mixture of experts.")

    def test_the_plain_api_gets_no_tools(self):
        self.start(call_script("web_search", query="qwen"), "</think>\n\nnever")
        code, text = self.post({})
        self.assertEqual(code, 200, text)
        self.assertNotIn("web_search", self.engine.prompt_text(0))
        self.assertNotIn("strata_mcp", text)

    def test_a_read_page_call(self):
        self.start(call_script("read_page", url=self.base + "/page"), "</think>\n\nIt says reading a page.")
        code, text = self.post({"strata_search": True})
        self.assertEqual(code, 200, text)
        self.assertIn("Reading a page", self.engine.prompt_text(1))

    def test_a_failing_search_is_an_error_result(self):
        self.start(call_script("web_search", query="qwen"), "</think>\n\nSorry.")
        self.svc.search = W.SearchHub(W.normalize({"enabled": True, "base_url": "http://127.0.0.1:9"}))
        code, text = self.post({"strata_search": True})
        self.assertEqual(code, 200, text)
        calls = [c["strata_mcp"] for c in self.chunks(text) if "strata_mcp" in c]
        self.assertFalse(calls[-1]["ok"])
        self.assertTrue(calls[-1]["text"].startswith("error:"), calls[-1]["text"])
        self.assertIn("<tool_response>", self.engine.prompt_text(1))          # the chat went on

    def test_no_instance_means_no_tools(self):
        self.start("</think>\n\nhi", search=False)
        code, text = self.post({"strata_search": True})
        self.assertEqual(code, 200, text)
        self.assertNotIn("web_search", self.engine.prompt_text(0))

    def test_structured_output_with_search_is_refused(self):
        self.start("</think>\n\nhi")
        code, _ = self.post({"strata_search": True,
                             "response_format": {"type": "json_schema", "json_schema": {
                                 "name": "x", "schema": {"type": "object", "properties": {}}}}})
        self.assertEqual(code, 400)


class PageSettings(unittest.TestCase):
    """POST /search as the page's dialog sends it: the card's exact object, the refusals it must show, and one real
    query through Test.  The page kept sending a shape nothing exercised; these are its fields, as they leave it."""

    @classmethod
    def setUpClass(cls):
        cls.good = fake.search_server()
        cls.base = f"http://127.0.0.1:{cls.good.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.good.shutdown()
        cls.good.server_close()

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        tok = ByteTokenizer()
        self.svc = Service(MockEngine(tok, "</think>\n\nhi"), tok, ChatTemplate(ROOT / "serve/chat_template.jinja"))
        self.svc.search_path = os.path.join(self.dir.name, "websearch.json")
        self.svc.config_path = None
        self.httpd = serve(self.svc, port=0)
        self.base_url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.dir.cleanup()

    def call(self, path, body=None):
        req = urllib.request.Request(self.base_url + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read())

    def card(self, **over):
        """The object the dialog's Save sends: every field, the toggles as booleans, numbers as numbers."""
        body = {"enabled": True, "base_url": self.base + "/", "auth": "none", "token": "", "basic_user": "",
                "basic_pass": "", "headers": {}, "language": "en", "safesearch": "", "categories": "",
                "time_range": "", "read_page": True, "allow_local": True, "timeout_s": 20, "max_results": 8}
        body.update(over)
        return body

    def test_the_cards_payload_is_saved_and_read_back(self):
        code, view = self.call("/search", {"set": self.card()})
        self.assertEqual(code, 200, view)
        self.assertTrue(view["configured"])
        self.assertEqual(view["settings"]["base_url"], self.base)            # the trailing slash goes
        code, again = self.call("/search")
        self.assertEqual(code, 200)
        self.assertEqual(again["settings"]["base_url"], self.base)
        self.assertEqual(sorted(again["tools"]), ["read_page", "web_search"])
        self.assertEqual(self.svc.search.settings["base_url"], self.base)    # in force, not only on disk

    def test_switching_it_off_hides_the_tools(self):
        self.call("/search", {"set": self.card()})
        code, view = self.call("/search", {"set": self.card(enabled=False)})
        self.assertEqual(code, 200, view)
        self.assertFalse(view["configured"])
        self.assertIsNone(self.svc.search)

    def test_a_bad_url_is_refused_with_a_sentence(self):
        for bad, want in (("search.local", "must start with http"), (self.base + "/?q=x", "base address")):
            with self.subTest(url=bad):
                code, out = self.call("/search", {"set": self.card(base_url=bad)})
                self.assertEqual(code, 400, out)
                self.assertIn(want, out["error"]["message"])

    def test_an_enabled_search_needs_a_url(self):
        code, out = self.call("/search", {"set": self.card(base_url="")})
        self.assertEqual(code, 400)
        self.assertIn("needs the SearXNG instance's URL", out["error"]["message"])

    def test_test_runs_one_real_query(self):
        code, out = self.call("/search", {"test": {"query": "qwen 3.8", "settings": self.card()}})
        self.assertEqual(code, 200, out)
        self.assertTrue(out["ok"], out)
        self.assertGreater(out["results"], 0)
        self.assertTrue(out["first_url"])

    def test_test_names_an_instance_without_json(self):
        bad = fake.search_server()
        bad.mode = "no-json"
        try:
            body = self.card(base_url=f"http://127.0.0.1:{bad.server_address[1]}", allow_local=True)
            code, out = self.call("/search", {"test": {"query": "qwen", "settings": body}})
        finally:
            bad.shutdown()
            bad.server_close()
        self.assertEqual(code, 200, out)
        self.assertFalse(out["ok"])
        self.assertIn("json", out["error"])

    def test_the_page_only(self):
        req = urllib.request.Request(self.base_url + "/search", data=b'{"set": {}}',
                                     headers={"Content-Type": "text/plain"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(caught.exception.code, 415)


if __name__ == "__main__":
    unittest.main()
