"""serve/toolhub.py - several tool providers behind the one interface the chat's tool loop uses.

`run_with_mcp` (serve/server.py) was written for one provider, serve/mcp.py's McpHub: it reads `settings["max_rounds"]`,
`routes()`, `template_tools(exclude)` and `call(name, arguments, cancel)`.  This joins two of them - the MCP servers
and the web search of serve/websearch.py - so one answer can use either, and a request that has only one configured
still runs exactly as before.
"""
from __future__ import annotations


class ToolHub:
    """McpHub and SearchHub together: merged routes, one call, the largest max_rounds."""

    def __init__(self, providers):
        self.providers = [p for p in providers if p is not None]
        self.settings: dict = {}
        for p in self.providers:
            for key, value in (getattr(p, "settings", None) or {}).items():
                if key == "max_rounds":
                    self.settings[key] = max(int(self.settings.get(key, 0)), int(value))
                else:
                    self.settings.setdefault(key, value)

    def wait(self, timeout: float | None = None) -> None:
        for p in self.providers:
            p.wait(timeout)

    def routes(self) -> dict:
        out: dict = {}
        for p in self.providers:                     # the first provider keeps a name two of them would share
            for name, entry in p.routes().items():
                out.setdefault(name, entry)
        return out

    def template_tools(self, exclude=()) -> list[dict]:
        out: list[dict] = []
        for p in self.providers:
            out.extend(p.template_tools(exclude=exclude))
        return out

    def openai_tools(self) -> list[dict]:
        return [{"type": "function", "function": t} for t in self.template_tools()]

    def call(self, name: str, arguments: dict, cancel=None) -> dict:
        for p in self.providers:
            if name in p.routes():
                return p.call(name, arguments, cancel)
        return {"server": None, "tool": name, "ok": False, "text": f"error: there is no tool named {name!r}",
                "chars": 0, "truncated": False, "ms": 0}

    def status(self) -> dict:
        return {"providers": [p.status() for p in self.providers]}
