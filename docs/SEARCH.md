# Web search (SearXNG)

AryaInfer has no search engine of its own and sends nothing off this PC unless you ask it to. Point it at a
[SearXNG](https://docs.searxng.org) instance you run or trust - on this PC, on the LAN, or over a Tailnet - and the
chat page offers the model two tools:

| Tool | What the model gives it | What it reads back |
| --- | --- | --- |
| `web_search` | a query, optionally how many results (1-20) | the instant answer when the instance has one, then numbered results: title, address, snippet, date |
| `read_page` | one address from those results | that page as readable text: scripts, styles and navigation dropped, links kept as `text (address)` |

Both run in the server, like the MCP tools ([details](DETAILS.md#tools-from-mcp-servers)): the model asks, AryaInfer
fetches, the model reads the text. The page's chat shows each call as a small block with the query, the result and its
time. **The tools are offered only in the chat page**, only when the card has a URL and its switch is on, and only for
a request that asks for them (`"strata_search": true`, which the page sends); every other client sees the API exactly
as before. They cost the model nothing until it decides to call one.

## Set it up

1. Run a SearXNG instance, or use one you already have. **Its JSON API must be on.** In its `settings.yml`:

   ```yaml
   search:
     formats:
       - html
       - json
   ```

   Without it the instance answers `403` with an HTML page, and the card's Test says so by name (`search.formats`)
   instead of reporting a generic failure.
2. In AryaInfer open **Settings > Tools > Web search**, paste the instance's base URL (for example
   `http://127.0.0.1:8080`, or `https://search.example.ts.net`), and turn **Use web search** on.
3. Press **Test**: it runs one real search with the fields as they are (saved or not) and reports the result count, the
   time, the engines that answered, the engines that did not, and the first address.
4. Press **Save**. The chat offers `web_search` and `read_page` from its next turn; the Sampling drawer has a
   **Use web search** switch to turn them off for a chat without changing the card.

The settings are kept in `websearch.json` beside the run config (one file for every model, since a search instance is
not a model setting). A `"search"` block in `strata-<model>.json` is read too, and the file wins; start the server with
`--search-config other.json` to use another file. Nothing is offered until the switch is on: a fresh install has no
search at all.

| Setting | What it does |
| --- | --- |
| Instance URL | the SearXNG base address, `http(s)://`; no `?query`, no `#hash` |
| Authentication | **None** (a LAN or Tailnet instance), **Bearer token**, **User name and password**, or **custom headers** (for a reverse proxy that wants its own header). A stored secret comes back as `********` and is kept when it is sent back unchanged |
| Language | the instance's language code, e.g. `en` or `pt-BR`; empty uses the instance's default |
| Safe search | off, moderate, strict, or the instance's default |
| Categories | e.g. `general`, `news`, `it`; empty uses the instance's default |
| Time range | any time, or the past day, week, month, year |
| Timeout | 2-60 seconds, default 20: how long a search may take before the model is told it did not answer |
| Results per search | 1-20, default 8 - also the most the model can ask for in one call |
| Offer the page reader | whether `read_page` is offered at all |
| Read pages on this PC and the LAN | off by default: the reader then reads public addresses only (see below) |

## What the model reads

A search becomes plain text, capped at 6,000 characters (the page reader at 6,000 too; both in the settings file):

```text
Instant answer: Qwen3.8 Flash Next is a mixture-of-experts model.

1. Qwen3.8-Flash-Next - model card
   https://example.org/qwen3-8-flash-next
   The card lists the mixture-of-experts sizes, the context the model was trained on and how to run it locally.
   published: 2026-10-01
2. ...
```

A page becomes its text under its address. The model decides what to do with either; the chat page shows the same text
in the call's block so you can check what it was told. Results over the cap are cut with a note saying so.

## What it does not do

- **No page fetching through SearXNG.** SearXNG searches; it cannot fetch an arbitrary page. `read_page` fetches it
  here, and only for the two schemes `http` and `https`.
- **No private addresses by default.** The reader refuses a host that resolves to a loopback, link-local, private,
  multicast or otherwise non-public address (`127.0.0.1`, `10.0.0.1`, `169.254.169.254`, a `.local` name), with a
  message that names `allow_local`. That switch exists for reading your own wiki or router page; leave it off unless
  you want the model to be able to read whatever this PC can reach.
- **No credentials in a URL.** `http://user:pass@host/` is refused: put the credentials in the card, where they are
  stored once and masked in the page.
- **No cookies, no login, no JavaScript.** A page that needs a session, or builds itself in the browser, comes back as
  "no readable text (it may be built by JavaScript in the browser)".
- **No fallback engine.** If the instance is unreachable the call fails with the reason, and the model is told
  `error: ...` so it can say what happened or try another query.

## Security

Search results and page text are **untrusted content**: a page can contain instructions aimed at the model, and the
model may follow them. That is the same exposure as opening the link yourself in a chat, with two differences worth
knowing: the model can read many pages quickly, and then act with the tools you gave it (an MCP filesystem server, for
example). Prefer an instance that does not run its engines with your accounts logged in, and give the model only the
MCP tools you would give a stranger.

`read_page` is guarded so it cannot be pointed at this PC's own services by accident: public addresses only, unless
`allow_local` is on. The check resolves the name and refuses non-public addresses, and it is re-checked at every
redirect hop. It does not defend against a name that changes its answer between the check and the fetch (DNS
rebinding) - the tool runs with your rights on a machine you control, not as a public web service.

## Failure modes

| What you see | What it means |
| --- | --- |
| `the instance refused the search (HTTP 403). Enable "json" in its search.formats` | its JSON API is off, or a proxy refused the request: fix `settings.yml`, then check the card's authentication |
| `the instance answered text/html instead of JSON` | JSON is off, but the instance did not refuse: same fix |
| `the instance is rate limiting (HTTP 429)` | wait, or relax its limiter for this client |
| `the instance answered HTTP 5xx` | the instance's own engines or process are failing: its log says which |
| `no answer within 20 s` | the instance is slow or unreachable: raise the timeout, or use another instance |
| `could not be reached` / `refused` | wrong URL or port, or the instance is not running |
| `no results` | the query found nothing (a rare word, a `!bang` to an engine that is off) |
| `... resolves to 127.0.0.1, a local or private address` | `read_page` against a local address with `allow_local` off |
| `the page has no readable text` | a JavaScript-only page, a PDF, or an image |

## The code

| Path | What it is |
| --- | --- |
| `serve/websearch.py` | the instance client, the page reader, the settings file and the two tools |
| `serve/toolhub.py` | the MCP tools and the search tools behind one provider for the chat's tool loop |
| `serve/search_fake_server.py` | a SearXNG-shaped instance for the tests (no network beyond localhost) |
| `serve/test_websearch.py` | the tests: mapping, settings, every failure mode, the page reader, the chat loop |

`python -m unittest serve.test_websearch` runs them without a GPU, a model or a real instance.
