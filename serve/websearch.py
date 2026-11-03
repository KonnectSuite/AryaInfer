"""serve/websearch.py - web search through a SearXNG instance, and a page reader, for the web app's chats.

AryaInfer ships no search of its own.  Point it at a [SearXNG](https://docs.searxng.org) instance - one on this PC,
on the LAN or on a Tailnet - and the chat page offers the model two tools: `web_search` (a query in, numbered results
out) and `read_page` (one address in, the readable text of that page out).  The settings live in `websearch.json`
beside the run config and the page edits them (Settings > Tools); the run config's `"search"` block is read too,
and the file wins.  Nothing is offered until a URL is set and the switch is on.

SearXNG details worth remembering (they are the failure modes the messages name):
- `format=json` must be listed in the instance's `search.formats`, else it answers 403 with an HTML page;
- a `!bang` query answers with a 302 to the destination instead of results, so a redirect becomes one result;
- `answers[]` carries the instant answer, which is shown above the results;
- `unresponsive_engines` names the engines that failed for that query (a CAPTCHA on one engine is normal, not fatal);
- it cannot fetch an arbitrary page: `read_page` fetches it here, and refuses local or private addresses unless
  `allow_local` is on.

The tools run in the server, like the MCP ones (serve/mcp.py); the text the model reads is capped by the settings.
"""
from __future__ import annotations

import base64
import html
import http.client
import ipaddress
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

FILE = "websearch.json"
VERSION = 1
ROOT = Path(__file__).resolve().parent.parent
USER_AGENT = "strata-websearch/1 (+local AryaInfer chat)"
MAX_PAGE_BYTES = 2 << 20                 # a page over this is cut: the reader shows text, not downloads
MAX_REDIRECTS = 5
SERVER = "web"                           # the name the chat shows for these tools' calls

DEFAULTS = {
    "enabled": False,                    # the switch in the card: off until the user turns it on
    "base_url": "",                      # https://search.example.org (no trailing slash needed)
    "auth": "none",                      # none | bearer | basic | header
    "token": "",                         # Bearer token
    "basic_user": "", "basic_pass": "",  # Basic auth
    "headers": {},                       # the whole header set for auth "header"
    "language": "",                      # "" = the instance's default; e.g. en, de, fr
    "safesearch": "",                    # "" = the instance's default; "0" off, "1" moderate, "2" strict
    "categories": "",                    # e.g. general, news, it
    "time_range": "",                    # "" | day | week | month | year
    "timeout_s": 20.0,
    "max_results": 8,                    # per search, 1-20
    "max_search_chars": 6000,            # what the model reads of one search
    "max_fetch_chars": 6000,             # what the model reads of one page
    "read_page": True,                   # offer the page reader too
    "allow_local": False,                # read pages on this PC or the LAN (a self-hosted wiki, a router's page)
}
SECRET_KEYS = ("token", "basic_pass")
LANGUAGES = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z]{2,4})?$")


class WebSearchError(RuntimeError):
    """The instance or the page could not be used; the message says what to change."""


class WebSearchTimeout(WebSearchError):
    pass


class WebSearchCancelled(WebSearchError):
    """The chat was stopped while the request ran."""


# ------------------------------------------------------------------------------------------------ the settings
def path_for(config_path: str | Path | None) -> Path:
    """The settings file beside the run config (else beside the code): one file for every model."""
    base = Path(config_path).parent if config_path else ROOT
    return base / FILE


