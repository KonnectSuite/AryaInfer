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

    def test_the_recent_chats_contract(self):
        for name in ("conversations", "chat-search", "chat-list", "chat-menu"):
            self.assertIn(name, self.page.by_id)
        for call in ('$("chat-list").onclick', '$("chat-menu").onclick', '$("chat-search").oninput'):
            self.assertIn(call, self.js)

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
        self.assertEqual(scripts, ["web/app.js"])

    def test_the_icons_the_page_names_are_in_the_sprite(self):
        symbols = set(re.findall(r'<symbol id="([^"]+)"', self.sprite))
        used = set(re.findall(r'sprite\.svg#(i-[a-z0-9-]+)', self.html))
        used |= {f"i-{name}" for name in re.findall(r'icon\("([a-z0-9-]+)"', self.js)}
        self.assertNotEqual(used, set())
        self.assertEqual(sorted(used - symbols), [])

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
