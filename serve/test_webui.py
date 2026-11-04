"""serve/test_webui.py - the chat page's static contract, checked without a browser or a server.

The page is one HTML file and one classic script, so most of its wiring can be proved by reading them: every element
the script looks up exists, the kit's icons it names exist, nothing is loaded from another machine, and the parts the
other suites pin (the conversation-cache card, the model-settings form) are still where they were promised.

    python -m unittest serve.test_webui -v
"""
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "serve" / "web"
HTML = WEB / "index.html"
JS = WEB / "app.js"
SPRITE = WEB / "sprite.svg"

VOID = {"img", "input", "br", "hr", "meta", "link", "source", "col", "area", "base", "embed", "track", "wbr"}


class Page(HTMLParser):
    """Every element with an id, and the elements it sits inside (by id and class)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []                 # [(tag, class, id)]
        self.by_id = {}                 # id -> (tag, class, ancestors)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        node = (tag, a.get("class", ""), a.get("id"))
        if node[2]:
            self.by_id[node[2]] = (tag, node[1], tuple(self.stack))
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):                 # a self-closing element still counts as present
            self.by_id[a["id"]] = (tag, a.get("class", ""), tuple(self.stack))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return


def load():
    page = Page()
    page.feed(HTML.read_text(encoding="utf-8"))
    page.close()
    return page


def inside(page, element, container_id):
    """True when the element sits inside the element with that id (or is it)."""
    if element not in page.by_id:
        return False
    return any(node[2] == container_id for node in page.by_id[element][2])


class Contract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = load()
        cls.html = HTML.read_text(encoding="utf-8")
        cls.js = JS.read_text(encoding="utf-8")
        cls.room = (WEB / "room.js").read_text(encoding="utf-8")
        cls.templates = (WEB / "comfy-templates.js").read_text(encoding="utf-8")
        cls.sprite = SPRITE.read_text(encoding="utf-8")

    def test_every_element_the_script_looks_up_exists(self):
        # $("id") in the script, plus the four views it builds as $(`view-${name}`)
        used = set(re.findall(r'\$\("([^"]+)"\)', self.js))
        used |= {f"view-{name}" for name in ("chat", "images", "monitor", "about")}
        self.assertNotEqual(used, set())
        missing = sorted(name for name in used if name not in self.page.by_id)
        self.assertEqual(missing, [], "the page has no element with these ids: " + ", ".join(missing))

    def test_the_shell_is_a_sidebar_and_a_main_column(self):
        for name in ("sidebar", "sidebar-collapse", "sidebar-toggle", "new-btn", "nav-chat", "nav-monitor",
                     "nav-about", "conversations", "chat-search", "chat-list", "mcp-nav", "models-nav",
                     "settings-btn", "view-title"):
            self.assertIn(name, self.page.by_id)

    def test_settings_holds_appearance_the_key_and_the_model_settings(self):
        for name in ("settings-pop", "theme-seg", "api-key", "cfg-card", "cfg-form", "cfg-save", "cfg-msg",
                     "about-link"):
            self.assertIn(name, self.page.by_id)
            self.assertTrue(inside(self.page, name, "settings-pop") or name == "settings-pop", name)
        self.assertFalse(inside(self.page, "api-key", "view-about"))
        self.assertFalse(inside(self.page, "cfg-card", "view-about"))

    def test_the_model_picker_is_in_the_composer(self):
        for name in ("model-select", "model-btn", "model-menu"):
            self.assertIn(name, self.page.by_id)
        self.assertTrue(inside(self.page, "model-select", "composer"))
        self.assertTrue(inside(self.page, "model-btn", "composer"))
        self.assertIn('$("models-nav").onclick', self.js)      # the sidebar row opens the same menu

    def test_the_footer_reports_this_chats_usage(self):
        # three chips under the composer, each with the popover behind its number
        for name in ("chat-foot", "foot-turns", "foot-turns-text", "foot-tokens", "foot-tokens-text",
                     "foot-context", "foot-context-text", "foot-turns-pop", "foot-tokens-pop", "foot-context-pop"):
            self.assertIn(name, self.page.by_id)
        for name in ("foot-turns", "foot-tokens", "foot-context"):
            self.assertTrue(inside(self.page, name, "chat-foot"), name)
        for pop in ("foot-turns-pop", "foot-tokens-pop", "foot-context-pop"):
            self.assertIn("st-menu", self.page.by_id[pop][1], pop)      # the menus' surface, opened by its chip
            self.assertTrue(inside(self.page, pop, "chat-foot"), pop)
        for needle in ("function blankStats(", "function renderFoot(", "j.strata_context",
                       "chat.stats || (chat.stats = blankStats())",
                       "Session statistics", "Token usage", "of context used",
                       "LLM time", "Tool time", "Avg time to first token (TTFT)", "Tokens per second (TPS)",
                       "Cache hit", "Uncached input", "Cached input", "System prompt", "Tool definitions",
                       "footStats.turns += 1", "footStats.steps += 1 + ran", "openFootPop("):
            self.assertIn(needle, self.js, needle)
        # the figures are the request's own: the server's usage, and its split of the prompt
        self.assertIn("usage.prompt_tokens_details", self.js)
        self.assertIn("usage.completion_tokens", self.js)
        css = (WEB / "app.css").read_text(encoding="utf-8")
        for rule in (".chat-foot", ".chat-foot__chip", ".foot-pop__bar", ".foot-pop__seg--system",
                     ".foot-pop__seg--tools", ".foot-pop__seg--messages"):
            self.assertIn(rule, css, rule)

    def test_the_recent_chats_contract(self):
        for name in ("conversations", "chat-search", "chat-list", "chat-menu"):
            self.assertIn(name, self.page.by_id)
        for call in ('$("chat-list").onclick', '$("chat-menu").onclick', '$("chat-search").oninput'):
            self.assertIn(call, self.js)
        # sessions are filed by day, and a chat can be archived (hidden but kept) or deleted
        self.assertIn('data-chat-act="archive"', self.html)
        for needle in ("function archiveChat(", "function chatGroupLabel(", '"Today"', '"Yesterday"',
                       '"Previous 7 days"', '"Previous 30 days"', '"Older"', '"Archived"',
                       "st-chat-item--archived", '[data-chat-act="archive"] span'):
            self.assertIn(needle, self.js, needle)
        css = (WEB / "app.css").read_text(encoding="utf-8")
        for rule in (".st-chat-group", ".st-chat-item__tag", ".st-chat-item--archived"):
            self.assertIn(rule, css, rule)

    def test_the_mcp_dialog_contract(self):
        for name in ("mcp-dialog", "mcp-list", "mcp-detail", "mcp-add", "mcp-add-view", "mcp-catalog",
                     "mcp-catalog-search", "mcp-paste", "mcp-paste-add", "mcp-form", "mcp-name", "mcp-kind",
                     "mcp-stdio", "mcp-http", "mcp-command", "mcp-args", "mcp-env", "mcp-cwd", "mcp-url",
                     "mcp-headers", "mcp-disabled", "mcp-save", "mcp-cancel", "mcp-msg", "mcp-close", "mcp-open",
                     "mcp-filter", "mcp-count"):
            self.assertIn(name, self.page.by_id, name)
        self.assertIn('$("mcp-form").onsubmit', self.js)          # Enter saves, it does not reload
        self.assertIn("mcp-servers.json", self.html)

    def test_the_web_search_dialog_contract(self):
        for name in ("search-dialog", "search-form", "search-enabled", "search-url", "search-url-note",
                     "search-test-query", "search-test", "search-test-result", "search-save", "search-msg",
                     "search-sum", "search-open", "search-close", "search-state"):
            self.assertIn(name, self.page.by_id, name)
        self.assertIn('$("search-form").onsubmit', self.js)
        self.assertNotIn("prompt(", self.js)                      # the test query is a field, not a prompt box

    def test_the_catalog_is_well_formed(self):
        catalog = (WEB / "mcp-catalog.js").read_text(encoding="utf-8")
        self.assertIn("window.MCP_CATALOG", catalog)
        ids = re.findall(r'\bid:\s*"([^"]+)"', catalog)
        self.assertGreaterEqual(len(ids), 18)
        self.assertEqual(sorted(ids), sorted(set(ids)), "a catalog id is used twice")
        for transport in re.findall(r'transport:\s*"([^"]+)"', catalog):
            self.assertIn(transport, ("stdio", "http"))
        # every icon a catalog entry names is a symbol in the MCP sprite
        sprite = (WEB / "mcp-icons.svg").read_text(encoding="utf-8")
        symbols = set(re.findall(r'<symbol id="m-([^"]+)"', sprite))
        used = set(re.findall(r'icon:\s*"([^"]+)"', catalog))
        self.assertEqual(sorted(used - symbols), [], "the catalog names icons the sprite lacks")

    def test_the_chat_render_contract(self):
        # the right panel is gone: none of its ids, and no toggle for it
        for name in ("workbench", "wb-toggle", "wb-close", "wb-resize", "wb-frame", "wb-stage", "wb-artifact",
                     "wb-files", "wb-url", "wb-read", "wb-activity", "wb-download", "wb-open"):
            self.assertNotIn(name, self.page.by_id, name)
        # the frame that renders a model-written page: scripts yes, anything else no, and never this page's origin
        self.assertIn('class="st-artifact__frame" sandbox="allow-scripts"', self.js)
        self.assertNotIn("allow-same-origin", self.js)
        self.assertIn("default-src 'none'", self.js)                 # no network from an artifact
        self.assertIn("function sameOriginImage(", self.js)          # only this server's pictures, never the internet
        # every rendered block downloads from the answer itself; nothing goes through a side panel
        for needle in ("data-artifact-download", "function downloadArtifact(", "function artifactFileName("):
            self.assertIn(needle, self.js, needle)
        self.assertNotIn("data-wb-image", self.js)

    def test_the_images_dialog_contract(self):
        for name in ("image-dialog", "image-close", "image-status", "image-url", "image-url-note", "image-headers",
                     "image-timeout", "image-launch-mode", "image-server-dir", "image-python", "image-extra-args",
                     "image-task", "image-auto-start", "image-start", "image-stop", "image-restart",
                     "image-server-state", "image-workflows", "image-import", "image-file", "image-check",
                     "image-check-result", "image-policy", "image-need", "image-max-files", "image-max-mib",
                     "image-save", "image-msg", "images-open", "images-sum", "images-row", "s-images"):
            self.assertIn(name, self.page.by_id, name)
        for call in ('$("images-open").onclick', '$("image-save").onclick', '$("image-check").onclick',
                     '$("image-start").onclick', '$("image-stop").onclick', '$("image-restart").onclick'):
            self.assertIn(call, self.js)
        self.assertIn('fetch("comfy"', self.js)                       # relative: only this server
        self.assertIn('body.strata_images = true', self.js)           # the chat's opt-in for the image tool

    def test_the_images_room_contract(self):
        # a conversation, not a form: the agent writes the prompt and picks the workflow
        for name in ("room-provider", "room-status", "room-settings", "room-new", "room-tabs", "room-tab-local",
                     "room-chat", "room-search", "room-favs", "room-count-note", "room-grid", "room-more",
                     "room-templates", "room-form", "room-prompt", "room-refs", "room-ref-btn", "room-ref-file",
                     "room-cancel", "room-go", "room-hint", "room-viewer", "room-viewer-img", "room-viewer-meta",
                     "room-viewer-actions", "room-viewer-close", "room-viewer-prev", "room-viewer-next",
                     "img-form", "img-prompt"):
            self.assertIn(name, self.page.by_id, name)
        self.assertIn('src="web/room.js"', self.html)
        self.assertIn('src="web/comfy-templates.js"', self.html)
        for call in ('$("room-form").onsubmit', '$("room-new").onclick', '$("room-favs").onclick',
                     '$("room-more").onclick', '$("room-viewer-close").onclick'):
            self.assertIn(call, self.room)
        self.assertIn('fetch("v1/chat/completions"', self.room)   # the same endpoint as the chat
        self.assertIn("fetch(`comfy?", self.room)                # relative: only this server
        self.assertIn("attached.length ? {references:", self.room)   # attached pictures ride with the request
        self.assertIn('room.messages.push({role: "user", text, refs: attached})', self.room)
        self.assertIn("room-bubble__refs", self.room)               # ... and are shown on that turn
        self.assertIn("The next request edits the attached picture", self.room)
        self.assertIn("refs: (m.refs || [])", self.room)            # they survive a reload
        self.assertIn("reference_id", self.room)                    # "change that one" names the last picture
        self.assertNotIn("api_base", self.room)
        self.assertGreaterEqual(self.templates.count("prompt:"), 8)

    def test_the_room_uses_the_chat_composer_and_a_full_width_gallery(self):
        # one message box for both views, so the two cannot drift apart
        self.assertIn('class="st-composer room__form"', self.html)
        self.assertIn('$("room-form").hidden = tab !== "create"', self.room)   # it belongs to the conversation
        css = (WEB / "app.css").read_text(encoding="utf-8")
        self.assertIn(".room__form { flex: none; margin-top: 8px; width: 100%; }", css)
        self.assertIn("minmax(220px, 1fr)", css)                                # the gallery fills the width
        self.assertIn(".room-card__prompt { position: absolute", css)           # the prompt rides over the picture
        self.assertIn("minmax(150px, 1fr)", css)                                # two a row on a phone

    def test_the_tools_show_their_state_in_the_header(self):
        for name in ("tool-pills", "pill-search", "pill-images"):
            self.assertIn(name, self.page.by_id, name)
        for call in ('$("pill-search").onclick', '$("pill-images").onclick', "function renderToolPills()"):
            self.assertIn(call, self.js, call)
        self.assertIn("renderToolPills();", self.js)
        self.assertIn('renderToolPills();                       // the switches for web search and images',
                      self.js)                                  # a switch in the drawer moves the light
        self.assertIn("function openSearchDialog()", self.js)
        css = (WEB / "app.css").read_text(encoding="utf-8")
        for state in ('[data-state="on"]', '[data-state="down"]'):
            self.assertIn(state, css)
        self.assertIn(".st-tool__label { display: none; }", css)   # a phone keeps the lights, not the words

    def test_a_viewbox_only_svg_fills_its_frame(self):
        # `max-height:96%` inside an auto-height grid row resolved to zero in Chrome: every viewBox-only SVG (the
        # model's usual shape) previewed as a blank frame.  The wrapper flexes and gives the SVG the whole box.
        body = self.js[self.js.index("function wbDoc(a)"):]
        body = body[:body.index("\n}")]
        self.assertIn("body{display:flex", body)
        self.assertIn("svg{display:block;width:100%;height:100%}", body)
        self.assertNotIn("svg{max-width:96%", body)

    def test_written_pages_render_in_the_answer(self):
        for needle in ("data-artifact-download", "st-artifact__frame", "function downloadArtifact(",
                       "codeBlock(m[2].trim(), rest, {live: true})",   # a streaming block stays code
                       "sandbox=\"allow-scripts\""):
            self.assertIn(needle, self.js, needle)
        css = (WEB / "app.css").read_text(encoding="utf-8")
        self.assertIn(".st-artifact__frame", css)
        self.assertIn(".room-bubble__ref", css)

    def test_the_views_still_carry_what_the_other_suites_pin(self):
        for name in ("cc-card", "cc-slots-text", "cc-mem-text", "cc-facts", "cc-note"):
            self.assertIn(name, self.page.by_id)
            self.assertIn(f'"{name}"', self.js)
        for name in ("cfg-card", "cfg-form", "cfg-save", "cfg-msg"):
            self.assertIn(f'id="{name}"', self.html)

    def test_nothing_is_loaded_from_another_machine(self):
        self.assertIsNone(re.search(r'src="https?://', self.html), "the page must load only this server's files")
        self.assertIsNone(re.search(r'fetch\(\s*[`"]https?://', self.js), "the page must talk only to this server")
        scripts = re.findall(r'<script[^>]*src="([^"]+)"', self.html)
        self.assertEqual(scripts, ["web/mcp-catalog.js", "web/app.js", "web/comfy-templates.js", "web/room.js"])

    def test_the_icons_the_page_names_are_in_the_sprite(self):
        symbols = set(re.findall(r'<symbol id="([^"]+)"', self.sprite))
        used = set(re.findall(r'sprite\.svg#(i-[a-z0-9-]+)', self.html))
        used |= {f"i-{name}" for name in re.findall(r'icon\("([a-z0-9-]+)"', self.js)}
        self.assertNotEqual(used, set())
        self.assertEqual(sorted(used - symbols), [])

    def test_saving_a_chat_keeps_the_live_turns(self):
        # saveChat must not re-point `messages` at the stored copy: that dropped every turn added since the last save,
        # so the model only ever saw alternate turns ("no context" in a normal conversation)
        body = self.js[self.js.index("function saveChat()"):]
        body = body[:body.index("\n}")]
        self.assertNotIn("const chat = ensureChat()", body)
        self.assertNotIn("chat.messages =", body)
        self.assertIn("savedMessages(messages)", body)

    def test_the_phone_contract(self):
        # an iPhone is a narrow, coarse-pointer screen: the things that only worked with a mouse must work there too
        self.assertIn('content="width=device-width, initial-scale=1, viewport-fit=cover"', self.html)
        css = (WEB / "app.css").read_text(encoding="utf-8")
        self.assertIn("@media (hover: none), (pointer: coarse)", css)
        self.assertIn(".st-chat-item__menu { opacity: 1; }", css)     # hover-only menus become visible
        self.assertIn("@supports (height: 100dvh)", css)             # the browser bars move
        self.assertIn("env(safe-area-inset-bottom)", css)            # the home indicator
        self.assertRegex(css, r"\.st-menu \{[^}]*bottom: calc\(10px \+ env\(safe-area-inset-bottom\)\)")
        self.assertIn("font-size: 16px;", css)                       # no zoom when a field takes focus
        for name in ("voice-btn", "room-voice-btn"):
            self.assertIn(name, self.page.by_id, name)
        self.assertIn("webkitSpeechRecognition", self.js)
        self.assertIn('setupVoice($("voice-btn"), $("input"))', self.js)
        self.assertIn('setupVoice($("room-voice-btn"), $("room-prompt"))', self.room)
        self.assertIn("is-recording", css)
        # the composer's row of buttons wraps instead of pushing Send off the screen
        self.assertIn(".st-composer__bar { flex-wrap: wrap;", css)
        # the MCP dialog's two panes become one column
        self.assertIn(".mcp-panes { grid-template-columns: 1fr;", css)

    def test_no_leftover_tab_markup(self):
        # the header's tab row became the sidebar's nav; nothing should still style or query the old classes
        self.assertNotIn('class="st-tab"', self.html)
        self.assertNotIn(".st-tab", self.js)
        self.assertNotIn('$("tab-btn-', self.js)


class Storage(unittest.TestCase):
    """The page keeps everything in this browser: the keys it writes are named here so a change is deliberate."""

    def test_the_stored_keys(self):
        js = JS.read_text(encoding="utf-8")
        for key in ('"strata.theme"', '"strata." + k', '"apikey"', '"chats"', '"chat"', '"sampling"', '"sidebar"'):
            self.assertIn(key, js)

    def test_the_chat_list_is_capped_and_migrated(self):
        js = JS.read_text(encoding="utf-8")
        self.assertIn("CHAT_CAP = 50", js)
        self.assertIn('OLD_CHAT_STORE = "chat"', js)
        self.assertIn("version: 1, active: activeChat, items: chats", js)


if __name__ == "__main__":
    unittest.main()