def normalize(raw: dict) -> dict:
    """The settings with every value checked and filled in from DEFAULTS.  ValueError: the sentence the page shows."""
    if not isinstance(raw, dict):
        raise ValueError("the web search settings must be an object")
    out = {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v) for k, v in DEFAULTS.items()}
    for key, value in raw.items():
        if key in DEFAULTS:
            out[key] = value
    for key in ("enabled", "read_page", "allow_local"):
        if not isinstance(out[key], bool):
            if out[key] in (0, 1, "true", "false", "on", "off"):
                out[key] = str(out[key]).lower() in ("1", "true", "on")
            else:
                raise ValueError(f"{key} must be true or false, not {out[key]!r}")
    out["base_url"] = str(out.get("base_url") or "").strip().rstrip("/")
    if out["base_url"]:
        parts = urllib.parse.urlsplit(out["base_url"])
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError(f"the instance's URL must start with http:// or https://, not {out['base_url']!r}")
        if parts.query or parts.fragment:
            raise ValueError("the instance's URL is a base address: leave out ?query and #hash")
    out["auth"] = str(out.get("auth") or "none").strip().lower() or "none"
    if out["auth"] not in ("none", "bearer", "basic", "header"):
        raise ValueError('auth is "none", "bearer", "basic" or "header"')
    out["token"] = str(out.get("token") or "").strip()
    out["basic_user"] = str(out.get("basic_user") or "").strip()
    out["basic_pass"] = str(out.get("basic_pass") or "")
    headers = out.get("headers")
    out["headers"] = ({str(k).strip(): str(v) for k, v in headers.items() if str(k).strip()}
                      if isinstance(headers, dict) else {})
    if out["auth"] == "bearer" and not out["token"]:
        raise ValueError("bearer authentication needs a token")
    if out["auth"] == "basic" and not out["basic_user"]:
        raise ValueError("basic authentication needs a user name")
    if out["auth"] == "header" and not out["headers"]:
        raise ValueError("header authentication needs at least one header")
    out["language"] = str(out.get("language") or "").strip()
    if out["language"] and not LANGUAGES.match(out["language"]):
        raise ValueError(f"language {out['language']!r} is not a language code such as en or pt-BR")
    out["safesearch"] = str(out.get("safesearch") if out.get("safesearch") not in (None, "") else "").strip()
    if out["safesearch"] not in ("", "0", "1", "2"):
        raise ValueError('safe search is "0" (off), "1" (moderate), "2" (strict), or empty for the instance default')
    out["time_range"] = str(out.get("time_range") or "").strip().lower()
    if out["time_range"] not in ("", "day", "week", "month", "year"):
        raise ValueError('the time range is "day", "week", "month", "year", or empty')
    out["categories"] = str(out.get("categories") or "").strip()
    out["timeout_s"] = _number(out["timeout_s"], "timeout_s", 2, 60, "seconds")
    out["max_results"] = int(_number(out["max_results"], "max_results", 1, 20, "results"))
    out["max_search_chars"] = int(_number(out["max_search_chars"], "max_search_chars", 500, 50000, "characters"))
    out["max_fetch_chars"] = int(_number(out["max_fetch_chars"], "max_fetch_chars", 500, 50000, "characters"))
    if out["enabled"] and not out["base_url"]:
        raise ValueError("an enabled web search needs the SearXNG instance's URL")
    return out


