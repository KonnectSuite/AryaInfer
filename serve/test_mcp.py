"""serve/test_mcp.py - tools from MCP servers (serve/mcp.py) and the web app's tool loop, against the mock engine and
the fake MCP server in serve/mcp_fake_server.py (no GPU, no pack, no MCP SDK).

    python -m unittest serve.test_mcp -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from serve import mcp_fake_server as fake  # noqa: E402
from serve.frontend import ChatTemplate  # noqa: E402
from serve.mcp import (SECRET_MASK, McpCancelled, McpHub, hub_from_config, merge_config,  # noqa: E402
                       public_config)
from serve.server import ByteTokenizer, MockEngine, Service, serve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FAKE = str(ROOT / "serve" / "mcp_fake_server.py")
CTX = 8192


def stdio(*args, **extra):
    return {"command": sys.executable, "args": [FAKE, *args], **extra}


def call_script(name, **params):
    """The model's text for one tool call, as Qwen's template asks for it."""
    body = "".join(f"<parameter={k}>\n{v}\n</parameter>\n" for k, v in params.items())
    return f"</think>\n\nLet me check.\n\n<tool_call>\n<function={name}>\n{body}</function>\n</tool_call>"


class ScriptedEngine(MockEngine):
    """A mock engine with one script per call (the last one repeats): a tool call first, then the answer."""

    def __init__(self, tok, scripts, max_context=CTX, delay_s=0.0):
        super().__init__(tok, list(scripts), max_context=max_context, delay_s=delay_s)
        self.prompts = []

    def generate(self, ids, max_new, sampling, cancel, embeddings=None):
        self.prompts.append(list(ids))
        yield from super().generate(ids, max_new, sampling, cancel, embeddings)

    def prompt_text(self, i):
        return bytes(t for t in self.prompts[i] if t < 256).decode("utf-8", "replace")


# ------------------------------------------------------------------------------------------------ the client
class Client(unittest.TestCase):
    """The stdio client against the fake server: start, pagination, calls, errors, crashes, timeouts, the cap."""

    @classmethod
    def setUpClass(cls):
        cls.log = tempfile.NamedTemporaryFile(delete=False, suffix=".jsonl")
        cls.log.close()
        os.environ["FAKE_MCP_LOG"] = cls.log.name
        cls.hub = McpHub({"fake": stdio(), "paged": stdio("--page", "4"), "broken": stdio("--crash-at-start"),
                          "missing": {"command": "strata-no-such-program"}},
                         {"timeout_s": 1.5, "max_result_chars": 1000})
        cls.hub.start(wait=True)

    @classmethod
    def tearDownClass(cls):
        cls.hub.close()
        del os.environ["FAKE_MCP_LOG"]
        os.unlink(cls.log.name)

    def test_initialize_and_list_every_page(self):
        s = self.hub.servers["fake"]
        self.assertEqual(s.status, "ready")
        self.assertEqual(s.info["name"], "fake")
        self.assertEqual(s.info["protocol"], "2025-06-18")
        want = [t["name"] for t in fake.TOOLS]
        self.assertEqual([t["name"] for t in s.tools], want)         # 3 pages of 2
        self.assertEqual([t["name"] for t in self.hub.servers["paged"].tools], want)   # 2 pages of 4

    def test_namespaced_openai_tools(self):
        tools = self.hub.openai_tools()
        names = [t["function"]["name"] for t in tools]
        self.assertIn("fake__echo", names)
        self.assertIn("paged__echo", names)
        echo = next(t for t in tools if t["function"]["name"] == "fake__echo")
        self.assertEqual(echo["type"], "function")
        self.assertEqual(echo["function"]["parameters"]["properties"]["text"]["type"], "string")

    def test_a_server_that_fails_is_left_out(self):
        for name, why in (("broken", "missing configuration"), ("missing", "could not start")):
            with self.subTest(name=name):
                s = self.hub.servers[name]
                self.assertEqual(s.status, "failed")
                self.assertIn(why, s.error)
                self.assertFalse([t for t in self.hub.template_tools() if t["name"].startswith(name + "__")])
        st = {s["name"]: s for s in self.hub.status()["servers"]}
        self.assertEqual(st["broken"]["status"], "failed")
        self.assertEqual(st["fake"]["status"], "ready")

    def test_call(self):
        self.hub.routes()
        r = self.hub.call("fake__echo", {"text": "hello wörld"})
        self.assertEqual((r["ok"], r["text"], r["server"], r["tool"]), (True, "hello wörld", "fake", "echo"))
        self.assertEqual(self.hub.call("fake__add", {"a": 2, "b": 40})["text"], "42")

    def test_errors_become_text(self):
        self.hub.routes()
        r = self.hub.call("fake__fail", {})                         # the tool's own error (isError)
        self.assertFalse(r["ok"])
        self.assertEqual(r["text"], "error: it failed on purpose")
        r = self.hub.call("nobody__nothing", {})                    # not a tool at all
        self.assertTrue(r["text"].startswith("error: there is no tool"))
        # a JSON-RPC error from the server
        s = self.hub.servers["fake"]
        with self.assertRaises(Exception) as ctx:
            s.call("no-such-tool", {}, 5)
        self.assertIn("unknown tool", str(ctx.exception))

    def test_timeout(self):
        self.hub.routes()
        t0 = time.monotonic()
        r = self.hub.call("fake__sleep", {"seconds": 5})
        self.assertLess(time.monotonic() - t0, 4)
        self.assertFalse(r["ok"])
        self.assertIn("timed out after 1.5 s", r["text"])
        self.assertEqual(self.hub.call("fake__echo", {"text": "still here"})["text"], "still here")

    def test_truncation(self):
        self.hub.routes()
        r = self.hub.call("fake__big", {"n": 50000})
        self.assertTrue(r["ok"])
        self.assertTrue(r["truncated"])
        self.assertEqual(r["chars"], 50000)
        self.assertTrue(r["text"].startswith("y" * 1000 + "\n\n[... truncated"))
        self.assertIn("50,000 characters", r["text"])
        self.assertLess(len(r["text"]), 1200)

    def test_crash_mid_call_then_restart(self):
        hub = McpHub({"solo": stdio()}, {"timeout_s": 5})
        hub.start(wait=True)
        try:
            hub.routes()
            r = hub.call("solo__die", {})
            self.assertFalse(r["ok"])
            self.assertIn("the server stopped", r["text"])
            self.assertIn("dying on purpose", r["text"])
            self.assertEqual(hub.servers["solo"].status, "stopped")
            self.assertIn("solo__echo", hub.routes())                # its tools stay: the next call restarts it
            self.assertEqual(hub.call("solo__echo", {"text": "back"})["text"], "back")
            self.assertEqual(hub.servers["solo"].status, "ready")
        finally:
            hub.close()

    def test_cancel(self):
        self.hub.routes()
        cancel = threading.Event()
        threading.Timer(0.3, cancel.set).start()
        t0 = time.monotonic()
        with self.assertRaises(McpCancelled):
            self.hub.call("fake__sleep", {"seconds": 1.2}, cancel)
        self.assertLess(time.monotonic() - t0, 1.0)
        time.sleep(0.3)
        seen = [json.loads(line) for line in Path(self.log.name).read_text().splitlines()]
        self.assertTrue(any("cancelled" in e for e in seen), seen)   # notifications/cancelled reached the server


class HttpClient(unittest.TestCase):
    """Streamable HTTP: JSON answers, an event-stream answer, the session id."""

    @classmethod
    def setUpClass(cls):
        cls.httpd = fake.http_server(0)
        url = f"http://127.0.0.1:{cls.httpd.server_address[1]}/mcp"
        cls.hub = McpHub({"web": {"url": url}, "down": {"url": "http://127.0.0.1:9/mcp"}}, {"timeout_s": 1.5})
        cls.hub.start(wait=True)

    @classmethod
    def tearDownClass(cls):
        cls.hub.close()
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_list_and_call(self):
        s = self.hub.servers["web"]
        self.assertEqual(s.status, "ready", s.error)
        self.assertEqual(len(s.tools), len(fake.TOOLS))             # pages, with the session id on each request
        self.assertEqual(s.transport.session, "s-1")
        self.hub.routes()
        self.assertEqual(self.hub.call("web__echo", {"text": "over http"})["text"], "over http")   # event stream
        self.assertEqual(self.hub.call("web__fail", {})["text"], "error: it failed on purpose")

    def test_timeout_and_unreachable(self):
        self.hub.routes()
        r = self.hub.call("web__sleep", {"seconds": 4})
        self.assertIn("timed out", r["text"])
        self.assertEqual(self.hub.servers["down"].status, "failed")
        self.assertIn("could not reach", self.hub.servers["down"].error)


class Config(unittest.TestCase):
    def test_both_spellings_and_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "claude_desktop_config.json")
            Path(path).write_text(json.dumps({"mcpServers": {"b": {"url": "http://x/mcp"}, "a": stdio()}}),
                                  encoding="utf-8")
            hub = hub_from_config({"mcp_servers": {"a": {"command": "old"}},
                                   "mcpServers": {"c": stdio(), "off": {"command": "x", "disabled": True}},
                                   "mcp": {"timeout_s": 5, "max_result_chars": 100, "max_rounds": 3}}, path)
            # a disabled entry is kept (the Monitor tab lists it and can switch it back on), but it is not started
            self.assertEqual(sorted(hub.servers), ["a", "b", "c", "off"])
            self.assertEqual(hub.servers["off"].status, "disabled")
            self.assertEqual(hub.sources["off"], "config")
            self.assertEqual(hub.sources["a"], "file")             # the file wins over the config's own "a"
            self.assertFalse([t for t in hub.template_tools() if t["name"].startswith("off__")])
            self.assertEqual(hub.servers["a"].cfg["command"], sys.executable)   # the file wins a name clash
            self.assertEqual(hub.servers["b"].kind, "http")
            self.assertEqual((hub.settings["timeout_s"], hub.settings["max_result_chars"], hub.settings["max_rounds"]),
                             (5.0, 100, 3))
        self.assertIsNone(hub_from_config({}))
        self.assertEqual(McpHub({}).settings["max_result_chars"], 20000)

    def test_bad_entries_stop_the_start(self):
        for cfg in ({"mcp_servers": {"x": {}}}, {"mcp_servers": {"x": {"command": "a", "args": "b"}}},
                    {"mcp_servers": ["x"]}, {"mcpServers": {"x": {"url": "http://a", "type": "sse"}}},
                    {"mcp_servers": {"x": {"command": "a"}}, "mcp": {"timeout_s": 0}},
                    {"mcp_servers": {"x": {"command": "a"}}, "mcp": {"max_rounds": 1.5}}):
            with self.subTest(cfg=cfg), self.assertRaises(SystemExit):
                hub_from_config(cfg)
        with self.assertRaises(SystemExit):
            hub_from_config({}, os.path.join(tempfile.gettempdir(), "strata-no-such-mcp.json"))


# ------------------------------------------------------------------------------------------------ the tool loop
class ToolLoop(unittest.TestCase):
    """The web app's chat (`"strata_mcp": true`): the model calls an MCP tool, the server runs it and the model
    answers with its result; plain API requests never see the MCP tools."""

    def setUp(self):
        self.log = tempfile.NamedTemporaryFile(delete=False, suffix=".jsonl")
        self.log.close()
        os.environ["FAKE_MCP_LOG"] = self.log.name
        self.hub = McpHub({"fake": stdio(), "broken": stdio("--crash-at-start")},
                          {"timeout_s": 10, "max_result_chars": 500, "max_rounds": 2})
        self.hub.start(wait=True)
        self.httpd = None

    def tearDown(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
        self.hub.close()
        del os.environ["FAKE_MCP_LOG"]
        os.unlink(self.log.name)

    def start(self, *scripts, delay_s=0.0):
        tok = ByteTokenizer()
        self.engine = ScriptedEngine(tok, list(scripts), delay_s=delay_s)
        self.svc = Service(self.engine, tok, ChatTemplate(ROOT / "serve/chat_template.jinja"))
        self.svc.mcp = self.hub
        self.httpd = serve(self.svc, port=0)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def post(self, body, headers=None, stream=True):
        body = {"model": "m", "messages": [{"role": "user", "content": "check it"}], "stream": stream, **body}
        req = urllib.request.Request(self.base + "/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                text = r.read().decode()
                return r.status, text
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.read().decode()

    @staticmethod
    def chunks(text):
        return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: {")]

    def test_tool_call_then_answer(self):
        self.start(call_script("fake__echo", text="hello from the tool"), "</think>\n\nThe tool said hello.")
        code, text = self.post({"strata_mcp": True})
        self.assertEqual(code, 200, text)
        cs = self.chunks(text)
        mcp = [c["strata_mcp"] for c in cs if "strata_mcp" in c]
        self.assertEqual([m["event"] for m in mcp], ["start", "call", "result"])
        self.assertEqual(mcp[1]["arguments"], {"text": "hello from the tool"})
        self.assertEqual((mcp[1]["server"], mcp[1]["tool"]), ("fake", "echo"))
        self.assertEqual((mcp[2]["ok"], mcp[2]["text"]), (True, "hello from the tool"))
        self.assertEqual(len({m["id"] for m in mcp}), 1)
        content = "".join((c["choices"][0]["delta"].get("content") or "") for c in cs)
        self.assertEqual(content, "Let me check.The tool said hello.")
        self.assertFalse([c for c in cs if c["choices"][0]["delta"].get("tool_calls")])   # nothing for the client to run
        self.assertEqual(cs[-1]["choices"][0]["finish_reason"], "stop")
        self.assertEqual(len(self.engine.prompts), 2)
        first, second = self.engine.prompt_text(0), self.engine.prompt_text(1)
        self.assertIn('"name": "fake__echo"', first)                 # the MCP tools are in the prompt
        self.assertNotIn("broken__", first)                          # the server that failed is left out
        self.assertIn("<function=fake__echo>\n<parameter=text>\nhello from the tool\n</parameter>", second)
        self.assertIn("<tool_response>\nhello from the tool\n</tool_response>", second)
        self.assertEqual(cs[-1]["usage"]["prompt_tokens"], len(self.engine.prompts[1]))

    def test_a_call_the_output_ends_inside_is_not_run(self):
        """#211: the model's turn ends inside an MCP call: nothing runs (it used to run with no arguments)."""
        script = call_script("fake__echo", text="hello from the tool")
        self.start(script[:script.index("from the tool")], "</think>\n\nnever")
        code, text = self.post({"strata_mcp": True})
        self.assertEqual(code, 200, text)
        cs = self.chunks(text)
        mcp = [c["strata_mcp"] for c in cs if "strata_mcp" in c]
        self.assertEqual([m["event"] for m in mcp], ["start"])        # the web app shows it as "Not run" at the end
        self.assertEqual(len(self.engine.prompts), 1)
        self.assertNotIn('"call"', Path(self.log.name).read_text())    # nothing ran
        self.assertEqual(cs[-1]["choices"][0]["finish_reason"], "stop")

    def test_non_stream(self):
        self.start(call_script("fake__add", a=2, b=3), "</think>\n\n5.")
        code, text = self.post({"strata_mcp": True}, stream=False)
        self.assertEqual(code, 200, text)
        msg = json.loads(text)["choices"][0]["message"]
        self.assertEqual(msg["content"], "Let me check.5.")
        self.assertEqual(msg["strata_mcp"][-1]["text"], "5")

    def test_plain_requests_get_no_mcp_tools(self):
        self.start(call_script("fake__echo", text="x"), "</think>\n\nnever")
        code, text = self.post({})
        self.assertEqual(code, 200, text)
        self.assertNotIn("fake__echo", self.engine.prompt_text(0))
        cs = self.chunks(text)
        self.assertFalse([c for c in cs if "strata_mcp" in c])
        self.assertEqual(cs[-1]["choices"][0]["finish_reason"], "tool_calls")   # returned to the client as always
        self.assertEqual(len(self.engine.prompts), 1)
        self.assertNotIn('"call"', Path(self.log.name).read_text())    # nothing ran
        for req in ({"strata_mcp": "yes"}, {"strata_mcp": 1}):         # only a real true opts in
            self.post(req)
            self.assertNotIn("fake__echo", self.engine.prompt_text(-1))

    def test_own_tools_still_go_to_the_client(self):
        own = [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object", "properties": {
            "q": {"type": "string"}}}}}]
        self.start(call_script("lookup", q="x"), "</think>\n\nnever")
        code, text = self.post({"strata_mcp": True, "tools": own})
        cs = self.chunks(text)
        calls = [tc for c in cs for tc in c["choices"][0]["delta"].get("tool_calls") or []]
        self.assertEqual(calls[0]["function"]["name"], "lookup")
        self.assertEqual(cs[-1]["choices"][0]["finish_reason"], "tool_calls")
        self.assertIn('"name": "lookup"', self.engine.prompt_text(0))
        self.assertIn('"name": "fake__echo"', self.engine.prompt_text(0))
        self.assertEqual(len(self.engine.prompts), 1)

    def test_tool_error_is_a_result(self):
        self.start(call_script("fake__fail"), "</think>\n\nIt failed.")
        code, text = self.post({"strata_mcp": True})
        mcp = [c["strata_mcp"] for c in self.chunks(text) if "strata_mcp" in c]
        self.assertEqual((mcp[-1]["ok"], mcp[-1]["text"]), (False, "error: it failed on purpose"))
        self.assertIn("<tool_response>\nerror: it failed on purpose\n</tool_response>", self.engine.prompt_text(1))
        self.assertEqual(self.chunks(text)[-1]["choices"][0]["finish_reason"], "stop")

    def test_truncated_for_the_model(self):
        self.start(call_script("fake__big", n=3000), "</think>\n\nLong.")
        self.post({"strata_mcp": True})
        second = self.engine.prompt_text(1)
        self.assertIn("y" * 500 + "\n\n[... truncated: the tool returned 3,000 characters", second)
        self.assertNotIn("y" * 501, second)

    def test_max_rounds(self):
        self.start(call_script("fake__echo", text="again"))          # the model never stops calling
        code, text = self.post({"strata_mcp": True})
        mcp = [c["strata_mcp"] for c in self.chunks(text) if "strata_mcp" in c]
        self.assertEqual(len(self.engine.prompts), 3)                # 2 rounds of tools, then the limit
        self.assertEqual(sum(m["event"] == "call" for m in mcp), 2)
        self.assertIn({"event": "limit", "max_rounds": 2}, mcp)
        self.assertTrue(mcp[-1].get("skipped"))
        self.assertEqual(self.chunks(text)[-1]["choices"][0]["finish_reason"], "stop")

    def test_stop_during_a_tool(self):
        """Closing the connection while a slow tool runs stops the tool (notifications/cancelled) and the loop."""
        self.start(call_script("fake__sleep", seconds=8), "</think>\n\nnever")
        body = {"model": "m", "messages": [{"role": "user", "content": "x"}], "stream": True, "strata_mcp": True}
        req = urllib.request.Request(self.base + "/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        r = urllib.request.urlopen(req, timeout=30)
        for raw in r:
            if b'"event": "call"' in raw:
                break
        r.close()                                                    # the web app's Stop aborts the fetch
        t0 = time.monotonic()
        while time.monotonic() - t0 < 6 and "cancelled" not in Path(self.log.name).read_text():
            time.sleep(0.1)
        self.assertIn("cancelled", Path(self.log.name).read_text())
        self.assertLess(time.monotonic() - t0, 6)
        time.sleep(0.5)
        self.assertEqual(len(self.engine.prompts), 1)                # no second round
        self.assertFalse(self.svc.status["busy"])

    def test_only_from_the_app_s_own_page(self):
        self.start("</think>\n\nhi")
        req = urllib.request.Request(self.base + "/v1/chat/completions", data=json.dumps(
            {"model": "m", "messages": [{"role": "user", "content": "x"}], "strata_mcp": True}).encode(),
            headers={"Content-Type": "text/plain"})                  # a cross-site "simple" request
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(ctx.exception.code, 415)
        code, _ = self.post({"strata_mcp": True}, {"Origin": "http://evil.example"})
        self.assertEqual(code, 403)
        self.assertEqual(self.engine.prompts, [])
        host = self.base.split("://", 1)[1]
        code, _ = self.post({"strata_mcp": True}, {"Origin": "http://" + host})
        self.assertEqual(code, 200)

    def test_get_mcp(self):
        self.start("</think>\n\nhi")
        with urllib.request.urlopen(self.base + "/mcp", timeout=10) as r:
            st = json.loads(r.read())
        servers = {s["name"]: s for s in st["servers"]}
        self.assertEqual(servers["fake"]["status"], "ready")
        self.assertEqual(servers["fake"]["transport"], "stdio")
        self.assertIn("fake__echo", [t["name"] for t in servers["fake"]["tools"]])
        self.assertEqual(servers["broken"]["status"], "failed")
        self.assertIn("missing configuration", servers["broken"]["error"])
        self.assertEqual(st["tools"], len(fake.TOOLS))
        self.assertEqual(st["settings"]["max_rounds"], 2)
        self.svc.api_key = "k"
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(self.base + "/mcp", timeout=10)
        self.svc.api_key = ""


class NoServers(unittest.TestCase):
    def test_opt_in_without_servers_is_a_plain_chat(self):
        tok = ByteTokenizer()
        svc = Service(ScriptedEngine(tok, ["</think>\n\nhi"]), tok, ChatTemplate(ROOT / "serve/chat_template.jinja"))
        httpd = serve(svc, port=0)
        try:
            base = f"http://127.0.0.1:{httpd.server_address[1]}"
            with urllib.request.urlopen(base + "/mcp", timeout=10) as r:
                self.assertEqual(json.loads(r.read()), {"servers": [], "tools": 0})
            req = urllib.request.Request(base + "/v1/chat/completions", data=json.dumps(
                {"model": "m", "messages": [{"role": "user", "content": "x"}], "strata_mcp": True}).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                self.assertEqual(json.loads(r.read())["choices"][0]["message"]["content"], "hi")
        finally:
            httpd.shutdown()
            httpd.server_close()


# ------------------------------------------------------------------------------------------------ the page's editor
class Editor(unittest.TestCase):
    """Adding, changing, disabling and removing servers on a running hub: only that server starts or stops."""

    def setUp(self):
        self.hub = McpHub({"kept": stdio()}, {"timeout_s": 10, "max_result_chars": 500})
        self.hub.start(wait=True)

    def tearDown(self):
        self.hub.close()

    def test_add_change_disable_remove(self):
        kept = self.hub.servers["kept"]
        self.hub.add_server("extra", stdio())
        self.hub.wait(30)
        self.assertEqual(self.hub.servers["extra"].status, "ready")
        self.assertIn("extra__echo", self.hub.routes())
        self.assertIs(self.hub.servers["kept"], kept)                 # the other server was not restarted
        self.assertEqual(kept.status, "ready")
        self.assertEqual(self.hub.call("extra__add", {"a": 1, "b": 2})["text"], "3")
        self.hub.replace_server("extra", stdio("--page", "5"))         # changed settings, same name
        self.hub.wait(30)
        self.assertEqual(self.hub.servers["extra"].status, "ready")
        self.assertIn("extra__echo", self.hub.routes())
        self.hub.replace_server("extra", {**stdio(), "disabled": True})   # disabled: kept, not offered, not started
        self.assertEqual(self.hub.servers["extra"].status, "disabled")
        self.assertNotIn("extra__echo", self.hub.routes())
        self.assertFalse(self.hub.call("extra__echo", {"text": "x"})["ok"])
        self.hub.remove_server("extra")
        self.assertNotIn("extra", self.hub.servers)
        self.assertNotIn("extra__echo", self.hub.routes())
        self.assertEqual(self.hub.servers["kept"].status, "ready")

    def test_reconnect_starts_a_server_that_died_again(self):
        self.hub.add_server("mortal", stdio())
        self.hub.wait(30)
        self.assertFalse(self.hub.call("mortal__die", {})["ok"])      # the process exits mid-call
        self.hub.reconnect("mortal")
        self.hub.wait(30)
        self.assertEqual(self.hub.servers["mortal"].status, "ready")
        self.assertEqual(self.hub.call("mortal__echo", {"text": "back"})["text"], "back")

    def test_names_and_settings_are_checked(self):
        with self.assertRaises(ValueError):
            self.hub.add_server("kept", stdio())                      # the name is taken
        for name in ("", "my server", "a" * 41, "x/y"):
            with self.assertRaises(ValueError):
                self.hub.add_server(name, stdio())
        for cfg in ({}, {"command": ""}, {"command": "a", "args": "b"}, {"url": "http://a", "type": "sse"},
                    {"command": "a", "env": "X=1"}):
            with self.assertRaises(ValueError):
                self.hub.add_server("fresh", cfg)
        self.assertNotIn("fresh", self.hub.servers)                   # a refused entry adds nothing
        for call in (self.hub.remove_server, self.hub.reconnect):
            with self.assertRaises(ValueError):
                call("nobody")
        with self.assertRaises(ValueError):
            self.hub.replace_server("nobody", stdio())

    def test_secrets_are_masked_and_kept(self):
        cfg = {"command": "x", "env": {"TOKEN": "s3cret", "PLAIN": "1"},
               "headers": {"Authorization": "Bearer t"}}
        public = public_config(cfg)
        self.assertEqual(public["env"], {"TOKEN": SECRET_MASK, "PLAIN": SECRET_MASK})
        self.assertNotIn("s3cret", json.dumps(public))
        merged = merge_config({"command": "y", "env": {"TOKEN": SECRET_MASK, "NEW": "n"}}, cfg)
        self.assertEqual(merged["env"], {"TOKEN": "s3cret", "NEW": "n"})    # the mask keeps what is stored
        self.assertNotIn("headers", merged)                                 # a block the page left out is gone


class EditorHttp(unittest.TestCase):
    """POST /mcp from the page: the file it writes, the servers it starts, and the gates in front of it."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        tok = ByteTokenizer()
        self.engine = ScriptedEngine(tok, [call_script("fresh__echo", text="from the new server"),
                                           "</think>\n\nIt answered."])
        self.svc = Service(self.engine, tok, ChatTemplate(ROOT / "serve/chat_template.jinja"))
        self.svc.config_path = os.path.join(self.dir.name, "strata-m.json")
        self.hub = McpHub({"fixed": stdio()}, {"timeout_s": 10, "max_result_chars": 500},
                          {"fixed": "config"})
        self.svc.mcp = self.hub
        self.hub.start(wait=True)
        self.httpd = serve(self.svc, port=0)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.hub.close()

    def post(self, body, headers=None):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        req = urllib.request.Request(self.base + "/mcp", data=raw,
                                     headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read() or b"{}")

    def status(self):
        with urllib.request.urlopen(self.base + "/mcp", timeout=10) as r:
            return json.loads(r.read())

    def server(self, name):
        return next((s for s in self.status()["servers"] if s["name"] == name), None)

    def file(self):
        return json.loads((Path(self.dir.name) / "mcp-servers.json").read_text(encoding="utf-8"))

    def chat(self, strata_mcp=True):
        body = {"model": "m", "messages": [{"role": "user", "content": "use it"}], "strata_mcp": strata_mcp}
        req = urllib.request.Request(self.base + "/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())

    def test_add_then_chat_without_a_restart(self):
        code, body = self.post({"add": {"fresh": stdio()}})
        self.assertEqual(code, 200, body)
        self.assertEqual(body["changed"], ["added fresh"])
        self.assertEqual(self.file()["mcpServers"], {"fresh": stdio()})     # the next start has it too
        self.hub.wait(30)
        self.assertEqual(self.server("fresh")["status"], "ready")
        self.assertTrue(self.server("fresh")["editable"])
        self.assertFalse(self.server("fixed")["editable"])                  # a hand-written entry stays hand-written
        self.assertEqual(self.server("fixed")["source"], "config")
        msg = self.chat()["choices"][0]["message"]                          # tools reach the model right away
        self.assertEqual(msg["content"], "Let me check.It answered.")
        self.assertEqual(msg["strata_mcp"][-1]["text"], "from the new server")
        self.assertIn('"name": "fresh__echo"', self.engine.prompt_text(0))

    def test_update_and_remove(self):
        self.post({"add": {"fresh": stdio()}})
        self.hub.wait(30)
        code, body = self.post({"update": {"name": "fresh", "config": stdio("--page", "5")}})
        self.assertEqual(code, 200, body)
        self.assertEqual(body["changed"], ["changed fresh"])
        self.assertEqual(self.file()["mcpServers"]["fresh"]["args"], [FAKE, "--page", "5"])
        self.hub.wait(30)
        self.assertEqual(self.server("fresh")["status"], "ready")
        code, body = self.post({"remove": ["fresh"]})
        self.assertEqual(code, 200, body)
        self.assertEqual(self.file()["mcpServers"], {})
        self.assertIsNone(self.server("fresh"))
        self.assertEqual(sorted(s["name"] for s in self.status()["servers"]), ["fixed"])

    def test_the_pages_own_keys_come_back(self):
        # the page stores which mark a server gets and the name the catalog gave it; the engine ignores both, but
        # GET /mcp has to hand them back so the next load draws the same card
        code, _ = self.post({"add": {"marked": {**stdio(), "icon": "github", "title": "GitHub"}}})
        self.assertEqual(code, 200)
        stored = self.file()["mcpServers"]["marked"]
        self.assertEqual((stored["icon"], stored["title"]), ("github", "GitHub"))
        self.assertEqual(self.server("marked")["config"]["icon"], "github")
        # an update is the whole server, as the page sends it (its own keys included): sending them back keeps them
        code, _ = self.post({"update": {"name": "marked", "config": {**stored, "disabled": True}}})
        self.assertEqual(code, 200)
        self.assertEqual(self.server("marked")["config"]["icon"], "github")
        self.assertEqual(self.server("marked")["config"]["disabled"], True)
        self.assertEqual(self.file()["mcpServers"]["marked"]["icon"], "github")

    def test_a_disabled_server_is_listed_and_switched_back_on(self):
        code, _ = self.post({"add": {"off": {**stdio(), "disabled": True}}})
        self.assertEqual(code, 200)
        self.assertEqual(self.server("off")["status"], "disabled")
        self.assertEqual(self.server("off")["config"]["disabled"], True)
        self.assertNotIn("off__echo", self.hub.routes())
        code, _ = self.post({"update": {"name": "off", "config": stdio()}})
        self.assertEqual(code, 200)
        self.hub.wait(30)
        self.assertEqual(self.server("off")["status"], "ready")
        self.assertIn("off__echo", self.hub.routes())

    def test_secrets_never_leave_the_server(self):
        code, _ = self.post({"add": {"vault": {**stdio(), "env": {"MCP_TOKEN": "s3cret"}}}})
        self.assertEqual(code, 200)
        self.assertEqual(self.server("vault")["config"]["env"], {"MCP_TOKEN": SECRET_MASK})
        self.assertNotIn("s3cret", json.dumps(self.status()))
        self.assertEqual(self.file()["mcpServers"]["vault"]["env"], {"MCP_TOKEN": "s3cret"})   # stored, not masked
        code, _ = self.post({"update": {"name": "vault", "config": {**stdio(), "env": {"MCP_TOKEN": SECRET_MASK}}}})
        self.assertEqual(code, 200)
        self.assertEqual(self.file()["mcpServers"]["vault"]["env"], {"MCP_TOKEN": "s3cret"})

    def test_a_refused_change_writes_nothing_and_starts_nothing(self):
        for body in ({"add": {"fresh": {}}}, {"add": {"my server": stdio()}}, {"add": {"a": stdio(), "b": stdio()}},
                     {"add": {"fresh": {"url": "http://a", "type": "sse"}}}, {"nonsense": True},
                     {"update": {"name": "nobody", "config": stdio()}}):
            with self.subTest(body=body):
                code, out = self.post(body)
                self.assertEqual(code, 400, out)
                self.assertIn("message", out["error"])
        self.assertFalse((Path(self.dir.name) / "mcp-servers.json").exists())
        self.assertNotIn("fresh", self.hub.servers)

    def test_a_hand_written_entry_is_named_where_it_lives(self):
        code, out = self.post({"update": {"name": "fixed", "config": stdio()}})
        self.assertEqual(code, 400)
        self.assertIn("run config", out["error"]["message"])
        self.assertEqual(self.post({"remove": ["fixed"]})[0], 400)

    def test_the_page_only(self):
        code, out = self.post({"add": {"fresh": stdio()}}, headers={"Origin": "http://evil.example"})
        self.assertEqual(code, 403, out)
        raw = json.dumps({"add": {"fresh": stdio()}}).encode()
        req = urllib.request.Request(self.base + "/mcp", data=raw, headers={"Content-Type": "text/plain"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(ctx.exception.code, 415)
        self.assertNotIn("fresh", self.hub.servers)


if __name__ == "__main__":
    unittest.main()
