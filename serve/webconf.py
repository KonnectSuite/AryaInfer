"""serve/webconf.py - the MCP servers AryaInfer's own page manages: `mcp-servers.json`, beside the run config.

serve/mcp.py reads servers from the run config and from a --mcp-config file and never writes them.  The Monitor
tab's editor needs a place of its own, so a hand-written entry and an entry the page manages never fight over one
file.  This file is that place: Claude Desktop's shape (`{"version": 1, "mcpServers": {...}}`), written whole and
atomically (a temporary file moved over the old one, as serve/runconfig.py does).

A file that cannot be read is moved aside rather than stopping the server: the page then shows no servers, and the
unreadable file keeps its old contents under `<name>.corrupt-<timestamp>`.  Nothing here starts a server - that is
serve/mcp.py's McpHub, which applies each change as it is saved.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

FILE = "mcp-servers.json"
VERSION = 1
ROOT = Path(__file__).resolve().parent.parent


def path_for(config_path: str | Path | None) -> Path:
    """The managed file beside the run config (else beside the code): the run config is per model, this file is not."""
    base = Path(config_path).parent if config_path else ROOT
    return base / FILE


def load(path: str | Path) -> dict[str, dict]:
    """The servers in the file; {} when it is missing or was moved aside as unreadable."""
    path = Path(path)
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        return _aside(path, str(e))
    block = data.get("mcpServers", data.get("mcp_servers")) if isinstance(data, dict) else None
    if not isinstance(block, dict):
        return _aside(path, "expected {\"mcpServers\": {...}}")
    return {str(name): cfg for name, cfg in block.items() if isinstance(cfg, dict)}


def _aside(path: Path, why: str) -> dict:
    """Move an unreadable file out of the way and say so: the reader keeps it, the page starts empty."""
    target = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
    try:
        os.replace(path, target)
        where = f"moved to {target.name}"
    except OSError:
        where = "left as it is"
    print(f"[strata] {path.name}: {why}; {where}. The Monitor tab starts with no servers; the rest of the chat is "
          "unaffected.", flush=True)
    return {}


def save(path: str | Path, servers: dict[str, dict]) -> Path:
    """The whole file: a temporary file written first, then moved over the old one (a crash cannot leave half a file)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"version": VERSION, "mcpServers": servers}, indent=1) + "\n"
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    os.replace(tmp, path)
    return path