def _number(value, name: str, low: float, high: float, what: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number of {what}, not {value!r}") from None
    if not low <= number <= high:
        raise ValueError(f"{name} must be between {low:g} and {high:g} {what}")
    return number


def public_settings(settings: dict) -> dict:
    """The settings with the secrets masked: what GET /search may tell the page."""
    out = {k: v for k, v in settings.items() if k not in SECRET_KEYS and k != "headers"}
    for key in SECRET_KEYS:
        if settings.get(key):
            out[key] = MASK
    out["headers"] = {k: MASK for k in (settings.get("headers") or {})}
    return out


def merge_secrets(new: dict, old: dict) -> dict:
    """`new` with a masked secret replaced by the stored one - the page is never shown the real value."""
    out = dict(new)
    for key in SECRET_KEYS:
        if out.get(key) in (MASK, None) and old.get(key):
            out[key] = old[key]
    headers = out.get("headers")
    if isinstance(headers, dict):
        kept = old.get("headers") if isinstance(old.get("headers"), dict) else {}
        out["headers"] = {k: (kept.get(k, v) if v in (MASK, None) else v) for k, v in headers.items()}
    return out


MASK = "********"


def read_settings(path: str | Path) -> dict:
    """The saved settings; {} when the file is missing or was moved aside as unreadable."""
    path = Path(path)
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        _aside(path, str(e))
        return {}
    block = data.get("settings") if isinstance(data, dict) else None
    if block is None and isinstance(data, dict):
        block = {k: v for k, v in data.items() if k in DEFAULTS}
    if not isinstance(block, dict):
        _aside(path, "expected {\"settings\": {...}}")
        return {}
    return {k: v for k, v in block.items() if k in DEFAULTS}


def _aside(path: Path, why: str) -> None:
    target = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
    try:
        os.replace(path, target)
        where = f"moved to {target.name}"
    except OSError:
        where = "left as it is"
    print(f"[strata] {path.name}: {why}; {where}. Web search starts unconfigured.", flush=True)


def write_settings(path: str | Path, settings: dict) -> Path:
    """The whole file, written to a temporary file and moved over the old one."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"version": VERSION, "settings": settings}, indent=1, ensure_ascii=False) + "\n"
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    os.replace(tmp, path)
    return path


# ------------------------------------------------------------------------------------------------ HTTP
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Do not follow a redirect: a SearXNG `!bang` answers with one, and the reader checks every hop itself."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _get(url: str, headers: dict, timeout: float, cancel, limit: int) -> tuple[int, object, bytes]:
    """GET once -> (status, headers, body at most `limit` bytes).  A 3xx is returned as one, not followed.

    The request runs on a thread so the chat's Stop is noticed while the instance is slow."""
    box: dict = {}

    def work():
        try:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.build_opener(_NoRedirect).open(req, timeout=timeout) as r:
                box["status"], box["headers"], box["body"] = r.status, r.headers, r.read(limit + 1)
        except urllib.error.HTTPError as e:              # 3xx and 4xx/5xx reach here (nothing follows a redirect)
            with e:
                box["status"], box["headers"] = e.code, e.headers
                try:
                    box["body"] = e.read(limit + 1) if e.code >= 400 else b""
                except (OSError, http.client.HTTPException):
                    box["body"] = b""
        except (TimeoutError, socket.timeout) as e:      # socket.timeout is TimeoutError since 3.10
            box["timeout"], box["error"] = True, e
        except (OSError, ValueError, http.client.HTTPException) as e:
            box["error"] = e

    t = threading.Thread(target=work, daemon=True, name="websearch-get")
    t.start()
    deadline = time.monotonic() + timeout + 5
    while t.is_alive():
        if cancel is not None and cancel.is_set():
            raise WebSearchCancelled("stopped")
        if time.monotonic() > deadline:
            raise WebSearchTimeout(f"no answer within {timeout:g} s")
        t.join(0.05)
    if box.get("timeout"):
        raise WebSearchTimeout(f"no answer within {timeout:g} s")
    if "error" in box:
        raise WebSearchError(str(box["error"])) from None
    return box["status"], box["headers"], box.get("body") or b""


def check_url(url: str, allow_local: bool = False) -> str:
    """An address the reader may fetch: http(s), no credentials in it, and a public address unless `allow_local`."""
    parts = urllib.parse.urlsplit(str(url).strip())
    if parts.scheme not in ("http", "https"):
        raise WebSearchError(f"{url!r} is not an http or https address")
    if not parts.hostname:
        raise WebSearchError(f"{url!r} has no host")
    if parts.username or parts.password:
        raise WebSearchError("an address with a user name and password in it is not read: put the credentials in the "
                             "web search card instead")
    if allow_local:
        return url
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80),
                                   type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as e:
        raise WebSearchError(f"{parts.hostname} cannot be looked up ({e})") from None
    for info in infos:
        try:
            ip = ipaddress.ip_address(str(info[4][0]).split("%")[0])
        except ValueError:
            continue
        if not ip.is_global:
            raise WebSearchError(f"{parts.hostname} resolves to {ip}, a local or private address: the page reader "
                                 "reads public pages (turn on \"allow_local\" in the web search card to read pages "
                                 "on this PC or the LAN)")
    return url


# ------------------------------------------------------------------------------------------------ search
def auth_headers(settings: dict) -> dict:
    """The request headers, with whichever authentication the settings name.  An async auth (a referenced token)
    is not needed here: the token is kept in the settings file, which the page never reads back unmasked."""
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if settings["auth"] == "bearer":
        headers["Authorization"] = f"Bearer {settings['token']}"
    elif settings["auth"] == "basic":
        pair = f"{settings['basic_user']}:{settings['basic_pass']}".encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(pair).decode("ascii")
    elif settings["auth"] == "header":
        headers.update({str(k): str(v) for k, v in (settings.get("headers") or {}).items()})
    else:
        headers.update({str(k): str(v) for k, v in (settings.get("headers") or {}).items()})
    return headers


def build_search_url(settings: dict, query: str) -> str:
    """`{base}/search?q=...&format=json` plus the optional filters the settings name."""
    params = {"q": query, "format": "json"}
    if settings["language"]:
        params["language"] = settings["language"]
    if settings["safesearch"] != "":
        params["safesearch"] = settings["safesearch"]
    if settings["categories"]:
        params["categories"] = settings["categories"]
    if settings["time_range"]:
        params["time_range"] = settings["time_range"]
    return f"{settings['base_url']}/search?" + urllib.parse.urlencode(params)


def decode_text(value) -> str:
    """SearXNG result text: HTML entities decoded and whitespace collapsed (the model reads plain sentences)."""
    text = html.unescape(str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def map_results(body: dict, max_results: int) -> tuple[list[dict], str, dict]:
    """A SearXNG JSON body -> ([{title, url, snippet, published}], instant answer, diagnostics)."""
    seen, results = set(), []
    for item in body.get("results") or []:
        if not isinstance(item, dict):
            continue
        url = item.get("url") if isinstance(item.get("url"), str) else ""
        if not url or url in seen:
            continue
        seen.add(url)
        results.append({"title": decode_text(item.get("title")) or url,
                        "url": url,
                        "snippet": decode_text(item.get("content")),
                        "published": decode_text(item.get("publishedDate")),
                        "engine": decode_text(item.get("engine"))})
        if len(results) >= max_results:
            break
    answers = body.get("answers") or []
    answer = decode_text(answers[0].get("answer")) if answers and isinstance(answers[0], dict) else ""
    engines = sorted({r["engine"] for r in results if r["engine"]})
    unresponsive = []
    for entry in body.get("unresponsive_engines") or []:
        if isinstance(entry, (list, tuple)) and entry:
            unresponsive.append({"engine": decode_text(entry[0]), "reason": decode_text(entry[1] if len(entry) > 1 else "")})
    return results, answer, {"engines": engines, "unresponsive": unresponsive, "results": len(results)}


def format_results(results: list[dict], answer: str, limit: int) -> tuple[str, int, bool]:
    """What the model reads: the instant answer, then one numbered block per result.  -> (text, full length, cut)."""
    lines = []
    if answer:
        lines.append(f"Instant answer: {answer}")
        lines.append("")
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']}")
        lines.append(f"   {r['url']}")
        if r["snippet"]:
            lines.append(f"   {r['snippet']}")
        if r["published"]:
            lines.append(f"   published: {r['published']}")
    text = "\n".join(lines) if lines else "No results."
    full = len(text)
    if full > limit:
        text = text[:limit] + f"\n\n[... cut: {full:,} characters, the first {limit:,} are shown]"
        return text, full, True
    return text, full, False


def search(settings: dict, query: str, cancel=None) -> tuple[str, int, bool, dict]:
    """One query -> (text the model reads, its full length, cut, diagnostics).  WebSearchError says what to fix."""
    query = str(query or "").strip()
    if not query:
        raise WebSearchError("the search needs a query")
    if not settings.get("base_url"):
        raise WebSearchError("web search has no SearXNG instance yet: set its URL in the web search card")
    status, headers, body = _get(build_search_url(settings, query), auth_headers(settings),
                                 float(settings["timeout_s"]), cancel, 4 << 20)
    if 300 <= status < 400:                                # a !bang: the destination is the one result
        destination = headers.get("Location") or ""
        destination = urllib.parse.urljoin(settings["base_url"] + "/", destination) if destination else ""
        if not destination:
            raise WebSearchError(f"the instance redirected the search (HTTP {status}) without a destination")
        text = f"1. {query}\n   {destination}"
        return text, len(text), False, {"engines": [], "unresponsive": [], "results": 1, "redirect": destination}
    if status in (401, 403):
        raise WebSearchError(f"the instance refused the search (HTTP {status}). Enable \"json\" in its "
                             "search.formats (settings.yml), and check the authentication in the web search card")
    if status == 429:
        raise WebSearchError("the instance is rate limiting (HTTP 429): wait a moment, or relax its limiter")
    if status >= 400:
        raise WebSearchError(f"the instance answered HTTP {status}")
    ctype = (headers.get("Content-Type") or "").lower()
    if "json" not in ctype:
        raise WebSearchError(f"the instance answered {ctype or 'without a content type'} instead of JSON: enable "
                             "\"json\" in its search.formats (settings.yml)")
    try:
        parsed = json.loads(body[:4 << 20].decode("utf-8", "replace"))
    except ValueError:
        raise WebSearchError("the instance's answer is not JSON") from None
    if not isinstance(parsed, dict):
        raise WebSearchError("the instance's answer is not a search result")
    results, answer, diagnostics = map_results(parsed, int(settings["max_results"]))
    text, full, cut = format_results(results, answer, int(settings["max_search_chars"]))
    diagnostics["first_url"] = results[0]["url"] if results else ""
    return text, full, cut, diagnostics


# ------------------------------------------------------------------------------------------------ the page reader
class _TextOf(HTMLParser):
    """A page's readable text: scripts and styles dropped, block elements become lines, links keep their address."""

    BLOCK = {"p", "div", "section", "article", "main", "header", "footer", "li", "ul", "ol", "table", "tr", "td",
             "th", "h1", "h2", "h3", "h4", "h5", "h6", "br", "pre", "blockquote", "dd", "dt", "figcaption", "hr"}
    SKIP = {"script", "style", "noscript", "svg", "template", "head", "iframe", "canvas"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.href = None

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
            return
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "a" and not self.skip:
            href = dict(attrs).get("href") or ""
            self.href = href if href.startswith(("http://", "https://")) else None

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if tag == "a" and self.href and not self.skip:
            self.parts.append(f" ({self.href})")
            self.href = None
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def extract_text(body: bytes, content_type: str = "") -> str:
    """A page's bytes -> readable text: HTML is parsed, plain text is taken as it is, entities are decoded."""
    charset = ""
    for piece in (content_type or "").split(";"):
        piece = piece.strip()
        if piece.lower().startswith("charset="):
            charset = piece.split("=", 1)[1].strip().strip("\"'")
    try:
        text = body.decode(charset or "utf-8", "replace")
    except LookupError:
        text = body.decode("utf-8", "replace")
    text = text.lstrip("\ufeff")
    is_html = "html" in (content_type or "").lower() or re.search(r"<(?:!doctype|html|body|p|div|main)\b",
                                                                  text[:4096], re.IGNORECASE)
    if is_html:
        parser = _TextOf()
        parser.feed(text)
        parser.close()
        text = "".join(parser.parts)
    text = re.sub(r"[ \t\r\f\v\u00a0]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def read_page(settings: dict, url: str, cancel=None) -> tuple[str, int, bool, dict]:
    """One address -> (text the model reads, its full length, cut, diagnostics).  WebSearchError: not readable."""
    checked = check_url(url, bool(settings["allow_local"]))
    status, headers, body = 0, None, b""
    hops = 0
    while True:
        status, headers, body = _get(checked, {"User-Agent": USER_AGENT,
                                              "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1"},
                                     float(settings["timeout_s"]), cancel, MAX_PAGE_BYTES)
        if status in (301, 302, 303, 307, 308) and headers.get("Location"):
            hops += 1
            if hops > MAX_REDIRECTS:
                raise WebSearchError(f"the page redirected more than {MAX_REDIRECTS} times")
            checked = check_url(urllib.parse.urljoin(checked, headers["Location"]), bool(settings["allow_local"]))
            continue
        break
    if status == 401 or status == 403:
        raise WebSearchError(f"the page refused the request (HTTP {status}): it needs a login this reader has not got")
    if status == 404:
        raise WebSearchError("the page does not exist (HTTP 404)")
    if status >= 400:
        raise WebSearchError(f"the page answered HTTP {status}")
    ctype = (headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if ctype.startswith(("image/", "video/", "audio/")) or ctype in ("application/pdf", "application/zip",
                                                                     "application/octet-stream", "application/gzip"):
        raise WebSearchError(f"the address is {ctype or 'a file'}, not a readable page")
    if len(body) > MAX_PAGE_BYTES:
        body = body[:MAX_PAGE_BYTES]
    text = extract_text(body, headers.get("Content-Type") or "")
    if not text:
        raise WebSearchError("the page has no readable text (it may be built by JavaScript in the browser)")
    heading = f"{checked}\n\n" if checked else ""
    full = len(heading) + len(text)
    limit = int(settings["max_fetch_chars"])
    if full > limit:
        keep = max(0, limit - len(heading))
        text = heading + text[:keep] + f"\n\n[... cut: the page has {full:,} characters, the first {limit:,} are shown]"
        return text, full, True, {"url": checked, "status": status, "bytes": len(body)}
    return heading + text, full, False, {"url": checked, "status": status, "bytes": len(body)}


# ------------------------------------------------------------------------------------------------ the hub
TOOLS = [
    {"name": "web_search",
     "description": "Search the web and read the results (titles, addresses and snippets). Use it for anything you "
                    "do not know or that changes: release versions, prices, news, documentation, error messages.",
     "parameters": {"type": "object", "properties": {
         "query": {"type": "string", "description": "What to search for, in the user's own words."},
         "max_results": {"type": "integer", "description": "How many results to return (1-20, default 8)."}},
         "required": ["query"]}},
    {"name": "read_page",
     "description": "Read one web page and return its text (scripts and styles are dropped). Use it on an address "
                    "from web_search when its snippet is not enough.",
     "parameters": {"type": "object", "properties": {
         "url": {"type": "string", "description": "The page's address (http or https)."}},
         "required": ["url"]}},
]


class SearchHub:
    """The SearXNG instance as a tool provider: the same shape as serve/mcp.py's McpHub, so the chat's tool loop
    runs it unchanged (routes, template_tools, call, settings)."""

    def __init__(self, settings: dict, source: str = "file"):
        self.settings = {**DEFAULTS, **settings}
        self.settings.setdefault("max_rounds", 8)      # the loop asks every provider for the rounds it allows
        self.name, self.source = SERVER, source        # the tool loop names the provider a call went to

    def configured(self) -> bool:
        return bool(self.settings.get("enabled") and self.settings.get("base_url"))

    def wait(self, timeout: float | None = None) -> None:
        return None                                    # nothing is started: the instance is at the other end

    def close(self) -> None:
        return None

    def tools(self) -> list[dict]:
        return list(TOOLS) if self.settings.get("read_page") else [TOOLS[0]]

    def routes(self) -> dict[str, tuple["SearchHub", str]]:
        return {t["name"]: (self, t["name"]) for t in self.tools()}

    def template_tools(self, exclude=()) -> list[dict]:
        return [{"name": t["name"], "description": t["description"], "parameters": t["parameters"]}
                for t in self.tools() if t["name"] not in exclude]

    def openai_tools(self) -> list[dict]:
        return [{"type": "function", "function": t} for t in self.template_tools()]

    def call(self, name: str, arguments: dict, cancel=None) -> dict:
        """Run one tool -> {"ok", "text", "chars", "truncated", "ms", "server", "tool"} (as McpHub.call)."""
        t0 = time.monotonic()
        arguments = arguments if isinstance(arguments, dict) else {}
        tool = name
        try:
            if name == "web_search":
                limit = arguments.get("max_results")
                settings = self.settings
                if isinstance(limit, (int, float)) and not isinstance(limit, bool):
                    settings = {**settings, "max_results": max(1, min(20, int(limit)))}
                text, full, cut, _ = search(settings, arguments.get("query"), cancel)
            elif name == "read_page":
                text, full, cut, _ = read_page(self.settings, arguments.get("url"), cancel)
            else:
                raise WebSearchError(f"there is no tool named {name!r}")
            ok = True
        except WebSearchCancelled:
            raise
        except WebSearchError as e:
            text, full, cut, ok = f"error: {e}", 0, False, False
        return {"server": SERVER, "tool": tool, "ok": ok, "text": text, "chars": full, "truncated": cut,
                "ms": int((time.monotonic() - t0) * 1000)}

    def status(self) -> dict:
        """GET /search: whether it is set up, the tools it offers, and the settings with the secrets masked."""
        return {"configured": self.configured(), "source": self.source,
                "tools": [t["name"] for t in self.tools()],
                "settings": public_settings({k: v for k, v in self.settings.items() if k in DEFAULTS})}


def settings_for(cfg: dict, path: str | Path) -> dict | None:
    """The settings in force: the run config's `"search"` block, the file's over it.  None: nothing is set up.

    A ValueError (a bad value) stops the start, as a bad MCP entry does."""
    block = cfg.get("search") if isinstance(cfg.get("search"), dict) else {}
    saved = read_settings(path)
    if not block and not saved:
        return None
    merged = {**block, **saved}
    settings = normalize(merged)
    return settings if settings["enabled"] and settings["base_url"] else None
